#!/usr/bin/env python3
"""parse-nta-tsutatsu.py -- NTA HTML tsutatsu (circular) -> Directive JSONL chunks.

Usage:
    python tools/parse/parse-nta-tsutatsu.py \\
        --circular hojin \\
        --cache-dir cache/tsutatsu/hojin/09 \\
        --output-dir build/chunks/hojin-kihon-tsutatsu \\
        --chapter 09

The circular's law_name / NTA URL base / reference-prefix map come from its
CircularConfig (selected by --circular); law_abbrev is derived from that config.

Output: build/chunks/hojin-kihon-tsutatsu/hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl

One record per directive item (e.g. 9-2-9).
Each record has:
    id              : "hojin-kihon-tsutatsu-9-2-9"  (directive_id)
    directive_id    : same as id
    law_name_ja     : "法人税基本通達"
    law_abbrev      : "hojin-kihon-tsutatsu"
    chapter_section : "9-2" (chapter-section prefix)
    directive_number: "9-2-9"
    title           : "(債務の免除による利益その他の経済的な利益)"
    text            : full body text (Markdown, items as list)
    amendment_note  : raw amendment string e.g. "(平19年課法2-3...)"
    related_articles: list of {law_abbrev, article_id, article_number, raw}
    source_url      : "https://www.nta.go.jp/law/tsutatsu/kihon/hojin/09/09_02_02.htm"
    license         : "public-domain-13-2"
    segment_type    : "tsutatsu"
    article_id      : None  (for retrieve.py compatibility)
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
import unicodedata
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Literal

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")

# juricode_shared を import 可能にする (DirectiveChunk による出力検証用)。
# 取込ループは main() の sys.path patch より前に走るため module レベルで patch する
# (parse-nta-taxanswer.py と同パターン)。
_SHARED_SRC = Path(__file__).resolve().parents[1] / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LICENSE = "public-domain-13-2"


# ---------------------------------------------------------------------------
# Per-circular config (法人税 / 消費税 ... を 1 セレクタで切替・Bug37 回避)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CircularConfig:
    """1 通達分の取込パラメータ (法人税固定の解消・FU-514 後段)。

    Why: parser ロジックは通達非依存だが、通達名・NTA URL ベース・参照接頭辞マップ
    だけが通達ごとに違う。これらをコード内 config 定数として束ね `--circular` で
    選択する (CLI に dict を渡さない=デシリアライズ不要で型不整合 Bug を構造的に回避)。
    ref_map は必須フィールド (mutable default を持たせない)。corpus 未登録の参照先は
    corpus_unregistered に列挙し unlinked として扱う。
    """

    law_name_ja: str
    law_abbrev: str
    source_url_base: str
    ref_map: Mapping[str, str]  # {"法": <law>, "令": <shikkourei>, "規": <shikoukisoku>, ...}
    corpus_unregistered: frozenset[str] = field(default_factory=frozenset)
    license: str = LICENSE
    # 本文末尾の改正注記を抽出する NTA 内部記号 (法人税="課法"+旧称"直法" / 消費税="課消")。
    # 「（<元号><年><部門記号><番号>…）」形式。部門記号は通達ごと、かつ法人税は 2001 年
    # (平成13年) の組織改編で「直法」→「課法」に改称したため旧章は "直法" を併用する。
    # tuple で複数記号を許し、抽出正規表現はこれらの alternation で組む。
    amendment_markers: tuple[str, ...] = ("課法",)
    # 通達番号のレベル数。法人税/消費税は 3 レベル (章-節-項)、所得税基本通達は 2 レベル
    # (条-番号 = "204-1")。番号検出正規表現と directive_id 形式ゲートをこの値で駆動する。
    # 既定 3 で HOJIN/SHOUHI は移行前と完全一致 (byte 回帰で実証)。num_style="flat_branch"
    # のときは num_levels は不使用 (flat_branch は単発番号 + 任意枝番でレベル数を持たない)。
    num_levels: int = 3
    # 番号体系のスタイル。
    #   "hierarchical" (既定): 階層番号 (章-節-項 / 条-番号)。レベルは "-" で必ず連結され、
    #       この必須ハイフンが (注) 注記の平文 "1 …" を通達番号から弾く判別子になる。
    #   "flat_branch": 財産評価基本通達型。章跨ぎの単発通し番号 (1..215) + 任意の単一ダッシュ
    #       枝番 ("4-2")。単発番号は番号形だけでは注記・別表行と区別できないため、番号が
    #       <strong> 内にある段落のみ通達開始とみなす (実 HTML で strong 付き 313 件が全 unique
    #       な真通達・平文番号 40 件は全て (注)/別表 と確認済)。既定 hierarchical は全経路で
    #       現行と完全一致 (byte 回帰で実証)。
    #   "kan_paren": 租税特別措置法通達型 (FU-536)。条 と 項 の間に款マーカー (N)/（N） を持つ
    #       (62の3（1）－1 = 62条の3 第1款 -1) ため階層に款レベルを畳み込む (62の3-1-1)。条跨ぎ
    #       共通マーカー （共） も持つ (42の5～48（共）－1 -> 42の5_48共-1)。款の有無で dash-level
    #       が 2 (条-項) / 3 (条-款-項) に変動するため num_levels ではなく可変 tail で検証する。
    #   "hier_var": hierarchical の可変レベル版 (FU-543・sochi-sozoku 専用)。同一編内で 2 レベル
    #       (条-通達 69の4-27) と 3 レベル (条-項-通達 70-1-3 = 70条1項 通達3) を混在させる編で、
    #       num_levels 固定 2 では 3 レベルを、固定 3 では 2 レベルを取りこぼす。dash-level を
    #       {1,2} の可変個 (先頭条レベルに続く 1〜2 個の "-N") で組み、款 fold も全角正規化もせず
    #       (既定 _normalize_directive_num 経路 = _RANGE_SEP_RE のみ・全角 verbatim) hierarchical と
    #       完全に同じ正規化を通す。旧法 (「旧」始まり) は数値開始の _FIRST_LEVEL に非マッチで自然除外。
    num_style: Literal["hierarchical", "flat_branch", "kan_paren", "hier_var"] = "hierarchical"
    # 取込から除外するファイル名 (basename) の集合。既定は空 = 全ファイル取込 (byte 不変)。
    # 措置法通達は改正で同一条番号に別制度が併載される事故があり (旧 02_57_4.htm 原子力発電施設
    # 解体準備金 vs 新 02_57_4_2.htm 特定原子力施設炉心等除去準備金 = 同 id 異本文 fail-loud)、
    # 旧版を basename で機械除外する。多章 (--cache-root) / 単章 (--cache-dir) 両モードで効く。
    exclude_files: frozenset[str] = field(default_factory=frozenset)


# 法人税基本通達 (既定・byte 回帰で固定。値は移行前の module 定数と完全一致)。
HOJIN_CONFIG = CircularConfig(
    law_name_ja="法人税基本通達",
    law_abbrev="hojin-kihon-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kihon/hojin",
    ref_map={
        "法": "houjin-zei-hou",
        "令": "houjin-zei-hou-shikkourei",
        "規": "houjin-zei-hou-shikoukisoku",
        "措法": "sochi-hou",  # corpus 未収録 -> warn, no link
    },
    corpus_unregistered=frozenset({"sochi-hou"}),
    # 課法 (現行) + 直法 (2001 年改編前の旧称)。旧章の末尾改正注記
    # 「（昭55年直法2-8「十」…）」を取りこぼさない (9-2 sentinel は末尾 直法 ゼロ = byte 不変)。
    amendment_markers=("課法", "直法"),
)

# 消費税法基本通達。source_url_base の NTA パスは "shohi" (実 URL で確認済・我々の
# abbrev "shouhi" とは独立)。参照接頭辞は corpus 実在の shouhi-zei-hou 系に対応。
# 第1章は 法/令 のみ参照 (規/措法なし) で全件 corpus 内 -> corpus_unregistered 空。
SHOUHI_CONFIG = CircularConfig(
    law_name_ja="消費税法基本通達",
    law_abbrev="shouhi-kihon-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kihon/shohi",
    ref_map={
        "法": "shouhi-zei-hou",
        "令": "shouhi-zei-hou-shikkourei",
        "規": "shouhi-zei-hou-shikoukisoku",
    },
    corpus_unregistered=frozenset(),
    amendment_markers=("課消",),  # 消費税通達の改正注記記号 (例: 平28課消1-57)
)

# 所得税法基本通達。HOJIN/SHOUHI と違い番号は 2 レベル (条-番号 = "204-1")。NTA URL パスは
# "shotoku"。改正記号は実測 8 値 + 官房総務課系 "官総"(×2)。条範囲の通達 (74・75-1 等) は
# 番号先頭レベルに中点 "・"(U+30FB) を含み、取込時に "_" へ正規化する (74・75-1 -> 74_75-1)。
SHOTOKU_CONFIG = CircularConfig(
    law_name_ja="所得税法基本通達",
    law_abbrev="shotoku-kihon-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kihon/shotoku",
    ref_map={
        "法": "shotoku-zei-hou",
        "令": "shotoku-zei-hou-shikkourei",
        "規": "shotoku-zei-hou-shikoukisoku",
    },
    corpus_unregistered=frozenset(),
    amendment_markers=("課個", "直所", "直法", "直資", "課所", "課資", "課法", "課審", "官総"),
    num_levels=2,
)

# 相続税法基本通達。num_levels=2 (目次の条-番号 2 レベル体系 "1の2-1" / "23の2-1" 等で確定・
# 実パーサ dry-run で 445 directives 取得を実測)。NTA URL パスは "sisan/sozoku2" (実 URL で
# 確認済・"souzoku"/"sozoku" は 404)。参照は相続税法系列 + 措置法(小規模宅地等) + 通則法 +
# 所得税法 + 地価税法。措置法/地価税法は corpus 未収録 (unlinked)、他 5 法は data/v0.2/phase1-tax
# に実在しリンク有効。接頭辞は _build_law_ref_re が長い順に組むので「措置法第N条」を「法」に
# 潰さず正しく解決する。改正記号は資産税系 課資/直資/課審/課評 (実測 513/211/63/16)。
SOUZOKU_CONFIG = CircularConfig(
    law_name_ja="相続税法基本通達",
    law_abbrev="souzoku-kihon-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kihon/sisan/sozoku2",
    ref_map={
        "措置法": "sochi-hou",  # 租税特別措置法 (corpus 未収録 -> warn, no link)
        "通則法": "kokuzei-tsuusoku-hou",  # 国税通則法 (corpus 実在 -> link)
        "所得税法": "shotoku-zei-hou",  # 所得税法 (corpus 実在 -> link)
        "地価税法": "chika-zei-hou",  # 地価税法 (corpus 未収録 -> warn, no link)
        "法": "souzoku-zei-hou",  # 相続税法 (corpus 実在 -> link)
        "令": "souzoku-zei-hou-shikkourei",  # 相続税法施行令 (corpus 実在 -> link)
        "規": "souzoku-zei-hou-shikoukisoku",  # 相続税法施行規則 (corpus 実在 -> link)
    },
    corpus_unregistered=frozenset({"sochi-hou", "chika-zei-hou"}),
    amendment_markers=("課資", "直資", "課審", "課評"),
    num_levels=2,
)

# 財産評価基本通達。num_style="flat_branch" (章跨ぎの単発通し番号 1..215 + 任意の単一ダッシュ
# 枝番 "4-2"。実 HTML で strong 付き番号 313 件が全 unique な真通達・平文番号 40 件は全て (注)
# 注記/別表行と実測確認)。NTA URL パスは "sisan/hyoka_new" (web_fetch 実確認・"hyoka"/"souzoku"
# は 404)。改正記号は資産税系の実測 3 値 課評(492)/直資(152)/直評(63)。単発 "評" はゼロ (全て
# 2 文字コードゆえ本文の "評価" を誤って改正注記と誤認しない)。参照は **完全名のみ** を key にする: 財産評価
# 通達は "法第N条" の裸接頭辞を使わず 会社法/建築基準法/都市計画法/農地法等の named-law を多数
# 引くため、裸 "法"/"令"/"規" を ref_map に入れると trailing 法 に誤マッチして相続税法へ偽リンク
# する (実測: 建築基準法/会社法/地方税法等 ~30 件)。相続税法(実在→link)/所得税法/法人税法(実在)/
# 地価税法(未収録→warn) の完全名だけを登録し偽リンクを構造的に排除する。
HYOKA_CONFIG = CircularConfig(
    law_name_ja="財産評価基本通達",
    law_abbrev="zaisan-hyoka-kihon-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kihon/sisan/hyoka_new",
    ref_map={
        "相続税法": "souzoku-zei-hou",  # 相続税法 (corpus 実在 -> link)。評価通達の主法。
        "所得税法": "shotoku-zei-hou",  # 所得税法 (corpus 実在 -> link)
        "法人税法": "houjin-zei-hou",  # 法人税法 (corpus 実在 -> link)
        "地価税法": "chika-zei-hou",  # 地価税法 (corpus 未収録 -> warn, no link)
    },
    corpus_unregistered=frozenset({"chika-zei-hou"}),
    amendment_markers=("課評", "直資", "直評"),
    num_style="flat_branch",
)

# 租税特別措置法関係通達 (法人税編)・FU-536。num_style="kan_paren" (款マーカー (N)/（N） +
# 条跨ぎ （共）)。NTA URL は個別通達パス "kobetsu/hojin/sochiho/750214" (発遣 直法2-2・
# 昭50.2.14・web_fetch 実確認)。改正記号は法人税系 課法/直法。ref_map は **実本文の表記を
# probe-don't-guess で実測** して full 形で登録する (P0-3): 本体 措置法(724)・施行令 措置法令
# (405・短縮形) ・施行規則 措置法規則、法人税法系は裸 法(882)/令(437)。_build_law_ref_re は
# 長い接頭辞を優先するので「措置法令第N条」を「措置法」や裸「令」へ潰さず解決する。措置法系は
# FU-535 で corpus 実在ゆえ全 link (corpus_unregistered 空)。旧 02_57_4.htm は除外 (exclude_files)。
SOCHI_HOJIN_CONFIG = CircularConfig(
    law_name_ja="租税特別措置法関係通達（法人税編）",
    law_abbrev="sochi-hojin-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kobetsu/hojin/sochiho/750214",
    ref_map={
        "措置法令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (短縮形 措置法令・corpus 実在)
        "措置法規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (corpus 実在)
        "措置法": "sochi-hou",  # 租税特別措置法 (本体・corpus 実在)
        "法": "houjin-zei-hou",  # 法人税法 (裸「法」)
        "令": "houjin-zei-hou-shikkourei",  # 法人税法施行令 (裸「令」)
        "規": "houjin-zei-hou-shikoukisoku",  # 法人税法施行規則 (裸「規」)
    },
    corpus_unregistered=frozenset(),
    amendment_markers=("課法", "直法"),
    num_style="kan_paren",
    exclude_files=frozenset({"02_57_4.htm"}),
)

# 租税特別措置法関係通達 (山林所得・譲渡所得関係)・FU-539。sochi-hojin (法人税編) を逐語コピーし
# 所得税分野の値へ変更。num_style は kan_paren ではなく "hierarchical"・num_levels=2 (条-番号)。
# **probe-don't-guess (P0-2 実測)**: 本通達の番号は 款括弧 (N) を持たず 条-番号 の 2 レベル
# (33-31 / 30の2-1 / 33の4-2の4)。条跨ぎ共通は所得税型の 中黒「・」+ 共 (31・32共-1) で、既存
# _LEVEL の (?:共)? 接尾 + _FIRST_LEVEL の 中点 range + _RANGE_SEP_RE の ・->_ 正規化により
# 追加コードなしで 31_32共-1 へ正規化され _directive_id_ok を通過する (P0-2 で NG0 実証)。
# ref_map は実本文の表記を実測 (P0-2 probe): 措置法(788)/措置法令(135)/措置法規則(36)・所得税法
# (53)/所得税法施行令(8)・裸 法(151)/令(14)=所得税法系 (譲渡・山林は所得税分野ゆえ裸「法」は
# 所得税法)・通則法(4)・租税特別措置法(3 full 形)。_build_law_ref_re は長い接頭辞を優先するので
# 「措置法令第N条」を「措置法」/裸「令」へ潰さない。全参照法令は data/v0.2/phase1-tax に実在
# (corpus_unregistered 空)。改正記号は所得税/資産税系の実証セット (SHOTOKU_CONFIG と同一・probe
# 実測 課資/課審/課個/課法/課所/直所/直資 は本セットの部分集合)。
SOCHI_JOTO_CONFIG = CircularConfig(
    law_name_ja="租税特別措置法関係通達（山林所得・譲渡所得関係）",
    law_abbrev="sochi-joto-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/710826/sanrin/sanjyou",
    ref_map={
        "措置法施行規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (full 形・corpus 実在)
        "措置法規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (短縮形 措置法規則)
        "措置法令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (短縮形 措置法令・corpus 実在)
        "租税特別措置法": "sochi-hou",  # 租税特別措置法 (full 形・corpus 実在)
        "措置法": "sochi-hou",  # 租税特別措置法 (本体・corpus 実在)
        "所得税法施行令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (full 形・corpus 実在)
        "所得税法": "shotoku-zei-hou",  # 所得税法 (full 形・corpus 実在)
        "通則法": "kokuzei-tsuusoku-hou",  # 国税通則法 (corpus 実在)
        "法": "shotoku-zei-hou",  # 所得税法 (裸「法」= 譲渡・山林は所得税分野ゆえ所得税法)
        "令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (裸「令」)
        "規": "shotoku-zei-hou-shikoukisoku",  # 所得税法施行規則 (裸「規」)
    },
    corpus_unregistered=frozenset(),
    amendment_markers=("課個", "直所", "直法", "直資", "課所", "課資", "課法", "課審", "官総"),
    num_levels=2,
)

# 租税特別措置法関係通達 (申告所得税関係)・FU-540。sochi-joto (山林所得・譲渡所得編) を逐語コピーし
# 申告所得税編 (801226) の値へ変更。num_style は sochi-joto と同型の "hierarchical"・num_levels=2
# (条-番号)。**probe-don't-guess (P0-2 実測)**: 番号は 款括弧 (N) を持たず 条-番号 の 2 レベル
# (10-1 / 8の5-3 / 10の4の2-1)。条跨ぎ範囲は 〜 (10の3〜15の3-1) で既存 _FIRST_LEVEL の 〜 range +
# _RANGE_SEP_RE の 〜->_ 正規化により追加コードなしで 10の3_15の3-1 へ正規化され通過する (kan_paren
# は 0・中黒 ・ は 0・共 3 件=P0-2 実測)。ref_map は本文実測 (P0-2 probe): 措置法(369)/措置法令(139)/
# 措置法規則(40)・所得税法(2)/裸 法(79)=所得税法系 (申告所得税編ゆえ裸「法」は所得税法)・裸 令(30)・
# 通則法(1)。named-law の裸「法/令」偽マッチを避けるため、本文に 第N条 で現れる別法令
# (労働基準法/雇用保険法/会社法/介護保険法/国土利用計画法(施行令)/建築基準法施行令/法人税法施行令/
# 旧所得税法) を full 形で登録し corpus_unregistered に入れて unlinked 記録する (SOUZOKU/HYOKA 同型・
# _build_law_ref_re が長い接頭辞を優先するので named-law が裸「法」へ潰れない・P0-2 で 偽リンク0 実証)。
# 措置法系/所得税法系/通則法は data/v0.2/phase1-tax に実在 (link 有効)。改正記号は所得税/資産税系の
# 実証セット (SHOTOKU/JOTO と同一・probe 実測 課個/直所/課所/課資/課法/直資 は本セットの部分集合)。
SOCHI_SHOTOKU_CONFIG = CircularConfig(
    law_name_ja="租税特別措置法関係通達（申告所得税関係）",
    law_abbrev="sochi-shotoku-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku",
    ref_map={
        "措置法施行規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (full 形・corpus 実在)
        "措置法規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (短縮形 措置法規則)
        "措置法令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (短縮形 措置法令・corpus 実在)
        "租税特別措置法": "sochi-hou",  # 租税特別措置法 (full 形・corpus 実在)
        "措置法": "sochi-hou",  # 租税特別措置法 (本体・corpus 実在)
        "所得税法施行令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (full 形・corpus 実在)
        "所得税法": "shotoku-zei-hou",  # 所得税法 (full 形・corpus 実在)
        "通則法": "kokuzei-tsuusoku-hou",  # 国税通則法 (corpus 実在)
        # named-law ガード (裸「法/令」偽マッチ回避・corpus 未収録ゆえ unlinked 記録)。
        "労働基準法": "roudou-kijun-hou",
        "雇用保険法": "koyou-hoken-hou",
        "会社法": "kaisha-hou",
        "介護保険法": "kaigo-hoken-hou",
        "国土利用計画法施行令": "kokudo-riyou-keikaku-hou-shikkourei",
        "国土利用計画法": "kokudo-riyou-keikaku-hou",
        "建築基準法施行令": "kenchiku-kijun-hou-shikkourei",
        "法人税法施行令": "houjin-zei-hou-shikkourei",  # 法人税法施行令 (本 corpus では未収録扱い)
        "旧所得税法": "kyu-shotoku-zei-hou",  # 旧所得税法 (現行条番号と不一致ゆえ unlinked)
        "法": "shotoku-zei-hou",  # 所得税法 (裸「法」= 申告所得税編ゆえ所得税法)
        "令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (裸「令」)
        "規": "shotoku-zei-hou-shikoukisoku",  # 所得税法施行規則 (裸「規」)
    },
    corpus_unregistered=frozenset(
        {
            "roudou-kijun-hou",
            "koyou-hoken-hou",
            "kaisha-hou",
            "kaigo-hoken-hou",
            "kokudo-riyou-keikaku-hou-shikkourei",
            "kokudo-riyou-keikaku-hou",
            "kenchiku-kijun-hou-shikkourei",
            "houjin-zei-hou-shikkourei",
            "kyu-shotoku-zei-hou",
        }
    ),
    amendment_markers=("課個", "直所", "直法", "直資", "課所", "課資", "課法", "課審", "官総"),
    num_levels=2,
)

# 租税特別措置法関係通達 (相続税法の特例関係)・FU-541 取込 / FU-543 で hier_var 化。sochi-joto
# (山林所得・譲渡所得編) を逐語コピーし相続税分野の値へ変更。num_style は当初 hierarchical・num_levels=2
# (条-番号) だったが、2 レベルと 3 レベル混在ゆえ FU-543 で "hier_var" (可変 {1,2}) に切替 (下記
# 「レベル混在」参照)。**probe-don't-guess (P0-2 実測)**: 番号は 款括弧 (N) を持たず 条-番号 の 2 レベル
# (69の4-1 / 70の2の2-3の2 / 69の4-24の3)。条跨ぎ範囲は 中黒「・」(69の6・69の7共-1 /
# 70の3の3・70の3の4-1) で既存 _RANGE_SEP_RE の ・->_ 正規化により追加コードなしで 69の6_69の7共-1
# へ正規化され通過する (kan_paren は 0・〜range は 0=P0-2 実測)。ref_map は本文実測 (P0-2 probe):
# 措置法(2587)/措置法令(521)/措置法規則(140)・相続税法(148)/相続税法施行令(2)/施行規則(3)・
# 所得税法(12)/施行令(1)・法人税法(8)・通則法(27)・租税特別措置法(7 full 形)・裸 法(10)=相続税法系
# (相続税特例編ゆえ裸「法」は相続税法・裸 令/規 は 0)。named-law の裸「法」偽マッチを避けるため、
# 本文に 第N条 で現れる別法令 (中小企業信用保険法/会社法/農地法/郵政民営化法/農業経営基盤強化促進法/
# 森林法(施行規則)/生産緑地法/都市計画法/医療法/郵便局株式会社法/雇用保険法/不動産登記規則/
# 会社計算規則/地方自治法/特定非営利活動促進法/借地借家法/市民農園整備促進法/文化財保護法/
# 産業競争力強化法/地方税法/独立行政法人農業者年金基金法・旧/改正前措置法系) を full 形で登録し
# corpus_unregistered に入れて unlinked 記録する (SOUZOKU/HYOKA/SHOTOKU 同型・_build_law_ref_re が
# 長い接頭辞を優先するので named-law が裸「法」へ潰れない・parse dry-run で 偽リンク0 実証)。措置法系/
# 相続税法系/所得税法系/法人税法/通則法は data/v0.2/phase1-tax に実在 (link 有効)。改正記号は
# 資産税系の実証セット (SOUZOKU と同一・probe 実測 課資/直資/課審/課評 は本セットの部分集合)。
#
# **レベル混在 (FU-541 で停止報告→FU-543 で num_style="hier_var" により捕捉・佐藤承認どおり)**:
# 本編は同一編内で 2 レベル (条-通達 69の4-27) と 3 レベル (条-項-通達 70-1-3 = 70条1項 通達3) を
# 混在させる。num_levels 固定 2 では 3 レベルを・固定 3 では 2 レベルを取りこぼす (FU-541 実測) ため、
# FU-543 で dash-level を {1,2} で可変に組む gated num_style "hier_var" を導入し、現行 18 件
# (措置法70条1項 70-1-1..70-1-14 = 14 件 + 70条3項 70-3-1..70-3-4 = 4 件) を捕捉する (corpus 963→981)。
# taxanswer 側の 措通70-1-3 も link 可になる (FU-543)。旧措置法70の3の3・70の3の4 系 7 件は「旧」始まり
# ゆえ数値開始の _FIRST_LEVEL に非マッチで除外維持 (旧法=現行条番号と不一致ゆえ除外が正しい)。
# 69の4-28 のカンマ継続裸番号 (措通69の4-27、28) の resolver 側継続解決は別 follow-up。hier_var は
# gated (sochi-sozoku 専用) ゆえ他 6 編の byte 出力は完全不変 (FU-543 で全編再パース byte 一致を実証)。
SOCHI_SOZOKU_CONFIG = CircularConfig(
    law_name_ja="租税特別措置法関係通達（相続税法の特例関係）",
    law_abbrev="sochi-sozoku-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kobetsu/sozoku/sochiho/080708",
    ref_map={
        "措置法施行規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (full 形・corpus 実在)
        "措置法規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (短縮形 措置法規則)
        "措置法令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (短縮形 措置法令・corpus 実在)
        "租税特別措置法": "sochi-hou",  # 租税特別措置法 (full 形・corpus 実在)
        "措置法": "sochi-hou",  # 租税特別措置法 (本体・corpus 実在)
        "相続税法施行令": "souzoku-zei-hou-shikkourei",  # 相続税法施行令 (full 形・corpus 実在)
        "相続税法施行規則": "souzoku-zei-hou-shikoukisoku",  # 相続税法施行規則 (full 形・corpus 実在)
        "相続税法": "souzoku-zei-hou",  # 相続税法 (full 形・corpus 実在)
        "所得税法施行令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (full 形・corpus 実在)
        "所得税法": "shotoku-zei-hou",  # 所得税法 (full 形・corpus 実在)
        "法人税法": "houjin-zei-hou",  # 法人税法 (full 形・corpus 実在)
        "通則法": "kokuzei-tsuusoku-hou",  # 国税通則法 (corpus 実在)
        # named-law ガード (裸「法/令/規」偽マッチ回避・corpus 未収録ゆえ unlinked 記録)。
        "中小企業信用保険法": "chusho-kigyo-shinyou-hoken-hou",
        "農業経営基盤強化促進法": "nogyo-keiei-kiban-kyouka-sokushin-hou",
        "独立行政法人農業者年金基金法": "dokuritsu-gyousei-houjin-nougyousha-nenkin-kikin-hou",
        "特定非営利活動促進法": "tokutei-hieiri-katsudou-sokushin-hou",
        "市民農園整備促進法": "shimin-nouen-seibi-sokushin-hou",
        "産業競争力強化法": "sangyou-kyousouryoku-kyouka-hou",
        "郵便局株式会社法": "yuubinkyoku-kabushiki-gaisha-hou",
        "郵政民営化法": "yuusei-mineika-hou",
        "会社計算規則": "kaisha-keisan-kisoku",
        "会社法": "kaisha-hou",
        "農地法": "nouchi-hou",
        "森林法施行規則": "shinrin-hou-shikoukisoku",
        "森林法": "shinrin-hou",
        "生産緑地法": "seisan-ryokuchi-hou",
        "都市計画法": "toshi-keikaku-hou",
        "医療法": "iryou-hou",
        "雇用保険法": "koyou-hoken-hou",
        "不動産登記規則": "fudousan-touki-kisoku",
        "地方自治法": "chihou-jichi-hou",
        "借地借家法": "shakuchi-shakuya-hou",
        "文化財保護法": "bunkazai-hogo-hou",
        "地方税法": "chihou-zei-hou",
        "旧措置法": "kyu-sochi-hou",  # 旧租税特別措置法 (現行条番号と不一致ゆえ unlinked)
        "特別措置法": "kyu-sochi-hou",  # 「特別措置法」単独表記 (旧法系・unlinked)
        "法": "souzoku-zei-hou",  # 相続税法 (裸「法」= 相続税特例編ゆえ相続税法)
        "令": "souzoku-zei-hou-shikkourei",  # 相続税法施行令 (裸「令」)
        "規": "souzoku-zei-hou-shikoukisoku",  # 相続税法施行規則 (裸「規」)
    },
    corpus_unregistered=frozenset(
        {
            "chusho-kigyo-shinyou-hoken-hou",
            "nogyo-keiei-kiban-kyouka-sokushin-hou",
            "dokuritsu-gyousei-houjin-nougyousha-nenkin-kikin-hou",
            "tokutei-hieiri-katsudou-sokushin-hou",
            "shimin-nouen-seibi-sokushin-hou",
            "sangyou-kyousouryoku-kyouka-hou",
            "yuubinkyoku-kabushiki-gaisha-hou",
            "yuusei-mineika-hou",
            "kaisha-keisan-kisoku",
            "kaisha-hou",
            "nouchi-hou",
            "shinrin-hou-shikoukisoku",
            "shinrin-hou",
            "seisan-ryokuchi-hou",
            "toshi-keikaku-hou",
            "iryou-hou",
            "koyou-hoken-hou",
            "fudousan-touki-kisoku",
            "chihou-jichi-hou",
            "shakuchi-shakuya-hou",
            "bunkazai-hogo-hou",
            "chihou-zei-hou",
            "kyu-sochi-hou",
        }
    ),
    amendment_markers=("課資", "直資", "課審", "課評"),
    num_style="hier_var",  # FU-543: 2 レベル (69の4-27) と 3 レベル (70-1-3) 混在ゆえ可変。
    num_levels=2,  # hier_var では不使用 (可変 {1,2}) だが既定値として明示保持。
)

# 租税特別措置法(株式等に係る譲渡所得等関係)の取扱い・FU-542。sochi-joto (山林所得・譲渡所得編) を
# 逐語コピーし株式等譲渡分野の値へ変更。num_style は sochi-joto と同型の "hierarchical"・num_levels=2
# (条-番号)。**probe-don't-guess (P0-2 実測)**: 番号は 款括弧 (N) を持たず 条-番号 の 2 レベル
# (37の10-1 / 37の11の2-1 / 37の14の2-3の2)。混在レベル (条-項-通達) はなし=hier_var 不要 (P0-2)。
# 条跨ぎ範囲は 中黒「・」(37の10・37の11共-1) で既存 _RANGE_SEP_RE の ・->_ 正規化により追加コード
# なしで 37の10_37の11共-1 へ正規化され通過する (kan_paren は 0・〜range は 0=P0-2 実測)。ref_map は
# 本文実測 (P0-2 probe): 措置法(306)/措置法令(70)/措置法規則(15)・所得税法(42)/所得税法令(58=施行令の
# NTA 短縮表記「所得税法令第N条」実確認)・法人税法(3)/法人税法施行令(1)・通則法(2)・租税特別措置法
# (2 full 形)・裸 令(1)=所得税法系 (株式譲渡は所得税分野ゆえ裸「法」は所得税法)。named-law の裸「法」
# 偽マッチを避けるため、本文に 第N条 で現れる別法令 (金融商品取引法/会社法/内閣府令) を full 形で登録し
# corpus_unregistered に入れて unlinked 記録する (SOUZOKU/SHOTOKU 同型・_build_law_ref_re が長い接頭辞を
# 優先するので named-law が裸「法」へ潰れない・parse dry-run で 偽リンク0 実証)。措置法系/所得税法系/
# 法人税法系/通則法は data/v0.2/phase1-tax に実在 (link 有効)。改正記号は所得税/資産税系の実証セット
# (SHOTOKU/JOTO と同一)。
SOCHI_KABUSHIKI_CONFIG = CircularConfig(
    law_name_ja="租税特別措置法（株式等に係る譲渡所得等関係）の取扱い",
    law_abbrev="sochi-kabushiki-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin",
    ref_map={
        "措置法施行規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (full 形・corpus 実在)
        "措置法規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (短縮形 措置法規則)
        "措置法令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (短縮形 措置法令・corpus 実在)
        "租税特別措置法": "sochi-hou",  # 租税特別措置法 (full 形・corpus 実在)
        "措置法": "sochi-hou",  # 租税特別措置法 (本体・corpus 実在)
        "所得税法施行令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (full 形・corpus 実在)
        "所得税法令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (NTA 短縮表記 所得税法令・corpus 実在)
        "所得税法": "shotoku-zei-hou",  # 所得税法 (full 形・corpus 実在)
        "法人税法施行令": "houjin-zei-hou-shikkourei",  # 法人税法施行令 (full 形・corpus 実在)
        "法人税法": "houjin-zei-hou",  # 法人税法 (full 形・corpus 実在)
        "通則法": "kokuzei-tsuusoku-hou",  # 国税通則法 (corpus 実在)
        # named-law ガード (裸「法/令」偽マッチ回避・corpus 未収録ゆえ unlinked 記録)。
        "金融商品取引法": "kinyuu-shouhin-torihiki-hou",
        "会社法": "kaisha-hou",
        "内閣府令": "naikakufu-rei",
        "法": "shotoku-zei-hou",  # 所得税法 (裸「法」= 株式譲渡は所得税分野ゆえ所得税法)
        "令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (裸「令」)
        "規": "shotoku-zei-hou-shikoukisoku",  # 所得税法施行規則 (裸「規」)
    },
    corpus_unregistered=frozenset(
        {
            "kinyuu-shouhin-torihiki-hou",
            "kaisha-hou",
            "naikakufu-rei",
        }
    ),
    amendment_markers=("課個", "直所", "直法", "直資", "課所", "課資", "課法", "課審", "官総"),
    num_levels=2,
)

# 租税特別措置法に係る所得税の取扱い(源泉所得税関係)・FU-546。sochi-kabushiki (株式等譲渡編・
# 所得税分野・hierarchical・num_levels=2) を逐語コピーし源泉所得税分野の値へ変更。
# **probe-don't-guess (P0-2 実測)**: 番号は 款括弧 (N) を持たず 条-番号 の 2 レベル
# (4の2-1 / 8の2-1 / 9の2-1 / 29の3-2 / 41の9-4 / 41の22-1)。混在レベル (条-項-通達) は
# なし=hier_var 不要。条跨ぎ共通は 中黒「・」+「共」(41の10・41の12共-1) で既存 _RANGE_SEP_RE の
# ・->_ 正規化により追加コードなしで 41の10_41の12共-1 へ通過する (kabushiki と同一・kan_paren 0)。
# ref_map は本文実測 (P0-2 probe): 措置法(117)/措置法令(69)/措置法規則(4)/措置法施行令(1)・
# 所得税法(15)/所得税法施行令(1)・裸 法/令/規=所得税法系 (源泉は所得税分野)。同法(9)/同令(29) は
# 照応参照で既存所得税編 (kabushiki/shotoku/joto=20/24/56 件) と同様に bare 法/令 経由で
# 所得税法系へ解決される既存挙動 (追加コードなし)。named-law の裸「法/令」偽マッチを避けるため、
# 本文に 第N条 で現れる別法令 (財形法/財形法令/外為法/外為令/外為省令/外国貿易法/外国為替令/
# 賃金支払確保法) を full 形で登録し corpus_unregistered に入れて unlinked 記録する (KABUSHIKI/
# SOZOKU 同型・_build_law_ref_re が長い接頭辞を優先するので named-law が裸「法」へ潰れない・
# parse dry-run で 偽リンク0 実証)。改正記号は所得税/資産税系の実証セット (KABUSHIKI と同一)。
SOCHI_GENSEN_CONFIG = CircularConfig(
    law_name_ja="租税特別措置法に係る所得税の取扱い（源泉所得税関係）",
    law_abbrev="sochi-gensen-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/880331/gensen/58",
    ref_map={
        "措置法施行規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (full 形・corpus 実在)
        "措置法規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (短縮形 措置法規則)
        "措置法令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (短縮形 措置法令・corpus 実在)
        "租税特別措置法": "sochi-hou",  # 租税特別措置法 (full 形・corpus 実在)
        "措置法": "sochi-hou",  # 租税特別措置法 (本体・corpus 実在)
        "所得税法施行令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (full 形・corpus 実在)
        "所得税法令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (NTA 短縮表記 所得税法令)
        "所得税法": "shotoku-zei-hou",  # 所得税法 (full 形・corpus 実在)
        "法人税法施行令": "houjin-zei-hou-shikkourei",  # 法人税法施行令 (full 形・corpus 実在)
        "法人税法": "houjin-zei-hou",  # 法人税法 (full 形・corpus 実在)
        "通則法": "kokuzei-tsuusoku-hou",  # 国税通則法 (corpus 実在)
        # named-law ガード (裸「法/令」偽マッチ回避・corpus 未収録ゆえ unlinked 記録・P0-2 実測)。
        "財形法施行令": "kinrousha-zaisan-keisei-sokushin-hou-shikkourei",  # 財形法令 full 形
        "財形法令": "kinrousha-zaisan-keisei-sokushin-hou-shikkourei",  # 勤労者財産形成促進法施行令
        "財形法": "kinrousha-zaisan-keisei-sokushin-hou",  # 勤労者財産形成促進法
        "外国為替令": "gaikoku-kawase-rei",  # 外国為替令 (full 形)
        "外為省令": "gaikoku-kawase-shourei",  # 外国為替に関する省令
        "外為令": "gaikoku-kawase-rei",  # 外国為替令 (短縮形 外為令)
        "外為法": "gaikoku-kawase-oyobi-gaikoku-boueki-hou",  # 外国為替及び外国貿易法
        "外国貿易法": "gaikoku-kawase-oyobi-gaikoku-boueki-hou",  # 外国為替及び外国貿易法 (末尾)
        "賃金支払確保法": "chingin-shiharai-kakuho-hou",  # 賃金の支払の確保等に関する法律
        "法": "shotoku-zei-hou",  # 所得税法 (裸「法」= 源泉所得税は所得税分野ゆえ所得税法)
        "令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (裸「令」)
        "規": "shotoku-zei-hou-shikoukisoku",  # 所得税法施行規則 (裸「規」)
    },
    corpus_unregistered=frozenset(
        {
            "kinrousha-zaisan-keisei-sokushin-hou-shikkourei",
            "kinrousha-zaisan-keisei-sokushin-hou",
            "gaikoku-kawase-rei",
            "gaikoku-kawase-shourei",
            "gaikoku-kawase-oyobi-gaikoku-boueki-hou",
            "chingin-shiharai-kakuho-hou",
        }
    ),
    amendment_markers=("課個", "直所", "直法", "直資", "課所", "課資", "課法", "課審", "官総"),
    num_levels=2,
)

# 租税特別措置法関係通達 (第40条 取扱い)・FU-547。800423 (直資2-181・昭55.4.23・措法40条1項後段の
# 譲渡所得等の非課税取扱い)。所得税(譲渡所得)分野の個別通達。num_style は HYOKA と同じ "flat_branch"
# (財産評価型・単発通し番号 + の枝番)。**probe-don't-guess (PS-3 実測)**: 番号は 01.htm=目次が列挙する
# flat 通し 1..52 + の枝番 8 (19の2/20の2/20の3/23の2/23の3/23の4/24の2/27の2) = 60。「40条」は
# directive 番号でなく h2 セクション見出し〔措置法第40条第N項関係〕にのみ現れる (hierarchical ではない)。
# 本文は 02..23.htm の content ページで <h2>(title) + <p><strong>N</strong>本文 の既存 flat_branch が
# 処理する markup。strong-gate が (注) 平文番号 "1"/"2" を排除するので num_levels=1 の膨張を起こさない
# (60 unique・dup 0・_directive_id_ok 全通過=PS 実測)。附則 22.htm は <li> 構造ゆえ <p><strong> 抽出に
# 非該当で自然に 0 件 (dup "1" 自動回避)。ref_map は全 content 本文実測 (PS-6 probe): 措置法(99)/措令
# (71・短縮形)/措置法施行令/措置法施行規則/措規・所得税法(3)/裸 法=所得税分野・法人税法(3)/法人税法
# 施行令(2)・通則法。同法(29)/同令 は照応参照で既存所得税編と同様に bare 法/令 経由で所得税法系へ解決
# される既存挙動 (追加コードなし)。named-law の裸「法」偽マッチを避けるため、本文に 第N条 で現れる別法令
# (一般社団・財団法人法/公益認定法/整備法/社会福祉法/医療法(施行規則)/更生保護事業法/博物館法/学校教育
# 法/児童福祉法/介護保険法/特定非営利活動促進法) を full 形で登録し corpus_unregistered に入れて unlinked
# 記録する (SOZOKU/KABUSHIKI/GENSEN 同型・_build_law_ref_re が長い接頭辞を優先するので named-law が裸
# 「法」へ潰れない・parse dry-run で 誤リンク0 実証)。措置法系/所得税法系/法人税法系/通則法は
# data/v0.2/phase1-tax に実在 (link 有効)。改正記号は所得税/資産税系の実証セット (GENSEN と同一)。
SOCHI_40JOU_CONFIG = CircularConfig(
    law_name_ja="租税特別措置法関係通達（第40条 取扱い）",
    law_abbrev="sochi-40jou-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/800423",
    ref_map={
        "措置法施行規則": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (full 形・corpus 実在)
        "措置法施行令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (full 形・corpus 実在)
        "租税特別措置法施行令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (最長 full 形)
        "租税特別措置法": "sochi-hou",  # 租税特別措置法 (full 形・corpus 実在)
        "措置法令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (短縮形 措置法令)
        "措置法": "sochi-hou",  # 租税特別措置法 (本体・corpus 実在)
        "措令": "sochi-hou-shikkourei",  # 租税特別措置法施行令 (NTA 短縮表記 措令・PS-6: 71 件)
        "措規": "sochi-hou-shikoukisoku",  # 租税特別措置法施行規則 (短縮形 措規)
        "所得税法施行令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (full 形・corpus 実在)
        "所得税法": "shotoku-zei-hou",  # 所得税法 (full 形・corpus 実在)
        "法人税法施行令": "houjin-zei-hou-shikkourei",  # 法人税法施行令 (full 形・corpus 実在)
        "法人税法": "houjin-zei-hou",  # 法人税法 (full 形・corpus 実在)
        "通則法": "kokuzei-tsuusoku-hou",  # 国税通則法 (corpus 実在)
        # named-law ガード (裸「法」偽マッチ回避・corpus 未収録ゆえ unlinked 記録・PS-6 実測)。
        "一般社団・財団法人法": "ippan-shadan-zaidan-houjin-hou",  # 一般社団法人及び一般財団法人に関する法律 (略称)
        "公益認定法": "koueki-nintei-hou",  # 公益社団法人及び公益財団法人の認定等に関する法律 (略称)
        "整備法": "seibi-hou",  # 一般社団・財団法人法等の施行に伴う関係法律の整備等に関する法律 (略称)
        "社会福祉法": "shakai-fukushi-hou",
        "医療法施行規則": "iryou-hou-shikoukisoku",  # 医療法施行規則 (施行規則ゆえ裸接頭辞に非該当だが full 登録)
        "医療法": "iryou-hou",
        "更生保護事業法": "kousei-hogo-jigyou-hou",
        "博物館法": "hakubutsukan-hou",
        "学校教育法": "gakkou-kyouiku-hou",
        "児童福祉法": "jidou-fukushi-hou",
        "介護保険法": "kaigo-hoken-hou",
        "特定非営利活動促進法": "tokutei-hieiri-katsudou-sokushin-hou",
        "法": "shotoku-zei-hou",  # 所得税法 (裸「法」= 40条は譲渡所得ゆえ所得税分野)
        "令": "shotoku-zei-hou-shikkourei",  # 所得税法施行令 (裸「令」)
        "規": "shotoku-zei-hou-shikoukisoku",  # 所得税法施行規則 (裸「規」)
    },
    corpus_unregistered=frozenset(
        {
            "ippan-shadan-zaidan-houjin-hou",
            "koueki-nintei-hou",
            "seibi-hou",
            "shakai-fukushi-hou",
            "iryou-hou-shikoukisoku",
            "iryou-hou",
            "kousei-hogo-jigyou-hou",
            "hakubutsukan-hou",
            "gakkou-kyouiku-hou",
            "jidou-fukushi-hou",
            "kaigo-hoken-hou",
            "tokutei-hieiri-katsudou-sokushin-hou",
        }
    ),
    amendment_markers=("課個", "直所", "直法", "直資", "課所", "課資", "課法", "課審", "官総"),
    num_style="flat_branch",
)

# --circular セレクタの登録簿。
CIRCULAR_CONFIGS: dict[str, CircularConfig] = {
    "hojin": HOJIN_CONFIG,
    "shouhi": SHOUHI_CONFIG,
    "shotoku": SHOTOKU_CONFIG,
    "souzoku": SOUZOKU_CONFIG,
    "hyoka": HYOKA_CONFIG,
    "sochi-hojin": SOCHI_HOJIN_CONFIG,
    "sochi-joto": SOCHI_JOTO_CONFIG,
    "sochi-shotoku": SOCHI_SHOTOKU_CONFIG,
    "sochi-sozoku": SOCHI_SOZOKU_CONFIG,
    "sochi-kabushiki": SOCHI_KABUSHIKI_CONFIG,
    "sochi-gensen": SOCHI_GENSEN_CONFIG,  # FU-546
    "sochi-40jou": SOCHI_40JOU_CONFIG,  # FU-547
}


# 出力 JSONL の chunk-level キー順マスタ (出力保持の正本・FU-514)。
# DirectiveChunk.model_dump() (意味フィールド) + 配管フィールドをマージした後、
# この順で再構築して現 dict の interleaved キー順をバイト再現する。
# naive な {**semantic, **pipeline} は配管キーが末尾集中で順序が崩れる (Bug1)。
DIRECTIVE_KEY_ORDER = [
    "id",
    "directive_id",
    "law_name_ja",
    "law_abbrev",
    "directive_number",
    "title",
    "text",
    "amendment_note",
    "related_articles",
    "source_url",
    "license",
    "segment_type",
    "article_id",
    "law_name_ja_display",
]

# ---------------------------------------------------------------------------
# Text normalization helpers (R7, R10)
# ---------------------------------------------------------------------------

# All horizontal bar variants -> ASCII hyphen.
# Wave dashes (U+301C / U+FF5E / U+007E) are intentionally NOT normalized here.
# A wave dash in body text is kept as-is (no body mutation), and turning the range
# mark of an article-range number into "-" would collide with the level separator
# "-" and mis-level it. Wave dashes inside a number are normalized to "_" after the
# number is matched, via _RANGE_SEP_RE (same approach as the middle dot).
_BAR_RE = re.compile(r"[\-\uff0d\u2010\u30fc\u2212\u2014\u2015]")
# Non-breaking space / full-width space -> regular space
_NBSP_RE = re.compile("[\u00a0\u3000 ]")
# Article-range separators (middle dot U+30FB / wave dash U+301C, U+FF5E, U+007E).
# Kept inside the level while the number is matched, then normalized to '_' before
# the record is built (74<dot>75-1 -> 74_75-1, 23<wave>35-kyo-1 -> 23_35-kyo-1).
_RANGE_SEP_RE = re.compile(r"[\u30fb\u301c\uff5e~]")


def _normalize_bars(s: str) -> str:
    """Replace all horizontal bar variants with ASCII hyphen (R7)."""
    return _BAR_RE.sub("-", s)


def _normalize_whitespace(s: str) -> str:
    """Replace non-breaking and full-width spaces with ASCII space (R10)."""
    return _NBSP_RE.sub(" ", s)


def _normalize_text(s: str) -> str:
    return _normalize_whitespace(_normalize_bars(s))


# ---------------------------------------------------------------------------
# Related article extraction (R2, R8, R12)
# ---------------------------------------------------------------------------

# Pattern: 法/令/規/措法 + 第 + article + optional branches + optional paragraph
# R8: relative refs (同条/同法/同項) excluded by requiring explicit prefix
# R12: multi-level no: (?:の\d+)* (not just ?)
_LAW_REF_RE = re.compile(
    r"(法|令|規|措法)第(\d+)条(?:の(\d+))*(?:第(\d+)項)?",
)
# The above only captures last の-branch. 実際の抽出は config.ref_map のキーから
# 組む _build_law_ref_re を使う (下記)。ハードコード (法|令|規|措法) では相続税通達の
# 「措置法第N条」が内側の「法」に誤マッチして相続税法へ偽リンクするため、接頭辞集合を
# config ごとに切り替える。既存 hojin/shohi/shotoku はキー集合が従来と同値 (または該当
# 接頭辞が本文に不在) ゆえ byte 不変 (byte 回帰テストで実証)。


@cache
def _build_law_ref_re(prefixes: tuple[str, ...]) -> re.Pattern[str]:
    """接頭辞集合から参照抽出正規表現を組む (長いキー優先で 措置法>法 を保証)。

    Why: 参照接頭辞は通達ごとに異なる (相続税は措置法/通則法/所得税法/地価税法を完全形で
    書く)。長い順の alternation にすることで「措置法第N条」を「法第N条」へ潰さず正しく
    捕捉する。tuple 引数で lru_cache 可能 (config ごとに 1 回コンパイル)。
    """
    alt = "|".join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True))
    return re.compile(rf"({alt})第(\d+)条((?:の\d+)*)(?:第(\d+)項)?")


def _extract_related_articles(text: str, config: CircularConfig) -> list[dict]:
    """Extract law article references from text (R2, R8, R12).

    Returns list of dicts with keys: raw, law_abbrev, article_number, article_id.
    Unresolved references (corpus未収録) are included with article_id=None + warn.
    接頭辞 -> law_abbrev の対応と corpus 未登録判定は config に従う (通達ごとに切替)。
    """
    results: list[dict] = []
    seen_raw: set[str] = set()

    ref_re = _build_law_ref_re(tuple(config.ref_map))
    for m in ref_re.finditer(text):
        prefix = m.group(1)  # config.ref_map のキー (法/令/規/... 通達依存)
        base_num = m.group(2)  # e.g. "34"
        no_suffix = m.group(3) or ""  # e.g. "の2の2" or ""
        # para = m.group(4)  -- not used for article_id

        raw = m.group(0)
        if raw in seen_raw:
            continue
        seen_raw.add(raw)

        law_abbrev = config.ref_map.get(prefix)
        if law_abbrev is None:
            # Unknown prefix: skip silently (R8: only explicit prefixes)
            continue

        # Build article_number: base + each の-branch as -N
        # "の2の2" -> ["2", "2"]
        branches = re.findall(r"\d+", no_suffix)
        article_number = base_num
        if branches:
            article_number = base_num + "-" + "-".join(branches)

        if law_abbrev in config.corpus_unregistered:
            warnings.warn(
                f"WARN: {raw!r} -> {law_abbrev} is not in corpus (corpus未収録). "
                "Keeping raw reference without article_id link.",
                stacklevel=2,
            )
            results.append(
                {
                    # disjoint Union の Unlinked 形に合わせ article_id キーは持たせない
                    # (FU-514: DirectiveUnlinkedArticleRef は extra="forbid")。
                    # 現コーパスは unlinked 0 件なので出力 byte は不変。
                    "raw": raw,
                    "law_abbrev": law_abbrev,
                    "article_number": article_number,
                    "unlinked_reason": "corpus_unregistered",
                }
            )
        else:
            article_id = f"{law_abbrev}-art-{article_number}"
            results.append(
                {
                    "raw": raw,
                    "law_abbrev": law_abbrev,
                    "article_number": article_number,
                    "article_id": article_id,
                }
            )

    return results


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

# Directive number levels (章-節-項 = 3 / 条-番号 = 2)、各レベルは「の」枝番を持ち得る。
# 法人税基本通達の「章の枝番」(第12章の2 = 12の2-1-1) では **章レベル**に「の」が付く。
# 消費税通達・法人税 9-2 は項レベルにしか「の」が付かない (9-2-12の2) ため、レベル毎に
# (?:の\d+)* を許す本パターンは旧パターンの上位互換 (既存コーパスの番号・キャプチャは
# Full-width digits may appear; normalize before matching.
# 所得税通達の共接尾 (36・37共-1 など) に対応: 末尾に (?:共)? を許す。
# HOJIN/SHOUHI は「共」を持たないため、本上位互換は非「共」入力で従来と同一 (byte 不変)。
_LEVEL = r"\d+(?:の\d+)*(?:共)?"
# 先頭レベルは条範囲 (所得税 74・75-1) を持ち得る。中点「・」(U+30FB) は全本文を変えない
# よう **番号検出時だけ** 許し、record 生成前に取込側で "_" へ正規化する。HOJIN/SHOUHI の
# 番号に「・」は無いため、本上位互換は非「・」入力で従来と同一キャプチャ (byte 回帰で実証)。
_FIRST_LEVEL = rf"{_LEVEL}(?:[・〜～~]{_LEVEL})*"

# kan_paren 専用: 条と項の間に入る款マーカー (N)/（N） または条跨ぎ共通マーカー （共）。
# 半角/全角の丸括弧、内部は半角/全角数字か「共」。任意 (款のない条-項もあるため) で、
# _directive_levels_re が款の後に必須の項ダッシュを続けて裸の号番号を通達開始と誤認しない。
_KAN_PAREN_RE = r"(?:[（(](?:\d+|共)[）)])?"


def _fold_kan_paren(num: str) -> str:
    """措置法通達番号を数値主体の directive_id 末尾へ畳み込む (款->-N・（共）->共・の 保持)。

    Why: 措通の番号は 条 と 項 の間に款マーカー (N)/（N） を持ち (62の3（1）－1)、条跨ぎ通達は
    共通マーカー （共） を持つ (42の5～48（共）－1)。hierarchical/flat_branch は款を表現しない。
    款は末尾の数値レベルへ (62の3-1-1)、（共） は範囲末尾レベルへ (48（共）->48共) 畳み込み、
    条・号の枝番「の」は既存規約どおり保持する (例 hojin 9-2-12の2)。全角ハイフン・全角数字は
    正規化する。未知の丸括弧内容 (数字でも「共」でもない) はそのまま残し、_directive_id_ok で
    fail-loud させる (buggy な既定変換で黙って壊さない)。呼び出し時点で ・/〜/～ は _RANGE_SEP_RE
    により既に "_" へ潰れている前提。
    """
    s = num.replace("　", "").strip()
    s = re.sub(r"[（(]\s*共\s*[）)]", "共", s)  # （共）-> 共 (範囲末尾レベルへ)
    s = re.sub(
        r"[（(]\s*(\d+)\s*[）)]",
        lambda m: "-" + unicodedata.normalize("NFKC", m.group(1)),
        s,
    )  # 款 (N)/（N）-> -N (半角化)
    s = s.replace("－", "-")  # 全角ハイフン -> ASCII
    s = re.sub(
        r"[0-9０-９]+", lambda m: unicodedata.normalize("NFKC", m.group(0)), s
    )  # 全角数字 -> 半角
    return s


def _normalize_directive_num(raw: str, config: CircularConfig) -> str:
    """キャプチャ直後の番号文字列を directive_id 末尾形へ正規化する (num_style 駆動)。

    Why: 全 num_style 共通で条範囲区切り (・/〜/～) を "_" に潰す (既存挙動)。kan_paren は
    さらに _fold_kan_paren で款・（共）を畳み込む。hierarchical/flat_branch では _RANGE_SEP_RE
    のみ適用され従来と同一文字列を返す (byte 回帰で実証)。全角アラビア数字は NTA ソースの表記を
    verbatim 保存する既存規約 (souzoku-kihon/sochi-shotoku の locked baseline は全角番号を含む・
    FU-541 で確認) に従い hierarchical 経路では正規化しない (locked baseline を byte 不変に保つ)。
    """
    num = _RANGE_SEP_RE.sub("_", raw)
    if config.num_style == "kan_paren":
        num = _fold_kan_paren(num)
    return num


def _directive_levels_re(config: CircularConfig) -> str:
    """番号パターンを num_style で組む。

    hierarchical: '{first}-{level}-...' を config.num_levels 個のレベルで (先頭は条範囲可)。
    flat_branch:  '{first}(?:-{level})?' = 単発番号 + 任意の単一ダッシュ枝番 (財産評価型・
                  貪欲で "4-2" を丸ごと、"4" を単独で取る)。num_levels は不使用。
    kan_paren:    '{first}{款?}[-－]{level}' = 条 + 任意の款 (N)/（N）/（共） + **必須**の項
                  ダッシュ (措置法通達型)。項を必須にすることで本文中の裸号番号 (1/2/3) を
                  通達開始と誤検出しない。ダッシュは全角/半角両対応。num_levels は不使用。
    hier_var:     '{first}(?:-{level}){1,2}' = 条 + 1〜2 個の項ダッシュ (FU-543・sochi-sozoku)。
                  貪欲で 3 レベル (70-1-3) を丸ごと、無ければ 2 レベル (69の4-27) を取る。行頭/
                  末尾アンカー (_build_*_re) 下では 2 レベル既存分は従来と同一列を返す (下限 1 で
                  一致・後続に "-N" が無いため 2 個目は非発火)。num_levels は不使用。
    hierarchical 経路は従来と完全に同一文字列を返す (byte 回帰で実証)。
    """
    if config.num_style == "flat_branch":
        return rf"{_FIRST_LEVEL}(?:-{_LEVEL})?"
    if config.num_style == "kan_paren":
        return rf"{_FIRST_LEVEL}{_KAN_PAREN_RE}[-－]{_LEVEL}"
    if config.num_style == "hier_var":
        return rf"{_FIRST_LEVEL}(?:-{_LEVEL}){{1,2}}"
    return "-".join([_FIRST_LEVEL] + [_LEVEL] * (config.num_levels - 1))


def _build_directive_num_re(config: CircularConfig) -> re.Pattern:
    """CASE A: 番号全体が <strong> 内 (法人税通達・一部の消費税通達)。末尾アンカー。"""
    return re.compile(rf"^({_directive_levels_re(config)})\s*$")


def _build_leading_directive_re(config: CircularConfig) -> re.Pattern:
    """CASE B/C: 段落テキスト先頭の番号 (split-strong / strong 無し平文)。

    NTA の消費税・所得税通達では番号が <strong>1</strong>－3－2 ... や <strong>204</strong>-1
    のように分割され、strong だけでは番号全体にならない。CASE A が外れたときのみ本パターンで
    段落先頭から番号を拾う。
    """
    return re.compile(rf"^({_directive_levels_re(config)})\s")


# 多章モードで cache root 直下から「章ディレクトリ」だけを拾うフィルタ。
# 章は 2 桁ゼロ詰め (01..21)。法人税基本通達は章の枝番ディレクトリ (12_2 = 第12章の2 ..
# 13_2) と 20a (第20章) を持つため、`_\d+` / `a` 接尾辞も章として許す。前文 (zenbun/ ・
# shohi/02.htm = root 直下の .htm で parts[0] が非 2桁) や 附則 (fusoku/)・旧版アーカイブ
# (20230930/ = 8 桁) は fullmatch で機械的に除外する (shohi の選択集合は不変 = byte 回帰で実証)。
# FU-539: 措置法通達(山林所得・譲渡所得関係)は章ディレクトリを措置法条番号で命名する
# (soti30..soti41)。additive に `soti\d+` を許す (既存 6 通達の cache に soti* ディレクトリは
# 皆無ゆえ選択集合は不変 = sochi-hojin 再パース byte 回帰で実証)。fusoku (附則) は他通達と同じく
# 非マッチで自然除外される (taxanswer が引くのは本則 soti 章の通達で附則は経過規定)。
# FU-542: 措置法通達(株式等譲渡・020624)は cache 直下に 4 桁の tree code dir (1273) を持ち、その下に
# 条 dir (37_10 等) が入れ子になる。additive に `\d{4}` を許す (既存 9 通達の cache に 4 桁 top-dir は
# 皆無・8 桁アーカイブ (20230930) は fullmatch で除外維持ゆえ選択集合は不変 = 既存編 再パース byte 回帰
# で実証)。**接尾 `_\d` は付けない**: 兄弟 dir `1273_1` は「平成14年11月27日付改正以前のもの」= 旧版
# アーカイブで現行 1273 と同一 directive_number を異本文で重複させる (fail-loud 検知・P0-1)。旧版は
# `\d{4}` (接尾なし fullmatch) で機械除外する (現行 1273 のみ収録)。tree code 下の zenbun (前文) は
# 0 directive で自然除外される。
_CHAPTER_DIR_RE = re.compile(r"\d{2}(?:_\d+|a)?|soti\d+|\d{4}")

# directive_id の命名規則 (ユニークさとは別の形式ゲート・査読項11)。
# {law_abbrev}-{レベル}-... の形だけを許し (各レベルに「の」枝番可、先頭は条範囲 "_" 連結可)、
# 章跨ぎ取込で番号抽出が崩れた record (レベル欠落・全角混入等) を fail-loud で止める。
# 検証対象は正規化済 id ゆえ条範囲は "・" でなく "_" (74_75-1)。
_ID_FIRST_LEVEL = rf"{_LEVEL}(?:_{_LEVEL})*"

# flat_branch 専用: 構造境界マーカー (章/節/款/目 divider ・ 附表/別表/付表/別紙 見出し)。
# 財産評価通達は単発通し番号ゆえ、節・章の見出しや附表見出しが通達間の平文段落として現れ、
# そのままだと直前通達の本文へ吸い込まれる (例: "第5節 信託受益権" が 201 削除本文に混入、
# "付表10 削除" が 43-4 本文に混入)。この境界に達したら現通達を確定し、次の通達開始まで本文
# 蓄積を打ち切る。第N見出しは「第<番号><単位>」の直後が空白/全角空白のもののみに限定し、
# 本文中の "第6章≪…≫" のような文中参照 (助詞や記号が続く) を誤検出しない。h1 見出しは元々
# スキップされるため対象は <p> の平文見出しのみ。
_FLAT_SECTION_BOUNDARY_RE = re.compile(
    r"^(?:第[0-9０-９〇一二三四五六七八九十百千]+[編章節款目][\s　]"
    r"|(?:附表|別表|付表|別紙)[0-9０-９\s　])"
)


def _build_directive_id_tail_re(config: CircularConfig) -> re.Pattern:
    """directive_id 末尾 (law_abbrev 除去後) の形式パターンを num_style で組む。

    hierarchical: num_levels 個のレベルを "-" 連結 (従来と完全同一)。
    flat_branch:  '{first}(?:-{level})?' = 単発番号 + 任意枝番 ("100" / "4-2")。
    kan_paren:    '{first}(?:-{level}){1,2}' = 条 + (款? + 項) の 2〜3 dash-level (款有無で
                  可変)。畳み込み後は数値主体 (「の」は _LEVEL が許容) ゆえ num_levels 固定では
                  なく可変個で検証する。
    hier_var:     '{first}(?:-{level}){1,2}' = 条 + 1〜2 dash-level (FU-543・sochi-sozoku)。
                  2 レベル (69の4-27) と 3 レベル (70-1-3) を同一ゲートで受理 (kan_paren の tail
                  と同形・款 fold なしで数値主体)。旧法 (「旧」始まり) は _ID_FIRST_LEVEL に非マッチ。
    """
    if config.num_style == "flat_branch":
        return re.compile(rf"{_ID_FIRST_LEVEL}(?:-{_LEVEL})?")
    if config.num_style in ("kan_paren", "hier_var"):
        return re.compile(rf"{_ID_FIRST_LEVEL}(?:-{_LEVEL}){{1,2}}")
    return re.compile("-".join([_ID_FIRST_LEVEL] + [_LEVEL] * (config.num_levels - 1)))


def _directive_id_ok(directive_id: str, config: CircularConfig) -> bool:
    """True if directive_id == '{law_abbrev}-{レベル-...(のN)*}' (査読項11・num_levels 駆動)."""
    prefix = f"{config.law_abbrev}-"
    if not directive_id.startswith(prefix):
        return False
    return _build_directive_id_tail_re(config).fullmatch(directive_id[len(prefix) :]) is not None


def _detect_charset(raw: bytes) -> str:
    """Detect encoding from HTML meta tag or default to cp932 (R1)."""
    # Try HTTP-equiv meta
    m = re.search(rb"charset=([^\s\"'>;]+)", raw[:2000], re.I)
    if m:
        enc = m.group(1).decode("ascii", errors="replace").strip().lower()
        # Normalize shift_jis variants to cp932
        if enc in ("shift_jis", "shift-jis", "sjis", "x-sjis", "shift_jis-2004"):
            return "cp932"
        return enc
    return "cp932"


def _build_directive_record(
    *,
    num: str,
    title: str,
    body: str,
    amendment_note: str,
    related: list[dict],
    source_url: str,
    config: CircularConfig,
) -> dict:
    """Validate via DirectiveChunk (Pydantic IR) and reconstruct the 14-key record.

    Why: routing through DirectiveChunk catches malformed refs at parse time and
    keeps the disjoint linked/unlinked Union honest, while the explicit
    DIRECTIVE_KEY_ORDER reconstruction reproduces the historical interleaved key
    order byte-for-byte. Pipeline fields (id / law_name_ja / law_name_ja_display
    / segment_type / article_id) are merged post-dump (not part of the semantic
    IR), and article_id is injected as None explicitly so the key is always
    present (Bug29: never silently dropped via .get()).
    """
    from juricode_shared.ir import DirectiveChunk

    directive_id = f"{config.law_abbrev}-{num}"
    chunk = DirectiveChunk(
        directive_id=directive_id,
        directive_number=num,
        law_abbrev=config.law_abbrev,
        title=title,
        text=body,
        amendment_note=amendment_note,
        related_articles=related,  # dict -> disjoint Union が linked/unlinked を判別
        source_url=source_url,
        license=config.license,
    )
    semantic = chunk.model_dump(mode="json")

    # 配管フィールドを明示注入 (retrieve.py 互換)。article_id は None でも必ず入れる。
    merged = {
        **semantic,
        "id": directive_id,
        "law_name_ja": config.law_name_ja,
        "law_name_ja_display": f"{config.law_name_ja} {num}",
        "segment_type": "tsutatsu",
        "article_id": None,
    }

    # キー順再構築: 全 14 キーが存在する前提 (欠落は KeyError で fail loud)。
    return {k: merged[k] for k in DIRECTIVE_KEY_ORDER}


# 段落本文として取り込む際に「中に入れ子になったブロック要素」を除外するためのタグ集合。
# NTA の一部ページ (例 09/09_03.htm) は別表 <table> の周辺で <p> が閉じられず、後続の
# 通達 <p>/<h2>/<table> が body 段落の **子** として吸い込まれる (malformed HTML)。これらの
# 入れ子ブロックは find_all で個別に巡回され各々処理されるため、親段落のテキストからは
# 除外して二重計上を防ぐ。整形済みページ (入れ子なし) では fast-path で get_text と完全一致。
_NESTED_BLOCK_TAGS = ("h1", "h2", "p", "table")


def _text_excluding_nested_blocks(tag, separator: str = "") -> str:
    """tag のテキストを、入れ子のブロック要素 (_NESTED_BLOCK_TAGS) を除いて取得する。

    Why: malformed HTML で親 <p> が後続ブロックを吸い込んだとき、親段落の get_text は
    子の通達本文まで含んでしまい二重計上になる。入れ子ブロックを除いた「その段落自身の
    テキスト」だけを返すことで正しい帰属にする。**入れ子が無い整形済み段落では
    get_text(separator) と同一文字列を返す** (= 既存コーパス byte 不変)。
    """
    if tag.find(_NESTED_BLOCK_TAGS) is None:
        return tag.get_text(separator=separator)
    clone = copy.copy(tag)  # bs4 は recursive copy。clone を破壊しても原木は不変。
    for el in clone.find_all(_NESTED_BLOCK_TAGS):
        el.decompose()
    return clone.get_text(separator=separator)


def _extract_directive_items(
    soup: BeautifulSoup, source_url: str, config: CircularConfig
) -> list[dict]:
    """Parse BeautifulSoup of a single htm page -> list of directive chunk dicts.

    One dict per directive item (e.g. 9-2-9, 9-2-10, ...).
    R4: handles multiple items per page.
    """
    items: list[dict] = []
    # current_title = 直近に出現した見出し (h2) = 次に始まる項の見出し (pending)。
    # current_item_title = いま蓄積中の項に確定済みの見出し。
    # 番号検出時に current_title を current_item_title へ束縛することで「項に対し
    # 直前の見出し」を正しく割当てる (旧実装は flush 時の current_title を使い、既に
    # 次項の見出しへ進んでいたため +1 ズレていた)。
    current_title: str | None = None
    current_item_title: str | None = None
    current_num: str | None = None
    current_body_parts: list[str] = []
    current_amendment: str | None = None

    # 番号検出正規表現は config.num_levels 駆動 (3=章節項 / 2=条番号)。先頭レベルは条範囲
    # (74・75) を許す。HOJIN/SHOUHI は非「・」入力ゆえ従来パターンと同一キャプチャ (byte 不変)。
    case_a_re = _build_directive_num_re(config)
    case_b_re = _build_leading_directive_re(config)

    def _flush(num: str | None, title: str | None, parts: list[str], amend: str | None) -> None:
        if num is None:
            return
        body = "\n".join(parts).strip()
        # Extract amendment note from end of body if not already found.
        # marker は通達ごと (課法[+直法]/課消)。複数記号を alternation で 1 本の正規表現に
        # 束ねる。hojin に "直法" を足しても 9-2 sentinel は末尾 直法 ゼロ -> byte 不変。
        amendment_note = amend
        if amendment_note is None:
            marker_alt = "|".join(re.escape(m) for m in config.amendment_markers)
            amend_re = rf"（[^）]*(?:{marker_alt})[^）]*）\s*$"
            amend_m = re.search(amend_re, body)
            if amend_m:
                amendment_note = amend_m.group(0)
                body = body[: amend_m.start()].rstrip()

        # Normalize bars/whitespace in body
        body = _normalize_text(body)
        related = _extract_related_articles(body, config)

        items.append(
            _build_directive_record(
                num=num,
                title=title or "",
                body=body,
                amendment_note=amendment_note or "",
                related=related,
                source_url=source_url,
                config=config,
            )
        )

    body_area = soup.find(id="bodyArea") or soup.find(id="contents")
    if body_area is None:
        warnings.warn(f"WARN: bodyArea not found in {source_url}", stacklevel=2)
        return items

    for tag in body_area.find_all(["h1", "h2", "p", "table"]):
        tag_name = tag.name

        if tag_name == "table":
            # 別表/表: プレーンテキスト本文として現在の項に取り込む (Bug55・別表保持ゴール)。
            # 完全構造化はスコープ外だが、税率表等を retrieval から落とさない (本文非空)。
            # 整形済みページに <table> は無く (shohi/9-2/ch1-2 = 0 件)、出力 byte は不変。
            if current_num is not None:
                table_text = _normalize_text(tag.get_text(separator="\n")).strip()
                if table_text:
                    current_body_parts.append(table_text)
            continue

        if tag_name in ("h1", "h2"):
            # h2 is the title before a directive item. e.g. "（債務の免除による利益...）"
            # h1 is the section header - skip
            if tag_name == "h2":
                current_title = tag.get_text(strip=True)
            continue

        # flat_branch (財産評価基本通達): 単発通し番号 + 任意の枝番。番号が <strong> 内に
        # ある段落のみ通達開始とみなし、(注) 注記や別表の平文 "1 …" は本文として蓄積する
        # (単発番号は番号形だけでは注記・別表行と区別できないため strong を必須ゲートにする。
        # 実 HTML で strong 付き番号 313 件が全 unique な真通達・平文番号 40 件は全て注記/別表
        # と確認済)。split-strong <strong>4</strong><strong>－2</strong> のため番号値は strong
        # 単独でなく段落先頭の完全一致 (case_b_re) から取り "4" に切り詰めない。always-continue
        # ゆえ以降の hierarchical 経路には落ちない (既存コーパスは num_style 既定で影響なし)。
        if config.num_style == "flat_branch":
            fb_strong = tag.find("strong")
            fb_plain = _normalize_text(_text_excluding_nested_blocks(tag)).strip()
            fb_stext = (
                _normalize_text(fb_strong.get_text()).strip() if fb_strong is not None else ""
            )
            fb_lead = (
                case_b_re.match(fb_plain)
                if (fb_strong is not None and fb_stext and fb_plain.startswith(fb_stext))
                else None
            )
            if fb_lead:
                _flush(current_num, current_item_title, current_body_parts, current_amendment)
                current_num = _RANGE_SEP_RE.sub("_", fb_lead.group(1))
                current_item_title = current_title
                current_title = None  # consume-once (削除通達はタイトルなし)
                current_body_parts = []
                current_amendment = None
                remaining = fb_plain[fb_lead.end() :].strip()
                if remaining:
                    current_body_parts.append(remaining)
            elif _FLAT_SECTION_BOUNDARY_RE.match(fb_plain):
                # 構造境界 (章/節 divider ・ 附表/別表/付表 見出し): 現通達を確定し、以降の
                # 付随構造ブロックは次の通達開始まで本文に取り込まない (吸い込み防止)。
                _flush(current_num, current_item_title, current_body_parts, current_amendment)
                current_num = None
                current_item_title = None
                current_body_parts = []
                current_amendment = None
            elif current_num is not None:
                # (注) 注記 / 号 (1)(2) / 通常本文は現在の通達本文へ蓄積する。
                raw_text = _normalize_text(_text_excluding_nested_blocks(tag, "\n")).strip()
                if raw_text:
                    current_body_parts.append(raw_text)
            continue

        # p tags: check if it starts a new directive item
        strong = tag.find("strong")
        if strong:
            raw_num_text = _normalize_text(strong.get_text())
            num_match = case_a_re.match(raw_num_text.strip())
            # ガード: 番号が段落の **先頭** にあるときのみ項開始とみなす。malformed HTML で
            # body 段落が後続通達 <p> を吸い込むと tag.find("strong") が入れ子の番号
            # (例 9-3-6) を拾い、本文段落を誤って項開始扱いして見出し脱落+本文混線を招く
            # (例 09/09_03.htm)。段落テキストが番号で始まらなければ入れ子 strong として却下。
            # 整形済みの真の項段落は番号が先頭にあるため no-op (既存コーパス byte 不変)。
            if num_match and _normalize_text(tag.get_text()).strip().startswith(num_match.group(1)):
                # CASE A: 番号全体が <strong> 内 (法人税通達・一部の消費税通達)。
                # Flush previous item (確定済み見出し current_item_title を使う)。
                _flush(current_num, current_item_title, current_body_parts, current_amendment)
                # Start new item: この番号の直前見出しを確定束縛 (title-lag 修正)。
                # 見出しは「直後の1番号」専用。束縛後 None に戻すことで、自前見出しの
                # ない「削除」通達が前項の見出しを継承しない (第2エッジ・タイトルなし)。
                # 条範囲の区切り (中点・/波ダッシュ) は番号内だけ "_" へ正規化。
                current_num = _normalize_directive_num(num_match.group(1), config)
                current_item_title = current_title
                current_title = None
                current_body_parts = []
                current_amendment = None
                # Get body text after the number (remove strong element text)
                strong.decompose()
                # R13: explicit newline before text (inline -> block)。入れ子ブロックは
                # 個別巡回されるため親段落テキストからは除外 (整形済みは get_text と同一)。
                remaining = _normalize_text(_text_excluding_nested_blocks(tag, "\n")).strip()
                if remaining:
                    current_body_parts.append(remaining)
                continue

        # CASE B/C: 段落テキスト先頭が番号 (B=split-strong / C=strong 無しの平文番号)。
        # CASE A で項を開始した段落は上で continue 済みなのでここには来ない。残るのは
        # (B) strong はあるが番号全体にならない (消費税 <strong>1</strong>－3－2 ...) と
        # (C) 古い節で番号が strong 無しの平文先頭にある法人税 (1-3の2-1　... / 1-8-1　...)。
        # 番号を含まない段落 (indent2 の「(1)…」等) は先頭が番号にならず非該当のため、
        # 本文段落を誤って項開始扱いしない (既存コーパスは byte 不変 = 回帰ゲートで実証)。
        plain = _normalize_text(_text_excluding_nested_blocks(tag)).strip()
        lead_match = case_b_re.match(plain)
        if lead_match:
            _flush(current_num, current_item_title, current_body_parts, current_amendment)
            # 条範囲の区切り (中点・/波ダッシュ) は番号内だけ "_" へ正規化。
            current_num = _normalize_directive_num(lead_match.group(1), config)
            current_item_title = current_title
            current_title = None  # consume-once (第2エッジ: 削除通達はタイトルなし)
            current_body_parts = []
            current_amendment = None
            remaining = plain[lead_match.end() :].strip()
            if remaining:
                current_body_parts.append(remaining)
            continue

        # Regular paragraph (indent1/indent2/other)。入れ子ブロック (malformed で吸い込まれた
        # 後続通達 <p>/<table>) は除外し二重計上を防ぐ (整形済みは get_text と同一 = byte 不変)。
        if current_num is not None:
            raw_text = _normalize_text(_text_excluding_nested_blocks(tag, "\n")).strip()
            if not raw_text:
                continue
            current_body_parts.append(raw_text)

    # Flush last item (確定済み見出しを使う)。
    _flush(current_num, current_item_title, current_body_parts, current_amendment)

    # Validate: 0 items = parse error
    if not items:
        warnings.warn(f"WARN: no directive items parsed from {source_url}", stacklevel=2)

    return items


def _build_source_url(config: CircularConfig, rel_path: Path) -> str:
    """NTA source URL from a path relative to the chapter root.

    Why: source_url must preserve the full chapter/section/目 sub-path so that
    4-level files (e.g. 09/01/01.htm under 第9章第1節第1目) map to the correct NTA
    URL. The old flat formula ``{base}/{chapter}/{stem}.htm`` dropped the 目 level
    and would have produced /shohi/09/01.htm for 09/01/01.htm. as_posix() keeps the
    URL separator '/' on every OS (Bug: Windows backslash leaking into URLs).
    """
    return f"{config.source_url_base}/{rel_path.as_posix()}"


def parse_file(htm_path: Path, config: CircularConfig, source_url: str) -> list[dict]:
    """Parse a single cached HTML file -> list of directive chunk dicts.

    source_url is computed by the caller (single-chapter: from --chapter + stem;
    multi-chapter: from the file path relative to the cache root via
    _build_source_url, preserving the 目 sub-path). Passing it in keeps this
    function path-policy-free and lets the single-chapter path stay byte-identical.
    """
    raw = htm_path.read_bytes()
    enc = _detect_charset(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except (LookupError, UnicodeDecodeError) as e:
        warnings.warn(
            f"WARN: decode error ({e}), falling back to cp932 for {htm_path.name}", stacklevel=2
        )
        text = raw.decode("cp932", errors="replace")

    # Decode sanity check (R1). cp932 decode with errors="replace" inserts U+FFFD
    # on byte failure; a correctly-decoded NTA page has zero. The old check looked
    # for hojin-specific keywords (経済的/役員/退職) which are absent in most 消費税
    # chapters -> false-positive warnings that could mask a real decode failure.
    # Replacement-char detection is circular-agnostic and fires only on real mojibake.
    n_repl = text.count("\ufffd")
    if n_repl:
        warnings.warn(
            f"WARN: {n_repl} replacement char(s) after decode in {htm_path.name} "
            f"(charset detected: {enc}) -- possible mojibake.",
            stacklevel=2,
        )

    soup = BeautifulSoup(text, "html.parser")
    items = _extract_directive_items(soup, source_url, config)
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse NTA tsutatsu HTML -> directive JSONL chunks.")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("cache/tsutatsu/hojin/09"),
        help="Single-chapter mode: directory of cached .htm files (uses --chapter for the URL).",
    )
    ap.add_argument(
        "--cache-root",
        type=Path,
        default=None,
        help=(
            "Multi-chapter mode: root holding <chapter>/<...>.htm. When set, all chapters "
            "under it are parsed, merged, globally numeric-sorted, and written to one file; "
            "source_url is derived per-file from its path (preserves the 目 sub-path). "
            "Takes precedence over --cache-dir/--chapter."
        ),
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/chunks/hojin-kihon-tsutatsu"),
        help="Output directory for JSONL chunk file.",
    )
    ap.add_argument(
        "--circular",
        choices=sorted(CIRCULAR_CONFIGS),
        default="hojin",
        help="Which circular's config to use (law_name / NTA URL base / ref_map).",
    )
    ap.add_argument("--chapter", default="09", help="Chapter directory name (e.g. '09').")
    ap.add_argument("--section", default="02", help="Section number prefix (e.g. '02').")
    ap.add_argument(
        "--glob-pattern",
        default="*.htm",
        help="Glob pattern to match HTML files in cache-dir.",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    config = CIRCULAR_CONFIGS[args.circular]

    # 取込対象ファイルと、各ファイル -> source_url の解決方法をモード別に確定する。
    # 単一章 (--cache-dir + --chapter): 非再帰 glob・URL は {base}/{chapter}/{stem}.htm
    #   (従来式そのまま -> hojin / 消費税第1章 byte 不変)。
    # 多章 (--cache-root): rglob・URL は root からの相対パス (目サブパス保持)。
    if args.cache_root is not None:
        root = args.cache_root
        if not root.exists():
            print(f"ERROR: cache-root not found: {root}", file=sys.stderr)
            return 1
        htm_files = sorted(
            p
            for p in root.rglob(args.glob_pattern)
            if _CHAPTER_DIR_RE.fullmatch(p.relative_to(root).parts[0])
            and p.name not in config.exclude_files
        )
        src_label = str(root)

        def _src_url(p: Path) -> str:
            return _build_source_url(config, p.relative_to(root))
    else:
        if not args.cache_dir.exists():
            print(f"ERROR: cache-dir not found: {args.cache_dir}", file=sys.stderr)
            return 1
        htm_files = sorted(
            p for p in args.cache_dir.glob(args.glob_pattern) if p.name not in config.exclude_files
        )
        src_label = str(args.cache_dir)

        def _src_url(p: Path) -> str:
            return _build_source_url(config, Path(args.chapter) / f"{p.stem}.htm")

    if not htm_files:
        print(f"ERROR: no .htm files found in {src_label}", file=sys.stderr)
        return 1

    print(f"Parsing {len(htm_files)} HTML file(s) from {src_label}", file=sys.stderr)

    all_items: list[dict] = []
    seen_ids: set[str] = set()
    seen_text: dict[str, str] = {}  # directive_id -> 本文 (重複 dedup の本文一致判定用)
    errors: list[str] = []

    for htm_path in htm_files:
        try:
            items = parse_file(htm_path, config, _src_url(htm_path))
        except Exception as e:
            msg = f"ERROR: failed to parse {htm_path.name}: {e}"
            print(msg, file=sys.stderr)
            errors.append(msg)
            continue

        if args.verbose:
            print(f"  {htm_path.name}: {len(items)} items", file=sys.stderr)

        for item in items:
            did = item["directive_id"]
            if not _directive_id_ok(did, config):
                # 形式ゲート (査読項11): 番号抽出が崩れた record を fail-loud で止める。
                print(
                    f"ERROR: directive_id {did!r} from {htm_path.name} violates the naming "
                    f"rule '{config.law_abbrev}-<chap>-<sec>-<item>(の<branch>)*'",
                    file=sys.stderr,
                )
                return 1
            if did in seen_ids:
                # NTA は同一通達を隣接セクション両ページに重複掲載する (例 所得税 62-1/62-2 が
                # 第60条関係 12/03.htm と 第62条関係 12/04.htm に本文一致で両載)。本文が完全一致
                # なら安全に dedup (後勝ちでなく先勝ちで黙ってスキップ)。本文が **異なる** 同番号は
                # 「目」階層・枝番のサイレント上書き (Bug36) ゆえ従来どおり fail-loud で止める。
                if item["text"] == seen_text[did]:
                    if args.verbose:
                        print(
                            f"  dedup: identical duplicate {did!r} from {htm_path.name} "
                            "(same body, cross-section reprint)",
                            file=sys.stderr,
                        )
                    continue
                print(
                    f"ERROR: duplicate directive_id {did!r} from {htm_path.name} with DIFFERENT "
                    "body (directive_id must be unique across the circular)",
                    file=sys.stderr,
                )
                return 1
            seen_ids.add(did)
            seen_text[did] = item["text"]
            all_items.append(item)

    if not all_items:
        print("ERROR: no directive items produced", file=sys.stderr)
        return 1

    # Sort by directive_number for deterministic output
    # e.g. "9-2-9" < "9-2-9の2" < "9-2-10" < "9-2-12の2"
    def _sort_key(item: dict) -> tuple:
        num = item["directive_number"]  # e.g. "9-2-12の2の3" / 所得税 "74_75-1"
        # Split on hyphen first, then on "の" within each part
        parts: list[int] = []
        for segment in num.split("-"):
            for sub in re.split(r"の", segment):
                if sub.isdigit():
                    parts.append(int(sub))
                else:
                    # 条範囲 "74_75" 等は先頭の条番号で代表させ物理順を保つ (74_75 -> 74)。
                    # HOJIN/SHOUHI は の-分割後すべて純数字ゆえこの枝に来ない (byte 不変)。
                    m = re.match(r"\d+", sub)
                    parts.append(int(m.group()) if m else 0)
        # Pad to fixed length for comparison
        while len(parts) < 6:
            parts.append(0)
        return tuple(parts)

    all_items.sort(key=_sort_key)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{config.law_abbrev}.tsutatsu.chunks.jsonl"

    # safe_write via juricode_shared
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "src"))
    from juricode_shared.safe_write import safe_write_jsonl

    safe_write_jsonl(out_path, all_items)

    print(f"Written {len(all_items)} directive chunks -> {out_path}", file=sys.stderr)

    # Summary
    for item in all_items:
        n_refs = len(item["related_articles"])
        linked = sum(1 for r in item["related_articles"] if r.get("article_id"))
        print(
            f"  {item['directive_number']:12s}  refs={n_refs}(linked={linked})  "
            f"chars={len(item['text'])}",
            file=sys.stderr,
        )

    if errors:
        print(f"\n{len(errors)} error(s) during parsing:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

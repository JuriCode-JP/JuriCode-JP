"""test_kfs_multi_article.py -- #72[C] 複数条列挙リンク取りこぼし修正の hermetic unit tests.

Why (#72[C]):
    旧 resolve_sanshou_jouken は 1 行を _ARTICLE_RE.search() で先頭 1 条のみ拾い、複数条列挙
    (国税通則法第12条第1項、第77条第1項) の 2 条目以降・同法/同法施行令の後方参照・別法令切替を
    落としていた (false-negative)。新 _extract_article_refs は 1 行を出現順に全走査する。本 test は:
      - 単一条は不変 (回帰なし)。
      - 複数条・同法(本則)・同法施行令/規則 の後方参照を全て拾う。
      - 号/項単独/別表は article 化しない (over-link 回避)。
      - 別法令混在で未マップ法令 (家事事件手続法・関税法) は非リンク (偽リンク0・R1)。
      - 埋め込み法令名 (○○法等の…に関する法律) は governing law と見なさない ((?!等)・偽リンク0)。
      - unmapped-law 由来の非リンク理由は unresolved_law、真の文脈なしは no_law_context (case(b))。
      - エントリ内 dedup は初出のみ・first paragraph 保持 (R3)。

    corpus 実在ガードは module-global _ARTICLE_CORPUS を注入して data/v0.2 非依存にする
    (test_kfs_saiketsu と同型)。_extract_article_refs は corpus に触れないため注入不要。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

_PARSER_PATH = _REPO_ROOT / "tools" / "parse" / "parse-kfs-saiketsu.py"


def _load_parser(corpus: set[str] | None = None):
    """ハイフン名モジュール parse-kfs-saiketsu.py を importlib で読み、corpus を注入して返す。"""
    spec = importlib.util.spec_from_file_location("parse_kfs_saiketsu", _PARSER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._ARTICLE_CORPUS = set(corpus or set())
    return mod


def _refs(mod, line: str) -> list[tuple[str | None, str, int | None]]:
    """(law_abbrev, art_num, paragraph) へ射影 (reason 4 要素目を落とす)。"""
    return [(c, a, p) for c, a, p, _reason in mod._extract_article_refs(line)]


def _linked(mod, line: str) -> list[tuple[str, str, int | None]]:
    """cur が解決した (非 None) ref のみ抽出。"""
    return [(c, a, p) for c, a, p in _refs(mod, line) if c is not None]


# ---------------------------------------------------------------------------
# _extract_article_refs: トークナイザ挙動
# ---------------------------------------------------------------------------


def test_single_article_unchanged():
    """単一条 (枝番付き) は 1 ref・不変 (R5 回帰なし)。"""
    mod = _load_parser()
    assert _refs(mod, "国税通則法第74条の9") == [("kokuzei-tsuusoku-hou", "74-9", None)]


def test_multi_article_enumeration():
    """複数条列挙の 2 条目以降を拾う (#72[C] の核心)。"""
    mod = _load_parser()
    assert _refs(mod, "国税通則法第12条第1項、第77条第1項") == [
        ("kokuzei-tsuusoku-hou", "12", 1),
        ("kokuzei-tsuusoku-hou", "77", 1),
    ]


def test_gou_kou_beppyo_not_article():
    """号 (第N号)・別表は article 化しない (over-link 回避・R2)。"""
    mod = _load_parser()
    assert _refs(mod, "消費税法第6条第1項、第30条、別表第一第7号イ") == [
        ("shouhi-zei-hou", "6", 1),
        ("shouhi-zei-hou", "30", None),
    ]


def test_same_law_backreference():
    """同法 (本則) は base 法令へ解決する。"""
    mod = _load_parser()
    assert _refs(mod, "相続税法第13条、同法第14条") == [
        ("souzoku-zei-hou", "13", None),
        ("souzoku-zei-hou", "14", None),
    ]


def test_same_shikkourei_backreference():
    """同法施行令は base の施行令へ解決する (R1b)。"""
    mod = _load_parser()
    assert _refs(mod, "所得税法第27条第1項、同法施行令第63条") == [
        ("shotoku-zei-hou", "27", 1),
        ("shotoku-zei-hou-shikkourei", "63", None),
    ]


def test_mixed_law_unmapped_not_linked():
    """別法令混在: 未マップ法令 (家事事件手続法) は非リンク・以降 reset (偽リンク0・R1)。"""
    mod = _load_parser()
    line = "民法第921条第1号、第3号、同法第938条、家事事件手続法第201条第5項"
    assert _linked(mod, line) == [("minpou", "921", None), ("minpou", "938", None)]
    # 家事事件手続法第201条 は cur=None (unresolved_law) で非リンク。
    reasons = {a: reason for c, a, _p, reason in mod._extract_article_refs(line) if c is None}
    assert reasons == {"201": "unresolved_law"}


def test_embedded_lawname_no_false_link():
    """埋め込み法令名 (○○法等の…に関する法律) は governing law でない ((?!等)・偽リンク0 回帰)。"""
    mod = _load_parser(corpus={"shotoku-zei-hou-art-7"})
    line = "協定の実施に伴う所得税法等の臨時特例に関する法律第7条"
    # 所得税法 は名称の一部ゆえ link しない。cur は None のまま。
    assert _linked(mod, line) == []
    res = mod.resolve_sanshou_jouken([line])
    assert res["links"] == [], "埋め込み法令名に偽リンクしている"


# ---------------------------------------------------------------------------
# resolve_sanshou_jouken: reason 区別 (case(b)) と dedup (R3)
# ---------------------------------------------------------------------------


def test_case_b_unresolved_law_reason():
    """未マップ法令由来の非リンクは reason=unresolved_law (case(b)・既存 test を無改変 green 化)。"""
    mod = _load_parser()
    res = mod.resolve_sanshou_jouken(["関税法第76条第1項"])
    assert res["links"] == []
    assert res["unlinked"] == [{"raw": "関税法第76条第1項", "reason": "unresolved_law"}]


def test_dedup_first_paragraph_kept():
    """エントリ内で同一 article_id は初出のみ・first paragraph を保持 (R3)。"""
    mod = _load_parser(corpus={"kokuzei-tsuusoku-hou-art-12"})
    res = mod.resolve_sanshou_jouken(["国税通則法第12条、第12条第2項"])
    assert len(res["links"]) == 1
    assert res["links"][0]["article_id"] == "kokuzei-tsuusoku-hou-art-12"
    assert res["links"][0]["relevant_paragraph"] is None  # 初出 (第12条・項なし) を保持

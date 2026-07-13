#!/usr/bin/env python3
"""Machine verification layer for the /chat orchestration (PoC P2).

出典つき・3値・断定なしの回答だけを通すための「機械検証層」。prompt 任せにしない
(過去の事故クラス: LLM に規律を約束させても守られない) ため、LLM 出力を規則で
機械的に検査し、違反を構造化して返す。違反時の再生成/フォールバックは呼び出し側
(chat_server) が担い、本モジュールは純関数の検査のみ (1 責務・副作用なし)。

core / policy の線引き:
    core (出典検証・ドメイン非依存) は packages/juricode-verifier (`juricode_verifier`) が正本。
    G1 出典実在・G2 逐語引用・valid_citations_only・snap はそちらに在り、本モジュールは
    税務チャット固有の policy (G3-G6) と、core + policy を合成するオーケストレータ
    (run_all_guards) を持つ。「何を検査するか」の方針はアプリ側 (ここ)、検査の部品は
    汎用パッケージ側、という責務分離。

ガード一覧 (PoC P2 §3.3):
    G1 出典実在   : citations[].chunk_id が「その回答で渡した hits の chunk_id 集合」の部分集合 (core)
    G2 逐語引用   : サーバー切り出しの citations[].quote が原文の逐語部分文字列 (byte 一致・core)
    G3 断定禁止   : answer に禁止表現 (辞書) が 0 件
    G4 数値非生成 : answer に税額・金額パターンが 0 件 (P2 では計算しない)
    G5 時制注記   : disclaimer_tense が非空
    G6 税理士法   : 橋渡しの定型文がテンプレどおり存在 (LLM の任意生成にしない)

Why 純関数: 検査を副作用なしの純関数に閉じることで、禁止表現辞書の各パターンを
テストから直接参照でき (§3.3 「辞書は定数として 1 箇所に」)、CI がモックだけで走る。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_VERIFIER_SRC = Path(__file__).resolve().parents[2] / "packages" / "juricode-verifier" / "src"
if str(_VERIFIER_SRC) not in sys.path:
    sys.path.insert(0, str(_VERIFIER_SRC))

from juricode_verifier import (  # noqa: E402
    Violation,
    check_citations_exist,
    check_quotes_verbatim,
)

# =====================================================
# 定数 (テストから参照する唯一の出所)
# =====================================================

#: verdict の許容 3 値。これ以外は schema 段階で 400、guard 段階でも G3 違反。
VALID_VERDICTS: frozenset[str] = frozenset({"該当", "非該当", "情報不足"})

#: 情報不足フォールバックの verdict 値。
VERDICT_INSUFFICIENT = "情報不足"

#: G3 禁止表現辞書 (name -> 正規表現)。断定・保証・結論の言い切りを機械検出する。
#: 名前は違反ログ・テストのケース名に使う。追加はここ 1 箇所のみ。
FORBIDDEN_ASSERTION_PATTERNS: dict[str, str] = {
    "kanarazu": r"必ず",
    "kakujitsu_ni": r"確実に",
    "zettai_ni": r"絶対に",
    "machigainaku": r"間違いなく",
    "mondai_arimasen": r"問題(?:は)?あり(?:ま)?せん",
    "mondai_nai": r"問題(?:は)?ない",
    "hinin_saremasen": r"否認され(?:ま)?せん",
    "hinin_sarenai": r"否認されない",
    "to_dangen": r"と(?:は)?断言",
    "hoshou_shimasu": r"保証(?:し|いた)ます",
    "hyaku_percent": r"(?:100|１００)\s*(?:%|％|パーセント)",
}

#: G4 数値生成パターン (list)。税額・金額を「生成」したら違反 (P2 は計算層でない)。
#: 円/万円/億円 の接尾辞を要求するので、条番号 (第9条) や通達番号 (9-2-9) は誤検出しない。
MONEY_PATTERNS: list[str] = [
    r"[0-9０-９][0-9０-９,，]*\s*円",
    r"[0-9０-９一二三四五六七八九十百千万]+\s*万\s*円",
    r"[0-9０-９一二三四五六七八九十百千]+\s*億\s*円",
]

#: G6 税理士法の橋渡し定型文 (テンプレ挿入・LLM 生成にしない)。
#: 本文は「情報提供であり税務代理・個別助言ではない」旨の中立注記。
TAX_LAW_BRIDGE = (
    "本回答は法令・通達等の一次情報に基づく情報提供であり、"
    "税理士法上の税務代理・税務相談(個別具体的な税務判断)には当たりません。"
    "個別の適用可否は税理士等の有資格者にご確認ください。"
)

_FORBIDDEN_COMPILED: dict[str, re.Pattern[str]] = {
    name: re.compile(pat) for name, pat in FORBIDDEN_ASSERTION_PATTERNS.items()
}
_MONEY_COMPILED: list[re.Pattern[str]] = [re.compile(p) for p in MONEY_PATTERNS]


# =====================================================
# 個別ガード (純関数・副作用なし)
# G1 (check_citations_exist) / G2 (check_quotes_verbatim) は juricode_verifier が正本
# (本モジュール冒頭で import 済み。run_all_guards が合成する)。
# =====================================================


def scan_forbidden_assertions(answer: str) -> list[Violation]:
    """G3: answer 本文に禁止表現辞書のパターンが 1 つも無いことを検査 (断定禁止)."""
    out: list[Violation] = []
    for name, pat in _FORBIDDEN_COMPILED.items():
        m = pat.search(answer)
        if m:
            out.append(Violation("G3", f"forbidden assertion {name!r} matched: {m.group(0)!r}"))
    return out


def scan_generated_numbers(answer: str) -> list[Violation]:
    """G4: answer 本文に税額・金額パターンが無いことを検査 (P2 は数値を生成しない)."""
    out: list[Violation] = []
    for pat in _MONEY_COMPILED:
        m = pat.search(answer)
        if m:
            out.append(Violation("G4", f"generated monetary amount matched: {m.group(0)!r}"))
    return out


def check_disclaimer(disclaimer_tense: str | None) -> list[Violation]:
    """G5: disclaimer_tense が非空であることを検査 (時制注記の欠落を塞ぐ)."""
    if not (disclaimer_tense and disclaimer_tense.strip()):
        return [Violation("G5", "disclaimer_tense is empty")]
    return []


def check_tax_law_bridge(notice: str | None) -> list[Violation]:
    """G6: 税理士法の橋渡し定型文がテンプレどおり存在することを検査.

    Why: 橋渡し文は server がテンプレ挿入する (LLM 任意生成にしない)。本検査は
    組立の欠落・改変 (バグ) を最終応答段で捕まえる belt-and-suspenders。
    """
    if notice != TAX_LAW_BRIDGE:
        return [Violation("G6", "tax-law bridge notice missing or altered")]
    return []


# =====================================================
# 集約 (chat_server から呼ぶ入口)
# =====================================================


def run_all_guards(
    verdict: str,
    answer: str,
    citations: list[dict],
    disclaimer_tense: str | None,
    notice: str,
    allowed_chunk_ids: set[str],
    chunk_texts: dict[str, str],
) -> list[Violation]:
    """G1-G6 を全て回して違反リストを返す (空なら合格)。呼び出し側が再生成/落としを判断.

    Why 全件返す: 最初の違反で打ち切らず全ガードを回すことで、B4 監査ログに違反の全容を
    残す (§3.3 「違反はすべて構造化ログに残す」)。順序は G1->G6。
    """
    violations: list[Violation] = []
    if verdict not in VALID_VERDICTS:
        violations.append(Violation("G3", f"verdict not one of the 3 values: {verdict!r}"))
    violations += check_citations_exist(citations, allowed_chunk_ids)
    violations += check_quotes_verbatim(citations, chunk_texts)
    violations += scan_forbidden_assertions(answer)
    violations += scan_generated_numbers(answer)
    violations += check_disclaimer(disclaimer_tense)
    violations += check_tax_law_bridge(notice)
    return violations

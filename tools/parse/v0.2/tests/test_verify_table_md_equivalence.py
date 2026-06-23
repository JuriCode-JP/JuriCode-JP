"""tests/test_verify_table_md_equivalence.py -- 構造等価ガードの純関数 test (FU-515 E-5).

cache/laws を要する law レベル検証ではなく、md->行抽出 / XML グリッド->期待行 の
純関数を committed fixture / 合成入力で検証する (CI-safe)。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from verify_table_md_equivalence import expected_rows_for_article, md_table_rows  # noqa: E402


def test_md_table_rows_excludes_separator_and_outside_section() -> None:
    md = (
        "---\nx: 1\n---\n\n"
        "## 原文 (日本語)\n\n"
        "### 第一条\n\n導入文。\n\n"
        "| 甲 | 乙 |\n"
        "| --- | --- |\n"
        "| 一 | 二 |\n\n"
        "## English Translation\n\n"
        "| should | not | count |\n"
    )
    rows = md_table_rows(md)
    assert rows == ["| 甲 | 乙 |", "| 一 | 二 |"]  # 区切り行除外・英訳側は対象外


def test_expected_rows_orders_by_paragraph_then_document() -> None:
    by_para = {
        2: [[["p2a", "x"], ["p2b", "y"]]],
        1: [[["p1", "z"]]],
    }
    rows = expected_rows_for_article(by_para)
    # paragraph 昇順: para1 -> para2
    assert rows == ["| p1 | z |", "| p2a | x |", "| p2b | y |"]


def test_md_rows_match_expected_for_simple_table() -> None:
    """md 抽出行と XML グリッド由来期待行が一致する (構造等価の核)."""
    md = (
        "---\n---\n\n## 原文 (日本語)\n\n### 第一条\n\n導入。\n\n"
        "| 区分 | 税率 |\n| --- | --- |\n| 一 | 五万円 |\n"
    )
    by_para = {1: [[["区分", "税率"], ["一", "五万円"]]]}
    assert md_table_rows(md) == expected_rows_for_article(by_para)

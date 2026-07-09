"""cases_splice の unit test (FU-71 md 削除スプライサ).

Why: 削除は「是正対象以外 byte 不変」が不変条件。block scalar 内の空行を跨ぐ・全除去で
`cases: []` に戻す・べき等・存在しない case_id は no-op、を固定する。
"""

from __future__ import annotations

import pytest
import yaml

from juricode_shared import CasesBlockError, remove_cases_from_md_text

# summary_ja の block scalar 内に空行を含む 2 エントリの md (実 corpus と同形)。
MD_TWO = """---
law_id: '325AC0000000073'
article_id: souzoku-zei-hou-art-11
paragraphs:
- number: 1
  segments:
  - id: souzoku-zei-hou-art-11-p1
    text: 相続税は、この節及び第三節に定めるところにより、
cases:
  - case_id: ntt-2013-08-29-j92-16
    case_type: ruling
    decision_date: '2013-08-29'
    summary_ja: '原処分庁は、審査請求人が提起した

      価額弁償の対象となった不動産は特定されているが、

      同項により価額を認定する。'
    issue_code: '0501010000'
  - case_id: ntt-2020-08-11-j120-4
    case_type: ruling
    decision_date: '2020-08-11'
    summary_ja: '取得財産に算入する遺留分減殺請求について、

      本件通達(2)によるべきとする更正の請求は認められない。'
    tags:
    - 参照通達:相続税法基本通達11の2-10
amendments: []
tags:
- phase1-tax
---

# 相続税法 第11条
"""

MD_EMPTY = (
    MD_TWO.replace("cases:\n", "cases: []\n", 1).split("cases: []")[0]
    + "cases: []\namendments: []\ntags:\n- phase1-tax\n---\n\n# 相続税法 第11条\n"
)


def _cases_of(md: str) -> list[str]:
    fm = yaml.safe_load(md.split("---\n", 2)[1]) or {}
    return [c["case_id"] for c in (fm.get("cases") or [])]


def test_remove_one_keeps_other_and_is_yaml_valid():
    new, n = remove_cases_from_md_text(MD_TWO, {"ntt-2013-08-29-j92-16"})
    assert n == 1
    assert _cases_of(new) == ["ntt-2020-08-11-j120-4"]


def test_removed_entry_bytes_gone_survivor_bytes_preserved():
    """残るエントリのバイト列は 1 文字も変わらない (yaml 再ダンプしていない証拠)。"""
    new, _ = remove_cases_from_md_text(MD_TWO, {"ntt-2013-08-29-j92-16"})
    assert "ntt-2013-08-29-j92-16" not in new
    assert "価額弁償の対象となった不動産は特定されているが、" not in new
    # 生き残りエントリ + 本文は逐語一致。
    survivor = MD_TWO[
        MD_TWO.index("  - case_id: ntt-2020-08-11-j120-4") : MD_TWO.index("amendments: []")
    ]
    assert survivor in new
    assert "# 相続税法 第11条" in new
    assert "text: 相続税は、この節及び第三節に定めるところにより、" in new


def test_blank_line_inside_block_scalar_does_not_split_entry():
    """block scalar 内の空行でエントリが切れると、除去が途中で止まり残骸が残る。"""
    new, n = remove_cases_from_md_text(MD_TWO, {"ntt-2020-08-11-j120-4"})
    assert n == 1
    assert "本件通達(2)によるべきとする更正の請求は認められない。" not in new
    assert "参照通達:相続税法基本通達11の2-10" not in new
    # 直後のトップレベルキーは残る。
    assert "\namendments: []\n" in new


def test_remove_all_degrades_to_empty_list():
    new, n = remove_cases_from_md_text(MD_TWO, {"ntt-2013-08-29-j92-16", "ntt-2020-08-11-j120-4"})
    assert n == 2
    assert "\ncases: []\n" in new
    fm = yaml.safe_load(new.split("---\n", 2)[1])
    assert fm["cases"] == []  # null でなく空リスト (IR 検証が通る形)
    assert fm["amendments"] == []


def test_idempotent_second_call_is_byte_identical():
    once, n1 = remove_cases_from_md_text(MD_TWO, {"ntt-2013-08-29-j92-16"})
    twice, n2 = remove_cases_from_md_text(once, {"ntt-2013-08-29-j92-16"})
    assert (n1, n2) == (1, 0)
    assert twice == once


def test_unknown_case_id_is_noop_byte_identical():
    new, n = remove_cases_from_md_text(MD_TWO, {"ntt-1999-01-01-j1-1"})
    assert n == 0
    assert new == MD_TWO


def test_empty_case_ids_is_noop():
    new, n = remove_cases_from_md_text(MD_TWO, set())
    assert (new, n) == (MD_TWO, 0)


def test_inline_empty_cases_list_is_noop():
    new, n = remove_cases_from_md_text(MD_EMPTY, {"ntt-2013-08-29-j92-16"})
    assert n == 0
    assert new == MD_EMPTY


def test_missing_cases_key_raises():
    md = "---\nlaw_id: x\namendments: []\n---\n\n# body\n"
    with pytest.raises(CasesBlockError):
        remove_cases_from_md_text(md, {"ntt-2013-08-29-j92-16"})


def test_missing_frontmatter_terminator_raises():
    with pytest.raises(CasesBlockError):
        remove_cases_from_md_text("---\ncases:\n  - case_id: x\n", {"x"})

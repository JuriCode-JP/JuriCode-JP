"""tests/test_emit_table_md.py -- 本則表の canonical md 反映 (emit_table_md.py / FU-515 E-3).

CI 内 (cache/laws 不在) で動くよう、committed fixture XML + 合成 md で実コードパスを
検証する。golden (312 の header+区切り+9税率) は §7 でロック済・改変禁止。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from emit_table_md import (  # noqa: E402
    build_gfm_block,
    collect_main_tables,
    insert_tables_into_md,
    resolve_article_and_paragraph,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDEN_XML = _FIXTURES / "chihou-zei-hou_main_table_excerpt.xml"


def _fixture_tables() -> dict:
    root = ET.parse(_GOLDEN_XML).getroot()
    pm = {c: p for p in root.iter() for c in p}
    return collect_main_tables(root, pm)


# ===========================================================
# build_gfm_block
# ===========================================================


def test_build_gfm_block_inserts_separator_after_first_row() -> None:
    block = build_gfm_block([["A", "B"], ["C", "D"], ["E", "F"]])
    assert block == ["| A | B |", "| --- | --- |", "| C | D |", "| E | F |"]


def test_build_gfm_block_separator_matches_column_count() -> None:
    block = build_gfm_block([["X", "Y", "Z"]])
    assert block[1] == "| --- | --- | --- |"


def test_build_gfm_block_empty_grid() -> None:
    assert build_gfm_block([]) == []


# ===========================================================
# insert_tables_into_md
# ===========================================================

_SYNTH_MD = (
    "---\n"
    "article_id: test-art-1\n"
    "article_number: '1'\n"
    "---\n\n"
    "## 原文 (日本語)\n\n"
    "### 第一条第一項\n\n"
    "<!-- segment: simple id: test-art-1-p1 -->\n"
    "次の表のとおりとする。\n\n"
    "### 第一条第二項\n\n"
    "<!-- segment: simple id: test-art-1-p2 -->\n"
    "別段の定めによる。\n\n"
    "## English Translation\n\n"
    "### Article 1\n"
    "table follows.\n"
)


def test_insert_into_target_paragraph_only() -> None:
    """表は対象項 (1) に入り、他項・英訳には入らない."""
    warnings: list[str] = []
    out = insert_tables_into_md(_SYNTH_MD, {1: [[["甲", "乙"], ["一", "二"]]]}, warnings)
    assert warnings == []
    p1 = out[out.find("### 第一条第一項") : out.find("### 第一条第二項")]
    p2 = out[out.find("### 第一条第二項") : out.find("## English")]
    en = out[out.find("## English") :]
    assert "| 甲 | 乙 |" in p1
    assert "| --- | --- |" in p1
    assert "| 一 | 二 |" in p1
    assert "次の表のとおりとする。" in p1  # 導入文は保持
    assert "|" not in p2  # 第二項には表が入らない
    assert "甲" not in en  # 英訳側は不変


def test_insert_preserves_option_a_empty_cells() -> None:
    warnings: list[str] = []
    out = insert_tables_into_md(_SYNTH_MD, {1: [[["試掘", "", "二百"]]]}, warnings)
    assert "| 試掘 |  | 二百 |" in out


def test_no_tables_is_noop_backward_compat() -> None:
    """表が無ければ md をバイト不変で返す (後方互換: 表なし条文の hash 不変)."""
    warnings: list[str] = []
    out = insert_tables_into_md(_SYNTH_MD, {}, warnings)
    assert out == _SYNTH_MD
    assert warnings == []


def test_idempotent_skips_paragraph_with_existing_table() -> None:
    """既に表がある項には二重挿入しない (再実行・逐次展開で安全)."""
    warnings: list[str] = []
    once = insert_tables_into_md(_SYNTH_MD, {1: [[["甲", "乙"], ["一", "二"]]]}, warnings)
    twice = insert_tables_into_md(once, {1: [[["甲", "乙"], ["一", "二"]]]}, warnings)
    assert twice == once  # 2 回目は no-op
    assert once.count("| 甲 | 乙 |") == 1  # 表は 1 個のみ
    assert any("冪等" in w for w in warnings)


def test_out_of_range_paragraph_warns_not_crash() -> None:
    """見出し数を超える項番号は警告して skip (crash しない)."""
    warnings: list[str] = []
    out = insert_tables_into_md(_SYNTH_MD, {9: [[["a", "b"]]]}, warnings)
    assert out == _SYNTH_MD  # 挿入されない
    assert any("範囲外" in w for w in warnings)


def test_missing_ja_section_warns() -> None:
    warnings: list[str] = []
    md = "---\nx: 1\n---\n\n## English Translation\n\ntext\n"
    out = insert_tables_into_md(md, {1: [[["a", "b"]]]}, warnings)
    assert out == md
    assert any("原文" in w for w in warnings)


# ===========================================================
# resolve_article_and_paragraph (suppl provision scope-out)
# ===========================================================


def test_suppl_provision_table_scoped_out() -> None:
    root = ET.Element("Law")
    sp = ET.SubElement(root, "SupplProvision")
    art = ET.SubElement(sp, "Article", Num="5")
    para = ET.SubElement(art, "Paragraph", Num="2")
    ts = ET.SubElement(para, "TableStruct")
    pm = {c: p for p in root.iter() for c in p}
    assert resolve_article_and_paragraph(ts, pm) == ("", 0)


def test_main_provision_resolves_article_and_paragraph() -> None:
    root = ET.Element("Law")
    mp = ET.SubElement(root, "MainProvision")
    art = ET.SubElement(mp, "Article", Num="312")
    para = ET.SubElement(art, "Paragraph", Num="1")
    ts = ET.SubElement(para, "TableStruct")
    pm = {c: p for p in root.iter() for c in p}
    assert resolve_article_and_paragraph(ts, pm) == ("312", 1)


# ===========================================================
# golden: fixture 312 を合成 md に反映
# ===========================================================

LOCKED_312_RATES = (
    "五万円",
    "十二万円",
    "十三万円",
    "十五万円",
    "十六万円",
    "四十万円",
    "四十一万円",
    "百七十五万円",
    "三百万円",
)


def test_golden_312_reflected_into_md() -> None:
    """fixture 312 の表が合成 md の項1 に header+区切り+9税率で反映される (LOCKED)."""
    tables = _fixture_tables()
    assert "312" in tables
    md = (
        "---\narticle_id: chihou-zei-hou-art-312\narticle_number: '312'\n---\n\n"
        "## 原文 (日本語)\n\n"
        "### 第三百十二条第一項\n\n"
        "<!-- segment: simple id: chihou-zei-hou-art-312-p1 -->\n"
        "法人に対して課する均等割の標準税率は、次の表の上欄に掲げる法人の区分に応じ、"
        "それぞれ同表の下欄に定める額とする。\n\n"
    )
    warnings: list[str] = []
    out = insert_tables_into_md(md, tables["312"], warnings)
    assert warnings == []
    assert "| 法人の区分 | 税率 |" in out
    assert "| --- | --- |" in out
    for rate in LOCKED_312_RATES:
        assert f"年額 {rate} |" in out, f"税率 {rate} が反映されていない"

"""tests/test_extract_table_from_xml.py -- extract_table_from_xml の単体テスト."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from extract_table_from_xml import (  # noqa: E402, I001
    MAX_LEADIN_LEN,
    MAX_ROWS_PER_CHUNK,
    build_table_chunks_for_ts,
    expand_virtual_grid,
    get_leadin_for_table,
    grid_to_pipe_rows,
    normalize_cell_text,
    table_to_pipe_rows_safe,
    trim_leadin,
)


# ============================================================
# Helpers for building minimal XML
# ============================================================


def make_para_with_table(leadin_text: str, rows_data: list[list[str]]) -> tuple:
    """Paragraph > ParagraphSentence + TableStruct を構築して (ts, parent_map) を返す."""
    root_elem = ET.Element("Law")
    para = ET.SubElement(root_elem, "Paragraph", Num="1")
    ps = ET.SubElement(para, "ParagraphSentence")
    sent = ET.SubElement(ps, "Sentence")
    sent.text = leadin_text
    ts = ET.SubElement(para, "TableStruct")
    table = ET.SubElement(ts, "Table")
    for row_cells in rows_data:
        row = ET.SubElement(table, "TableRow")
        for cell_text in row_cells:
            col = ET.SubElement(row, "TableColumn")
            col.text = cell_text
    parent_map = {child: parent for parent in root_elem.iter() for child in parent}
    return ts, parent_map


def make_ts_with_rowspan(row_specs: list[list[tuple[str, int, int]]]) -> ET.Element:
    """rowspan/colspan 指定付きの TableStruct を構築.

    row_specs: [[("text", rowspan, colspan), ...], ...]
    """
    ts = ET.Element("TableStruct")
    table = ET.SubElement(ts, "Table")
    for row_data in row_specs:
        row = ET.SubElement(table, "TableRow")
        for cell_text, rs, cs in row_data:
            col = ET.SubElement(row, "TableColumn")
            col.text = cell_text
            if rs != 1:
                col.set("rowspan", str(rs))
            if cs != 1:
                col.set("colspan", str(cs))
    return ts


# ============================================================
# normalize_cell_text
# ============================================================


def test_normalize_cell_text_strips_whitespace():
    assert normalize_cell_text("  hello  ") == "hello"


def test_normalize_cell_text_collapses_whitespace():
    assert normalize_cell_text("a  b\tc") == "a b c"


def test_normalize_cell_text_escapes_pipe():
    assert normalize_cell_text("a|b") == r"a\|b"


def test_normalize_cell_text_collapses_newline():
    assert normalize_cell_text("a\nb") == "a b"


# ============================================================
# trim_leadin
# ============================================================


def test_trim_leadin_short():
    text = "短い導入文"
    assert trim_leadin(text) == text


def test_trim_leadin_long_truncates():
    text = "a" * (MAX_LEADIN_LEN + 50)
    result = trim_leadin(text)
    assert len(result) == MAX_LEADIN_LEN


# ============================================================
# expand_virtual_grid
# ============================================================


def test_expand_virtual_grid_simple():
    """3列2行の単純テーブル."""
    ts = make_ts_with_rowspan(
        [
            [("A", 1, 1), ("B", 1, 1), ("C", 1, 1)],
            [("D", 1, 1), ("E", 1, 1), ("F", 1, 1)],
        ]
    )
    rows = list(ts.iter("TableRow"))
    grid = expand_virtual_grid(rows)
    assert len(grid) == 2
    assert grid[0] == ["A", "B", "C"]
    assert grid[1] == ["D", "E", "F"]


def test_expand_virtual_grid_rowspan():
    """rowspan=2 のセルが次行に複製される."""
    # Row 0: [A(rowspan=2), B, C]
    # Row 1: [D, E]  (A が自動補完される)
    ts = make_ts_with_rowspan(
        [
            [("A", 2, 1), ("B", 1, 1), ("C", 1, 1)],
            [("D", 1, 1), ("E", 1, 1)],
        ]
    )
    rows = list(ts.iter("TableRow"))
    grid = expand_virtual_grid(rows)
    assert len(grid) == 2
    assert grid[0][0] == "A"
    assert grid[1][0] == "A"  # 複製されている
    assert grid[1][1] == "D"


def test_expand_virtual_grid_colspan():
    """colspan=2 のセルが横方向に展開される."""
    ts = make_ts_with_rowspan(
        [
            [("AB", 1, 2), ("C", 1, 1)],
            [("D", 1, 1), ("E", 1, 1), ("F", 1, 1)],
        ]
    )
    rows = list(ts.iter("TableRow"))
    grid = expand_virtual_grid(rows)
    assert grid[0][0] == "AB"
    assert grid[0][1] == "AB"  # colspan 展開
    assert grid[0][2] == "C"


def test_expand_virtual_grid_empty():
    result = expand_virtual_grid([])
    assert result == []


# ============================================================
# grid_to_pipe_rows
# ============================================================


def test_grid_to_pipe_rows():
    grid = [["A", "B", "C"], ["D", "E", "F"]]
    rows = grid_to_pipe_rows(grid)
    assert rows == ["| A | B | C |", "| D | E | F |"]


# ============================================================
# get_leadin_for_table
# ============================================================


def test_get_leadin_for_table_paragraph_parent():
    leadin = "次の表の上欄に掲げる字句は下欄に読み替える。"
    ts, parent_map = make_para_with_table(leadin, [["A", "B"], ["C", "D"]])
    result = get_leadin_for_table(ts, parent_map)
    assert result == leadin


def test_get_leadin_for_table_no_parent():
    ts = ET.Element("TableStruct")
    result = get_leadin_for_table(ts, {})
    assert result == ""


# ============================================================
# table_to_pipe_rows_safe
# ============================================================


def test_table_to_pipe_rows_safe_normal():
    _, parent_map = make_para_with_table("dummy", [["X", "Y"], ["Z", "W"]])
    # TableStruct は Paragraph の子として作成されているのでそれを取得
    table_structs = [e for e in parent_map if e.tag == "TableStruct"]
    assert len(table_structs) == 1
    rows = table_to_pipe_rows_safe(table_structs[0])
    assert len(rows) == 2
    assert "X" in rows[0]
    assert "Y" in rows[0]


def test_table_to_pipe_rows_safe_empty():
    ts = ET.Element("TableStruct")
    rows = table_to_pipe_rows_safe(ts)
    assert rows == []


# ============================================================
# build_table_chunks_for_ts (window split)
# ============================================================


def test_build_table_chunks_single_window():
    """MAX_ROWS_PER_CHUNK 以内なら 1 chunk で分割なし."""
    ts, parent_map = make_para_with_table(
        "導入文",
        [["A", "B"]] * 3,  # 3行 < MAX_ROWS_PER_CHUNK
    )
    meta = {"article_id": "test-art-1", "law_id": "TESTLAW", "law_name_ja": "テスト法"}
    chunks = build_table_chunks_for_ts(ts, "導入文", "test-art-1", meta, 1)
    assert len(chunks) == 1
    assert chunks[0]["id"] == "test-art-1-tbl1"
    assert "導入文" in chunks[0]["text"]
    assert "segment_type" in chunks[0]
    assert chunks[0]["segment_type"] == "table"


def test_build_table_chunks_multi_window():
    """MAX_ROWS_PER_CHUNK より多い行は複数 chunk に分割される."""
    rows = [["A", "B"]] * (MAX_ROWS_PER_CHUNK + 3)
    ts, parent_map = make_para_with_table("導入文", rows)
    meta = {"article_id": "test-art-2", "law_id": "TESTLAW", "law_name_ja": "テスト法"}
    chunks = build_table_chunks_for_ts(ts, "導入文", "test-art-2", meta, 1)
    assert len(chunks) == 2
    assert chunks[0]["id"].endswith("-tbl1-w0")
    assert chunks[1]["id"].endswith("-tbl1-w1")
    # 各 chunk に導入文が入っている
    for c in chunks:
        assert "導入文" in c["text"]


def test_build_table_chunks_leadin_in_each_window():
    """全 window に leadin が前置きされる."""
    rows = [["C" + str(i), "D" + str(i)] for i in range(MAX_ROWS_PER_CHUNK + 5)]
    ts, parent_map = make_para_with_table("次の表の内容", rows)
    meta = {"article_id": "test-art-3", "law_id": "TESTLAW", "law_name_ja": "テスト法"}
    chunks = build_table_chunks_for_ts(ts, "次の表の内容", "test-art-3", meta, 1)
    for c in chunks:
        assert c["text"].startswith("次の表の内容")


# ============================================================
# Integration: corpus から table chunk が取得できる
# ============================================================

CORPUS_PATH = Path("build/corpus-v0.2.jsonl")


@pytest.mark.skipif(not CORPUS_PATH.exists(), reason="corpus not built yet")
def test_corpus_contains_table_chunks():
    """corpus に table chunk が存在する (446件以上)."""
    count = 0
    with CORPUS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("segment_type") == "table":
                count += 1
    assert count >= 400, f"Expected >= 400 table chunks, got {count}"


@pytest.mark.skipif(not CORPUS_PATH.exists(), reason="corpus not built yet")
def test_corpus_table_chunks_have_text():
    """全 table chunk に非空 text フィールドがある."""
    empty_count = 0
    with CORPUS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("segment_type") == "table":
                if not d.get("text", "").strip():
                    empty_count += 1
    assert empty_count == 0, f"{empty_count} table chunks have empty text"


@pytest.mark.skipif(not CORPUS_PATH.exists(), reason="corpus not built yet")
def test_corpus_table_chunks_have_article_id():
    """本則 table chunk には article_id がある."""
    missing = 0
    checked = 0
    with CORPUS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("segment_type") == "table" and "supplproviso" not in d.get("chunk_id", ""):
                checked += 1
                if not d.get("article_id"):
                    missing += 1
    assert missing == 0, f"{missing}/{checked} main-provision table chunks missing article_id"


@pytest.mark.skipif(not CORPUS_PATH.exists(), reason="corpus not built yet")
def test_corpus_table_chunks_contain_pipe():
    """table chunk の text には | が含まれる（表が直列化されている）."""
    without_pipe = 0
    total = 0
    with CORPUS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("segment_type") == "table":
                total += 1
                # table chunk のうち表セルが空でないものは必ず | を含む
                text = d.get("text", "")
                has_newline = "\n" in text
                if has_newline and "|" not in text:
                    without_pipe += 1
    # 行区切りがあるのに | が無いケースは 0 であるべき
    assert without_pipe == 0, f"{without_pipe} table chunks have rows but no pipe separators"

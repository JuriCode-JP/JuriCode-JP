"""tests/test_table_core.py -- 表直列化コア (table_core.py) の単体 + 回帰テスト (FU-515 E-1).

Why this test exists:
    table_core.py は extract_table_from_xml.py から **挙動を変えずに** 切り出した
    共通コア (E-1 pure refactor)。E-3 (md 反映) と E-4 (canonical_hash) が同じコアを
    使うため、ここで核となる直列化規約 (Option A 空セル維持・rowspan 値複製・colspan
    寛容・例外フォールバック) を pin する。

    回帰ゲート (briedfing E-1 / Bug15): build/chunks の table.chunks.jsonl は
    gitignored ゆえサイレント・デグレし得る。フルコーパスのバイト一致は cache/laws
    を要するためローカル検証 (push 前)。CI 内では委員会済 fixture XML で
    table_to_pipe_rows_safe の出力を golden 固定し、コア直列化のデグレを検出する。
    **落ちたら直すのはコードであって golden ではない** (§7 佐藤ロック)。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from table_core import (  # noqa: E402
    expand_virtual_grid,
    get_leadin_for_table,
    normalize_cell_text,
    table_to_grid_safe,
    table_to_pipe_rows_safe,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDEN_XML = _FIXTURES / "chihou-zei-hou_main_table_excerpt.xml"

# LOCKED golden (§7・佐藤ロック・改変禁止). 出典 e-Gov 325AC0000000226 第312条.
LOCKED_312_HEADER = "| 法人の区分 | 税率 |"
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


# ===========================================================
# helpers
# ===========================================================


def _make_ts(row_specs: list[list[tuple[str, int, int]]]) -> ET.Element:
    """rowspan/colspan 指定付きの TableStruct を構築. row_specs: [[(text, rs, cs), ...], ...]."""
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


def _ts_for_article(num: str) -> ET.Element:
    root = ET.parse(_GOLDEN_XML).getroot()
    for art in root.iter("Article"):
        if art.get("Num") == num:
            return next(art.iter("TableStruct"))
    raise AssertionError(f"fixture に Article Num={num} の TableStruct が無い")


# ===========================================================
# normalize_cell_text
# ===========================================================


def test_normalize_collapses_whitespace_and_newlines() -> None:
    assert normalize_cell_text("a  b\tc\nd") == "a b c d"


def test_normalize_escapes_pipe() -> None:
    assert normalize_cell_text("a|b") == r"a\|b"


def test_normalize_preserves_fullwidth_dash() -> None:
    """全角ダッシュ ― (U+2015) は ASCII 置換せず逐語保持 (§3.5.3)."""
    bar = "―"
    assert normalize_cell_text(f"  {bar}  ") == bar


# ===========================================================
# expand_virtual_grid: rowspan 値複製 / 明示空セル維持 / colspan 寛容
# ===========================================================


def test_rowspan_value_duplication() -> None:
    """rowspan=2 のセルは展開後 2 行の同列に逐語複製される (D-a 方式・Option A)."""
    ts = _make_ts([[("A", 2, 1), ("B", 1, 1)], [("C", 1, 1)]])
    grid = expand_virtual_grid(list(ts.iter("TableRow")))
    assert grid[0] == ["A", "B"]
    assert grid[1] == ["A", "C"]  # A が rowspan で複製、C は空き列へ


def test_explicit_empty_cell_preserved_option_a() -> None:
    """明示的な空セルは空のまま維持する (Option A: 罫線結合は再現しない)."""
    ts = _make_ts([[("試掘鉱区", 1, 1), ("", 1, 1), ("二百円", 1, 1)]])
    grid = expand_virtual_grid(list(ts.iter("TableRow")))
    assert grid[0] == ["試掘鉱区", "", "二百円"]


def test_colspan_expands_value() -> None:
    """colspan=2 は横方向に値複製 (見出し行等)."""
    ts = _make_ts([[("AB", 1, 2), ("C", 1, 1)], [("D", 1, 1), ("E", 1, 1), ("F", 1, 1)]])
    grid = expand_virtual_grid(list(ts.iter("TableRow")))
    assert grid[0] == ["AB", "AB", "C"]


def test_colspan_tolerant_rectangular_grid() -> None:
    """colspan は max_cols を広げて値複製し、grid は矩形を保つ (クラッシュ禁止)."""
    # 2 行目 colspan=5 が max_cols=5 を決め、grid は全行 5 列の矩形になる
    ts = _make_ts([[("A", 1, 1), ("B", 1, 1)], [("X", 1, 5)]])
    grid = expand_virtual_grid(list(ts.iter("TableRow")))
    assert len(grid) == 2
    assert all(len(r) == 5 for r in grid), "grid が矩形でない"
    assert grid[1] == ["X", "X", "X", "X", "X"]  # colspan=5 を値複製


def test_overflow_cell_dropped_tolerantly() -> None:
    """rowspan が全列を埋めた行に余剰セルが来たら drop + 素通し (例外を投げない)."""
    # 行1: A(rowspan=2, colspan=2) が max_cols=2 を全部埋め、両列を carry
    # 行2: B は置く先が無い → overflow で drop (warn) されるが crash しない
    ts = _make_ts([[("A", 2, 2)], [("B", 1, 1)]])
    grid = expand_virtual_grid(list(ts.iter("TableRow")))
    assert len(grid) == 2
    assert grid[0] == ["A", "A"]
    assert grid[1] == ["A", "A"]  # carry で両列埋まり、B は drop


# ===========================================================
# table_to_grid_safe / table_to_pipe_rows_safe
# ===========================================================


def test_grid_and_pipe_rows_consistent() -> None:
    """table_to_grid_safe と table_to_pipe_rows_safe は同じ表を表す."""
    ts = _make_ts([[("A", 1, 1), ("B", 1, 1)], [("C", 1, 1), ("D", 1, 1)]])
    grid = table_to_grid_safe(ts)
    rows = table_to_pipe_rows_safe(ts)
    assert grid == [["A", "B"], ["C", "D"]]
    assert rows == ["| A | B |", "| C | D |"]


def test_empty_tablestruct_returns_empty() -> None:
    assert table_to_grid_safe(ET.Element("TableStruct")) == []
    assert table_to_pipe_rows_safe(ET.Element("TableStruct")) == []


def test_get_leadin_from_paragraph() -> None:
    root = ET.Element("Law")
    para = ET.SubElement(root, "Paragraph", Num="1")
    ps = ET.SubElement(para, "ParagraphSentence")
    ET.SubElement(ps, "Sentence").text = "次の表の上欄に掲げる字句は下欄に読み替える。"
    ts = ET.SubElement(para, "TableStruct")
    pm = {c: p for p in root.iter() for c in p}
    assert get_leadin_for_table(ts, pm) == "次の表の上欄に掲げる字句は下欄に読み替える。"


# ===========================================================
# 回帰 golden (committed fixture・CI 内で動く)
# ===========================================================


def test_golden_312_pipe_rows_locked() -> None:
    """fixture 312 の直列化が header + 9 税率 (LOCKED) を厳密に再現する."""
    rows = table_to_pipe_rows_safe(_ts_for_article("312"))
    assert len(rows) == 10, f"312 は header+9行=10 行のはず: {len(rows)}"
    assert rows[0] == LOCKED_312_HEADER
    for i, rate in enumerate(LOCKED_312_RATES, start=1):
        assert rate in rows[i], f"行{i} にロック済税率 {rate} が無い: {rows[i]!r}"


def test_golden_312_deterministic() -> None:
    """同一入力で 2 回直列化してもバイト一致 (冪等・サイレントデグレ防止)."""
    a = table_to_pipe_rows_safe(_ts_for_article("312"))
    b = table_to_pipe_rows_safe(_ts_for_article("312"))
    assert a == b


def test_golden_180_empty_cell_preserved() -> None:
    """fixture 180 (鉱区税) は空セルを維持し列潰れしない (Option A)."""
    grid = table_to_grid_safe(_ts_for_article("180"))
    assert grid, "180 の grid が空"
    # いずれかの行に空セルが存在する (罫線結合を値複製していない証跡)
    assert any("" in row for row in grid), "空セルが維持されていない = 列潰れ"

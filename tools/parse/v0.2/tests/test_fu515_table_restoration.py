"""tests/test_fu515_table_restoration.py -- FU-515 本則 TableStruct 修復の回帰テスト.

Why this test exists:
    extract_table_from_xml.py が既定 `data/` (本法を欠く) を走査していたため、本則
    TableStruct (税率表等) が build/chunks に一切生成されていなかった (本則 table
    chunks = 0)。本テストは (1) 走査ロジックが v0.2 layout を発見し異常を fail-loud
    すること、(2) 復元された本則表の golden 値、(3) 冪等性、を pin する。

テスト方針:
    - T1 は hermetic な fake_data fixtures (実 corpus 非依存・実法令数を assert しない)。
    - T2 / T2b は cache/laws (gitignored・CI 不在) に依存しないよう、地方税法 312条/180条
      の <TableStruct> を含む最小 fixture XML をコミットし、実コードパス
      (extract_main_table_chunks) で検証する。
    - golden 値 (T2 の 9 税率 / T2b の対応関係・3 値) は §7 で佐藤がロック済。
      **落ちたら直すのはコードであって expected ではない**。
"""

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
    build_law_abbrev_to_id_phase,
    extract_main_table_chunks,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_FAKE_DATA = _FIXTURES / "fake_data"
_GOLDEN_XML = _FIXTURES / "chihou-zei-hou_main_table_excerpt.xml"

# ===========================================================
# LOCKED golden expectations (§7・佐藤ロック・改変禁止)
# 出典: e-Gov XML 325AC0000000226 第312条/第180条
# ===========================================================

# T2: 地方税法 312条 法人の均等割 9 区分 年額 (LOCKED - DO NOT EDIT)
LOCKED_312_RATES: tuple[str, ...] = (
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

# T2b: 地方税法 180条 鉱区税 対応関係 + 3 値 (LOCKED - DO NOT EDIT)
LOCKED_180_PAIRING: tuple[str, ...] = ("試掘鉱区", "二百円", "採掘鉱区", "四百円")
LOCKED_180_SAND_ROW: tuple[str, ...] = ("面積百アールごとに", "二百円")

_GOLDEN_LAW_ID = "325AC0000000226"


# ===========================================================
# helpers
# ===========================================================


def _load_main_chunks() -> dict[str, list[dict]]:
    """fixture XML を実コードパスで処理し article_num -> chunks を返す."""
    tree = ET.parse(_GOLDEN_XML)
    root = tree.getroot()
    parent_map = {child: parent for parent in root.iter() for child in parent}
    return extract_main_table_chunks(root, parent_map, "chihou-zei-hou", _GOLDEN_LAW_ID, "地方税法")


def _find_chunk_by_metadata(
    chunks_by_article: dict[str, list[dict]], law_id: str, article_number: str
) -> list[dict]:
    """まず metadata で正しい条文の chunk を特定 (他条文の同一文字列で誤 PASS しない)."""
    matched: list[dict] = []
    for chunks in chunks_by_article.values():
        for ch in chunks:
            if ch.get("law_id") == law_id and ch.get("article_number") == article_number:
                matched.append(ch)
    return matched


def _is_ordered_subsequence(text: str, tokens: tuple[str, ...]) -> bool:
    """tokens が text 内にこの順序で (重なりなく) 出現するか."""
    pos = -1
    for tok in tokens:
        idx = text.find(tok, pos + 1)
        if idx < 0:
            return False
        pos = idx
    return True


def _canonical(record: dict) -> str:
    """型厳密な正準文字列 (キー順非依存 + int/float・null/"" 型差検知 + 改行非依存)."""
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


# ===========================================================
# T1: layout regression (hermetic fixtures)
# ===========================================================


def test_t1a_discovers_v02_layout() -> None:
    """phase* 直下の law_dir を発見し law_abbrev -> (law_id, phase) を構築 (実法令数は assert しない)."""
    law_map = build_law_abbrev_to_id_phase(_FAKE_DATA / "valid")
    assert set(law_map.keys()) == {"law-alpha", "law-beta"}
    assert law_map["law-alpha"] == ("TESTALPHA0001", "phase1-alpha")
    assert law_map["law-beta"] == ("TESTBETA0001", "phase2-beta")


def test_t1b_duplicate_abbrev_fails_loud() -> None:
    """同一 law_abbrev が複数 phase dir に出現したら fail-loud (silent 片選び禁止)."""
    with pytest.raises(ValueError, match="重複する law_abbrev"):
        build_law_abbrev_to_id_phase(_FAKE_DATA / "duplicate")


def test_t1c_zero_laws_fails_loud(tmp_path: Path) -> None:
    """1 法令も発見できなければ fail-loud (silent な 0 件出力を防ぐ)."""
    (tmp_path / "not-a-phase-dir").mkdir()
    with pytest.raises(ValueError, match="1 件も発見できません"):
        build_law_abbrev_to_id_phase(tmp_path)


def test_t1d_silent_drop_fails_loud() -> None:
    """md を持つ law_dir が law_id を生まなければ fail-loud (coverage 欠落防止)."""
    with pytest.raises(ValueError, match="law_id を frontmatter から抽出できません"):
        build_law_abbrev_to_id_phase(_FAKE_DATA / "silent_drop")


# ===========================================================
# T2 (LOCKED): golden 地方税法312条 均等割税率
# ===========================================================


def test_t2_golden_312_kintouwari_rates_locked() -> None:
    """metadata 照合で 312条 chunk を特定 → ロック済 9 税率がその chunk に出現する."""
    chunks_by_article = _load_main_chunks()
    matched = _find_chunk_by_metadata(chunks_by_article, _GOLDEN_LAW_ID, "312")
    assert matched, "312条 (law_id=325AC0000000226) の本則 table chunk が見つからない"

    combined = "\n".join(ch["text"] for ch in matched)
    missing = [rate for rate in LOCKED_312_RATES if rate not in combined]
    assert not missing, f"312条 table chunk に欠落しているロック済税率: {missing}"


# ===========================================================
# T2b (LOCKED): golden 地方税法180条 鉱区税 (セルずれ検知)
# ===========================================================


def test_t2b_golden_180_kouku_pairing_locked() -> None:
    """180条 chunk を metadata 照合で特定 → 対応関係 (試掘=二百/採掘=四百) と空セルを assert."""
    chunks_by_article = _load_main_chunks()
    matched = _find_chunk_by_metadata(chunks_by_article, _GOLDEN_LAW_ID, "180")
    assert matched, "180条 (law_id=325AC0000000226) の本則 table chunk が見つからない"

    text = "\n".join(ch["text"] for ch in matched)
    # 対応関係 (順序): 試掘鉱区→二百円→採掘鉱区→四百円 が入れ替わったら fail
    assert _is_ordered_subsequence(text, LOCKED_180_PAIRING), (
        f"180条 鉱区税の対応関係が崩れている (期待順序 {LOCKED_180_PAIRING}): {text!r}"
    )
    # 砂鉱目的行: 面積百アールごとに→二百円
    assert _is_ordered_subsequence(text, LOCKED_180_SAND_ROW)
    # 空セルが保持されている (列潰れしていない)
    assert "|  |" in text, "空セル (|  |) が保持されていない = 列潰れ (意味的破損)"


# ===========================================================
# T3: idempotency (型厳密な正準比較)
# ===========================================================


def test_t3_idempotent_canonical() -> None:
    """同一入力 2 回で各 chunk record が正準文字列レベルで一致 (行順序保持)."""
    run_a = _load_main_chunks()
    run_b = _load_main_chunks()

    assert sorted(run_a.keys()) == sorted(run_b.keys())
    for art_num in run_a:
        canon_a = [_canonical(ch) for ch in run_a[art_num]]
        canon_b = [_canonical(ch) for ch in run_b[art_num]]
        assert canon_a == canon_b, f"art {art_num} の chunk が冪等でない"

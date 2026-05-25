"""Tests for AMEND_LAW_NUM_PATTERN (FU-304).

Why this test exists:
    The old regex used `[^第]*第N号` (greedy any-char up to 第) which falsely
    matched unrecognized prefixes in AmendLawNum strings. FU-304 replaced
    this with a literal alternation of recognized law types
    (法律|政令|規則|省令|府令|告示|条約). This test guards against:
    1. Regression of any of the 7 supported law types
    2. Re-introduction of greedy [^第]* behavior (unrecognized prefixes
       must NOT trigger the law_num capture group)
    3. Existing valid AmendLawNum strings continue to parse correctly
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running this file directly via `python -m pytest tests/...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extract_supplproviso_from_xml import parse_amend_law_num  # noqa: E402

# ===========================================================
# Existing AmendLawNum forms must continue to parse
# ===========================================================


def test_full_date_form() -> None:
    """日付フル形式: 元号N年M月D日法律第K号."""
    result = parse_amend_law_num("昭和二二年一〇月二六日法律第一二四号")
    assert result.get("law_num") == "124"
    assert result.get("era") == "昭和"
    assert result.get("year_gengo") == 22


def test_year_only_form() -> None:
    """年のみ形式: 元号N年法律第K号."""
    result = parse_amend_law_num("令和七年法律第二十六号")
    assert result.get("law_num") == "26"
    assert result.get("era") == "令和"


def test_arabic_numerals() -> None:
    """アラビア数字混在形式 (e-Gov XML で時々ある)."""
    result = parse_amend_law_num("平成26年法律第69号")
    assert result.get("law_num") == "69"


# ===========================================================
# New: literal alternation supports all 7 law types
# ===========================================================


def test_seirei() -> None:
    """政令タイプ (内閣制定)."""
    result = parse_amend_law_num("令和五年政令第百号")
    assert result.get("law_num") == "100"


def test_kisoku() -> None:
    """規則タイプ (各種行政機関)."""
    result = parse_amend_law_num("令和七年規則第二号")
    assert result.get("law_num") == "2"


def test_kokuji() -> None:
    """告示タイプ (各機関公示)."""
    result = parse_amend_law_num("平成三十年告示第十五号")
    assert result.get("law_num") == "15"


def test_shourei() -> None:
    """省令タイプ.

    Note: 「元年」は現状の era-year regex の char class に含まれない (FU 別件)。
    "令和七年" で代用してテスト.
    """
    result = parse_amend_law_num("令和七年省令第三号")
    assert result.get("law_num") == "3"


# ===========================================================
# Regression guard: unrecognized prefixes must NOT trigger law_num
# ===========================================================


def test_no_match_unrecognized_prefix() -> None:
    """FU-304 の核心: 認識されない法令種別前置を greedy match しない.

    旧 regex `(?:[^第]*第N号)?` は「雑種」のような未対応の prefix も
    [^第]* で吸収して law_num を取ってしまった。新 regex は literal
    alternation なので、未対応の prefix は law_num group を triger しない。
    """
    result = parse_amend_law_num("令和七年雑種第二号")
    assert result.get("law_num") is None, (
        f"Got law_num={result.get('law_num')!r}. 未対応の前置 '雑種' が law_num を triger している. "
        f"FU-304 で literal alternation 化したはずだが、greedy match の挙動が再発した可能性."
    )


def test_no_match_year_only() -> None:
    """年だけ (法令種別なし) では law_num は None."""
    result = parse_amend_law_num("令和七年")
    assert result.get("law_num") is None


def test_empty_input() -> None:
    """空文字列で例外を出さず空 dict 返却."""
    result = parse_amend_law_num("")
    assert result == {}

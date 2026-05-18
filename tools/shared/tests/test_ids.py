"""ID 規約のテスト."""

from datetime import date

import pytest

from juricode_shared.ids import (
    make_article_id,
    make_case_id,
    validate_article_id,
)


# ---- make_article_id ----


def test_make_article_id_basic() -> None:
    assert make_article_id("keihou", "36") == "keihou-art-36"


def test_make_article_id_with_branch() -> None:
    assert make_article_id("keihou", "36-2") == "keihou-art-36-2"


def test_make_article_id_long_abbrev() -> None:
    assert make_article_id("keiji-soshou-hou", "203") == "keiji-soshou-hou-art-203"


def test_make_article_id_rejects_uppercase() -> None:
    with pytest.raises(ValueError, match="law_abbrev"):
        make_article_id("Keihou", "36")


def test_make_article_id_rejects_invalid_number() -> None:
    with pytest.raises(ValueError, match="article_number"):
        make_article_id("keihou", "三十六")


# ---- validate_article_id ----


def test_validate_article_id_accepts_valid() -> None:
    assert validate_article_id("keihou-art-36") is True
    assert validate_article_id("keiji-soshou-hou-art-203") is True
    assert validate_article_id("kenpou-art-9") is True
    assert validate_article_id("keihou-art-36-2") is True


def test_validate_article_id_rejects_invalid() -> None:
    assert validate_article_id("Keihou-art-36") is False
    assert validate_article_id("keihou_art_36") is False
    assert validate_article_id("keihou-art-") is False
    assert validate_article_id("36") is False


# ---- make_case_id ----


def test_make_case_id_supreme_court() -> None:
    case_id = make_case_id("scj-pb1", date(1969, 12, 4), "keishu-23-12-1573")
    assert case_id == "scj-pb1-1969-12-04-keishu-23-12-1573"


def test_make_case_id_high_court() -> None:
    case_id = make_case_id("oh", date(2010, 3, 25), "hanji-2080-65")
    assert case_id == "oh-2010-03-25-hanji-2080-65"

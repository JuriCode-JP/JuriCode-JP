"""Tests for anonymize.normalize (Phase D).

Why this test exists:
    Pins the placeholder rules: era+year -> [ERA][N]年, legal identifiers
    (第N条/項/号) preserved (data moat value), all other digit runs -> [N], and that
    placeholders never contain HTML-tag chars.
"""

from __future__ import annotations

from juricode_shared.anonymize.normalize import anonymize_text


def test_era_year() -> None:
    assert anonymize_text("令和3年に施行") == "[ERA][N]年に施行"


def test_era_year_with_space() -> None:
    assert anonymize_text("平成 26 年") == "[ERA][N]年"


def test_article_preserved() -> None:
    assert anonymize_text("刑法第36条") == "刑法第36条"


def test_paragraph_item_preserved() -> None:
    assert anonymize_text("第3項 と 第2号") == "第3項 と 第2号"


def test_age_to_placeholder() -> None:
    assert anonymize_text("20歳の学生") == "[N]歳の学生"


def test_amount_to_placeholder() -> None:
    assert anonymize_text("1000万円の損害") == "[N]万円の損害"


def test_mixed_preserve_and_strip() -> None:
    assert anonymize_text("第36条で20歳") == "第36条で[N]歳"


def test_plain_date_digits_stripped() -> None:
    assert anonymize_text("2026年5月30日") == "[N]年[N]月[N]日"


def test_no_digits_unchanged() -> None:
    assert anonymize_text("正当防衛の要件") == "正当防衛の要件"


def test_placeholder_has_no_html_tag_chars() -> None:
    out = anonymize_text("令和3年 第36条 20歳")
    assert "<" not in out and ">" not in out

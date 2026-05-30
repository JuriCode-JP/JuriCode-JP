"""Tests for anonymize.pii_filter (Phase D).

Why this test exists:
    Pins Tier 1 PII detection: each pattern fires on a positive, stays quiet on a
    negative, returns the matched label list (V2-3), handles multiple matches, and
    (BOUND fix) does not false-positive on long digit runs or legal article numbers.
"""

from __future__ import annotations

from juricode_shared.anonymize.pii_filter import detect_pii


def test_email() -> None:
    d, m = detect_pii("連絡先は taro@example.co.jp です")
    assert d and "email" in m


def test_phone_jp() -> None:
    d, m = detect_pii("090-1234-5678 にかけて")
    assert d and "phone_jp" in m


def test_postal_jp() -> None:
    d, m = detect_pii("郵便番号 123-4567 の地域")
    assert d and "postal_jp" in m


def test_credit_card() -> None:
    d, m = detect_pii("カード 4111 1111 1111 1111 を使った")
    assert d and "credit_card" in m


def test_my_number_jp() -> None:
    d, m = detect_pii("マイナンバー 1234 5678 9012 です")
    assert d and "my_number_jp" in m


def test_url_with_query() -> None:
    d, m = detect_pii("https://example.com/p?id=abc を参照")
    assert d and "url_with_query" in m


def test_clean_legal_question_no_pii() -> None:
    d, m = detect_pii("正当防衛が成立する要件は何ですか")
    assert not d and m == []


def test_article_number_not_pii() -> None:
    d, m = detect_pii("刑法 第36条 と 第709条 について")
    assert not d, f"article numbers must not be PII, got {m}"


def test_case_number_not_pii() -> None:
    d, m = detect_pii("最判昭和38年12月24日 の判旨")
    assert not d, f"case citation must not be PII, got {m}"


def test_multiple_patterns_sorted() -> None:
    d, m = detect_pii("a@b.co と 090-1234-5678")
    assert d
    assert "email" in m and "phone_jp" in m
    assert m == sorted(m)  # deterministic order


def test_postal_no_false_positive_inside_long_digits() -> None:
    # BOUND: 567-8901 inside a longer number must not register as postal
    d, m = detect_pii("法人番号 1234567-890123 の件")
    assert "postal_jp" not in m


def test_phone_no_false_positive_inside_long_digits() -> None:
    d, m = detect_pii("口座 12309012345678 の件")
    assert "phone_jp" not in m

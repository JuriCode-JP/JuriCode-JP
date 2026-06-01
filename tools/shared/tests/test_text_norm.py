"""test_text_norm -- juricode_shared.text_norm の unit tests (FU-513).

責務:
  1. golden: 全角数字変換 / 空白畳み込み / BOM 除去 / canonical_search_text 冪等性.
  2. 漢数字 round-trip: kanji_to_int(int_to_kanji(n)) == n (n=1..9999 サンプル).
  3. 条番号変換: arabic/kanji_version_of_article_numbers の既存挙動.
  4. 異常系: 不正漢数字 / 空文字 / 記号 で None / 元文字列を返す挙動を固定.

Why 改行は明示エスケープ (\\r\\n / \\n) で記述するか (ガードレール §8):
  .gitattributes で `*.py text eol=lf` が設定済だが、テストファイル内の
  マルチライン文字列リテラルが CRLF 化するリスクを防御多重化として排除する.
"""

from __future__ import annotations

from juricode_shared.text_norm import (
    KANJI_DIGIT,
    arabic_version_of_article_numbers,
    canonical_search_text,
    int_to_kanji,
    kanji_to_int,
    kanji_version_of_article_numbers,
    normalize_fullwidth_digits,
)


# =========================================================================
# normalize_fullwidth_digits
# =========================================================================


class TestNormalizeFullwidthDigits:
    def test_all_fullwidth(self):
        assert normalize_fullwidth_digits("０１２３４５６７８９") == "0123456789"

    def test_mixed(self):
        assert normalize_fullwidth_digits("第２３４条") == "第234条"

    def test_no_change(self):
        assert normalize_fullwidth_digits("abc123") == "abc123"

    def test_empty(self):
        assert normalize_fullwidth_digits("") == ""

    def test_kanji_digits_unchanged(self):
        # 漢数字は変換しない
        assert normalize_fullwidth_digits("三百") == "三百"


# =========================================================================
# kanji_to_int
# =========================================================================


class TestKanjiToInt:
    def test_simple(self):
        assert kanji_to_int("一") == 1
        assert kanji_to_int("九") == 9

    def test_ten(self):
        assert kanji_to_int("十") == 10
        assert kanji_to_int("二十") == 20
        assert kanji_to_int("十三") == 13

    def test_hundred(self):
        assert kanji_to_int("百") == 100
        assert kanji_to_int("百二十三") == 123
        assert kanji_to_int("二百") == 200

    def test_thousand(self):
        assert kanji_to_int("千") == 1000
        assert kanji_to_int("千二百三十四") == 1234
        assert kanji_to_int("二千") == 2000

    def test_complex(self):
        assert kanji_to_int("九千九百九十九") == 9999

    def test_empty_returns_none(self):
        assert kanji_to_int("") is None

    def test_non_kanji_returns_none(self):
        # 漢数字でない文字だけからなる文字列: total=0 -> None
        assert kanji_to_int("abc") is None

    def test_zero_char(self):
        # "〇" は KANJI_DIGIT に含まれるが値 0; current=0 のまま -> total=0 -> None
        assert kanji_to_int("〇") is None

    def test_symbols_returns_none(self):
        assert kanji_to_int("@#$") is None


# =========================================================================
# int_to_kanji
# =========================================================================


class TestIntToKanji:
    def test_zero(self):
        assert int_to_kanji(0) == "〇"

    def test_single_digit(self):
        assert int_to_kanji(1) == "一"
        assert int_to_kanji(9) == "九"

    def test_ten(self):
        assert int_to_kanji(10) == "十"
        assert int_to_kanji(11) == "十一"
        assert int_to_kanji(20) == "二十"

    def test_hundred(self):
        assert int_to_kanji(100) == "百"
        assert int_to_kanji(123) == "百二十三"
        assert int_to_kanji(200) == "二百"

    def test_thousand(self):
        assert int_to_kanji(1000) == "千"
        assert int_to_kanji(1234) == "千二百三十四"
        assert int_to_kanji(2000) == "二千"

    def test_max(self):
        assert int_to_kanji(9999) == "九千九百九十九"

    def test_round_trip_samples(self):
        # kanji_to_int(int_to_kanji(n)) == n for sampled values
        samples = list(range(1, 51)) + list(range(100, 120)) + list(range(999, 1010)) + [9999]
        for n in samples:
            assert kanji_to_int(int_to_kanji(n)) == n, f"round-trip failed for n={n}"


# =========================================================================
# arabic_version_of_article_numbers
# =========================================================================


class TestArabicVersionOfArticleNumbers:
    def test_simple(self):
        assert arabic_version_of_article_numbers("第三条") == "第3条"

    def test_with_sub(self):
        assert arabic_version_of_article_numbers("第三条の二") == "第3条の2"

    def test_hundred(self):
        assert arabic_version_of_article_numbers("第百二十三条") == "第123条"

    def test_no_match(self):
        # アラビア数字の条番号はそのまま返す
        assert arabic_version_of_article_numbers("第3条") == "第3条"

    def test_empty(self):
        assert arabic_version_of_article_numbers("") == ""

    def test_invalid_kanji_in_pattern_returns_original(self):
        # 漢数字パターンに一致しない文字を混ぜた場合はそのまま返す
        text = "第abc条"
        assert arabic_version_of_article_numbers(text) == text

    def test_mixed_text(self):
        result = arabic_version_of_article_numbers("刑法第三十六条は正当防衛について規定する")
        assert result == "刑法第36条は正当防衛について規定する"


# =========================================================================
# kanji_version_of_article_numbers
# =========================================================================


class TestKanjiVersionOfArticleNumbers:
    def test_simple(self):
        assert kanji_version_of_article_numbers("第3条") == "第三条"

    def test_with_sub(self):
        assert kanji_version_of_article_numbers("第3条の2") == "第三条の二"

    def test_hundred(self):
        assert kanji_version_of_article_numbers("第123条") == "第百二十三条"

    def test_no_match(self):
        # 漢数字の条番号はそのまま返す
        assert kanji_version_of_article_numbers("第三条") == "第三条"

    def test_empty(self):
        assert kanji_version_of_article_numbers("") == ""

    def test_mixed_text(self):
        result = kanji_version_of_article_numbers("刑法第36条は正当防衛について規定する")
        assert result == "刑法第三十六条は正当防衛について規定する"


# =========================================================================
# canonical_search_text
# =========================================================================


class TestCanonicalSearchText:
    def test_fullwidth_digits(self):
        assert canonical_search_text("第２３４条") == "第234条"

    def test_bom_removal(self):
        # BOM (U+FEFF) を先頭に持つ文字列
        assert canonical_search_text("\ufeff第1条") == "第1条"

    def test_crlf_to_lf_then_collapsed(self):
        # 明示エスケープ (ガードレール §8)
        text = "第1条\r\n第2条"
        # CRLF -> LF -> スペース畳み込み
        result = canonical_search_text(text)
        assert result.replace("\r", "") == "第1条 第2条"

    def test_cr_to_lf_then_collapsed(self):
        text = "第1条\r第2条"
        result = canonical_search_text(text)
        assert result == "第1条 第2条"

    def test_whitespace_collapse_tab(self):
        assert canonical_search_text("第1条\t第2条") == "第1条 第2条"

    def test_whitespace_collapse_fullwidth(self):
        # 全角スペース (U+3000)
        assert canonical_search_text("第1条　第2条") == "第1条 第2条"

    def test_whitespace_collapse_multiple(self):
        assert canonical_search_text("第1条   第2条") == "第1条 第2条"

    def test_strip(self):
        assert canonical_search_text("  第1条  ") == "第1条"

    def test_empty(self):
        assert canonical_search_text("") == ""

    def test_only_whitespace(self):
        assert canonical_search_text("   \t\n　") == ""

    def test_idempotent(self):
        # 2 回適用 = 1 回 (冪等性)
        text = "\ufeff第２３４条　の\t規定"
        once = canonical_search_text(text)
        twice = canonical_search_text(once)
        assert once == twice

    def test_no_nfkc(self):
        # NFKC を適用しないので漢字等は変換しない
        text = "第1条"
        assert canonical_search_text(text) == "第1条"

    def test_symbols_unchanged(self):
        # 記号はそのまま残る
        text = "第1条（正当防衛）"
        assert canonical_search_text(text) == "第1条（正当防衛）"


# =========================================================================
# KANJI_DIGIT 定数
# =========================================================================


class TestKanjiDigitConstant:
    def test_all_keys_present(self):
        expected_keys = {"〇", "一", "二", "三", "四", "五", "六", "七", "八", "九"}
        assert set(KANJI_DIGIT.keys()) == expected_keys

    def test_values(self):
        assert KANJI_DIGIT["〇"] == 0
        assert KANJI_DIGIT["九"] == 9


# =========================================================================
# 等価テスト: normalize_legal_query の出力がバイト一致 (Phase 2 リファクタ無害証明)
# =========================================================================


class TestNormalizeLegalQueryEquivalence:
    """retrieve.py から juricode_shared.text_norm への import 置換後、
    normalize_legal_query 出力が移送前 golden と完全一致することを確認する.

    Golden 値は Phase 2 実装前に retrieve.py の元関数で実測した結果.
    """

    GOLDEN = [
        ("刑法第36条正当防衛", "刑法第36条正当防衛 刑法第三十六条正当防衛"),
        ("第三十六条の規定", "第三十六条の規定 第36条の規定"),
        ("警察官職務執行法第２条", "警察官職務執行法第2条 警察官職務執行法第二条"),
        ("行政手続法の不利益処分", "行政手続法の不利益処分"),
        ("地公法第３条", "地公法第3条 地公法第三条 地方公務員法"),
        ("個保法の開示請求", "個保法の開示請求 個人情報保護法"),
        ("薬機法第14条の承認", "薬機法第14条の承認 薬機法第十四条の承認 医薬品医療機器等法"),
        ("", ""),
        ("記号のみ！？", "記号のみ！？"),
        ("第百二十三条", "第百二十三条 第123条"),
    ]

    def test_golden_equivalence(self):
        import sys

        sys.path.insert(0, "tools/embed")
        from retrieve import normalize_legal_query

        for query, expected in self.GOLDEN:
            result = normalize_legal_query(query)
            assert result == expected, (
                f"normalize_legal_query({query!r}) = {result!r}, expected {expected!r}"
            )

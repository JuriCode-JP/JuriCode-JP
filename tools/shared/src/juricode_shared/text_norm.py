"""text_norm -- 検索側テキスト正規化の純関数群 (FU-513).

移送元: tools/embed/retrieve.py
責務: 漢数字/全角数字/条番号変換 + canonical_search_text を提供する純関数のみ.
     I/O・辞書系 (LAW_ABBREV_EXPANSIONS) は retrieve.py に残す.

Why この module が必要か (FU-513):
    retrieve.py に散在していた正規化ロジックを juricode_shared に集約することで
    将来の再埋め込み FU (Option B 系) や parser 経路 (D2 defer / FU-405) が
    同一実装を参照できるようにする. Phase 1 は純移送のみ; corpus text・*.npy は
    一切変更しない (成功条件 = manifest hash 不変 / R@3=72.7% 不変).

Why NFKC 全適用しないか (canonical_search_text):
    数字と空白に限定することで corpus の漢字・仮名・記号への副作用を排除.
    広すぎる NFKC 正規化 (例: ㍉ -> ミリ) は将来の再埋め込み FU に委ねる.

Why canonical_search_text は Phase 2 でトークナイザに配線しないか:
    BM25 ablation の等価性担保のため. 実配線は将来の再埋め込み FU で行う.
"""

from __future__ import annotations

import re

KANJI_DIGIT: dict[str, int] = {
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def normalize_fullwidth_digits(s: str) -> str:
    """全角数字を半角数字に変換する (０-９ -> 0-9)."""
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def kanji_to_int(s: str) -> int | None:
    """漢数字 -> 整数. 「百二十三」 -> 123.

    空文字列・変換不能な場合は None を返す (retrieve.py の既存挙動を完全再現).
    """
    if not s:
        return None
    total = 0
    current = 0
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    for ch in s:
        if ch in KANJI_DIGIT:
            current = current * 10 + KANJI_DIGIT[ch] if current else KANJI_DIGIT[ch]
        elif ch in unit_map:
            unit = unit_map[ch]
            current = current if current else 1
            total += current * unit
            current = 0
    total += current
    return total if total > 0 else None


def int_to_kanji(n: int) -> str:
    """整数 -> 漢数字 (0-9999).

    retrieve.py::_kanji_version_of_article_numbers 内の inner 関数を top-level に昇格.
    出力は逐語等価 (1 ビットも変えない).
    """
    if n == 0:
        return "〇"
    digits = "〇一二三四五六七八九"
    result = ""
    if n >= 1000:
        d = n // 1000
        result += (digits[d] if d > 1 else "") + "千"
        n %= 1000
    if n >= 100:
        d = n // 100
        result += (digits[d] if d > 1 else "") + "百"
        n %= 100
    if n >= 10:
        d = n // 10
        result += (digits[d] if d > 1 else "") + "十"
        n %= 10
    if n > 0:
        result += digits[n]
    return result


def arabic_version_of_article_numbers(text: str) -> str:
    """漢数字の条番号をアラビア数字に変換した版を生成 (置換せず別バージョン).

    retrieve.py::_arabic_version_of_article_numbers の逐語移送.
    """

    def repl(m: re.Match[str]) -> str:
        main_kanji = m.group(1)
        sub_kanji = m.group(2)
        main_num = kanji_to_int(main_kanji)
        if main_num is None:
            return m.group(0)
        if sub_kanji:
            sub_num = kanji_to_int(sub_kanji)
            if sub_num is not None:
                return f"第{main_num}条の{sub_num}"
        return f"第{main_num}条"

    pattern = r"第([〇一二三四五六七八九十百千万]+)条(?:の([〇一二三四五六七八九十百千万]+))?"
    return re.sub(pattern, repl, text)


def kanji_version_of_article_numbers(text: str) -> str:
    """アラビア数字の条番号を漢数字に変換した版を生成 (corpus body マッチ用).

    retrieve.py::_kanji_version_of_article_numbers の逐語移送 (inner int_to_kanji を
    top-level 関数として参照する形に統合).
    """

    def repl(m: re.Match[str]) -> str:
        main_num = int(m.group(1))
        sub_str = m.group(2)
        result = f"第{int_to_kanji(main_num)}条"
        if sub_str:
            sub_num = int(sub_str)
            result += f"の{int_to_kanji(sub_num)}"
        return result

    pattern = r"第(\d+)条(?:の(\d+))?"
    return re.sub(pattern, repl, text)


def canonical_search_text(text: str) -> str:
    """検索側テキストの正準形を返す純関数 (FU-513 本体).

    順序固定:
    1. BOM 除去 (U+FEFF).
    2. 改行統一: \\r\\n / \\r -> \\n.
    3. 全角数字 -> 半角 (normalize_fullwidth_digits).
    4. 空白畳み込み: 連続する空白類 (半角空白/タブ/改行/全角空白 U+3000) を半角空白 1 個に.
    5. 前後 strip.

    注意: Phase 2 では既存の _tokenize_chargram には配線しない (BM25 ablation 等価性担保).
         将来の再埋め込み FU で実適用する.
    """
    # 1. BOM 除去
    if text.startswith("\ufeff"):
        text = text[1:]
    # 2. 改行統一
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 3. 全角数字 -> 半角
    text = normalize_fullwidth_digits(text)
    # 4. 空白畳み込み (半角空白 / タブ / 改行 / 全角空白 U+3000)
    text = re.sub(r"[ \t\n　]+", " ", text)
    # 5. strip
    return text.strip()


__all__ = [
    "KANJI_DIGIT",
    "normalize_fullwidth_digits",
    "kanji_to_int",
    "int_to_kanji",
    "arabic_version_of_article_numbers",
    "kanji_version_of_article_numbers",
    "canonical_search_text",
]

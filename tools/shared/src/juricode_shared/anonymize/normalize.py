"""Tier 1 anonymization (numeric / era placeholdering) for the question log.

Why: PII 検出時に raw を捨て匿名化版のみ残すため, および非 PII 行の anonymized 後追い
fill のため. NER (人名/住所) は Tier 2 (FU). 条文識別子 (第N条/項/号) は中核の法的
シグナルで PII ではないため保持し, それ以外の数字のみ placeholder 化する (data moat の質)。

placeholder は [N]/[ERA] の角括弧のみ。`<`/`>` は HTML タグ誤認になるため使わない
(表示時は別途 escHtml を通す, defense in depth)。
"""

from __future__ import annotations

import re
from typing import Final

# 左優先 alternation: era+year | article-id (preserve) | bare digits。
_TOKEN: Final[re.Pattern[str]] = re.compile(
    r"(?P<era>(?:令和|平成|昭和|大正|明治)\s*\d+\s*年)"
    r"|(?P<art>第\d+(?:条|項|号))"
    r"|(?P<num>\d+)"
)


def _repl(m: re.Match[str]) -> str:
    if m.group("era") is not None:
        return "[ERA][N]年"
    if m.group("art") is not None:
        return m.group("art")  # preserve legal identifier (not PII)
    return "[N]"


def anonymize_text(text: str) -> str:
    """Return a placeholdered copy.

    era+year -> [ERA][N]年, 第N条/項/号 は保持, その他の数字列 -> [N].
    """
    return _TOKEN.sub(_repl, text)

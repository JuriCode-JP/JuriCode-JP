"""Tier 1 PII detection (regex based) for the question log.

Why: UI 公開前に PII を機械的に捕捉し, 検出時は raw を保存しない防御層を作る. マッチした
パターン名を返すことで (V2-3), 後で false positive を集計しチューニングできる. 人名/住所/
固有事案名は Tier 2 (Claude API, FU-P0-4 弁護士レビュー後) で扱う (本 sprint 外).
"""

from __future__ import annotations

import re
from typing import Final

# briefing 4.4 の 6 種。phone_jp/postal_jp は数字境界 (?<!\d)...(?!\d) を付与し,
# 長い数字列内部への誤検知を消す (本物の単独 postal/phone はマッチ維持、実測確認済)。
PATTERNS: Final[dict[str, str]] = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "phone_jp": r"(?<!\d)0\d{1,4}[-(\s]?\d{1,4}[-)\s]?\d{3,4}(?!\d)",
    "postal_jp": r"(?<!\d)\d{3}-\d{4}(?!\d)",
    "credit_card": r"\b(?:\d[ -]*?){13,19}\b",
    "my_number_jp": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
    "url_with_query": r"https?://[^\s]+\?[^\s]+",
}

_COMPILED: Final[dict[str, re.Pattern[str]]] = {
    name: re.compile(rx) for name, rx in PATTERNS.items()
}


def detect_pii(text: str) -> tuple[bool, list[str]]:
    """Return (detected, matched_pattern_names).

    Why (V2-3): matched names を sorted (決定的) で返し, raw 破棄前に csv で記録できる
    ようにする. 空 list は detected=False.
    """
    matched = sorted(name for name, rx in _COMPILED.items() if rx.search(text))
    return (bool(matched), matched)

"""Canonical text normalization for hash verification.

parse-egov.py と verify.py の両方で同じ正規化処理を使うため共有モジュール化.
2 箇所に分けると drift して、同じ条文を別ハッシュとして扱う事故が起きうる.

正規化ルール:
  1. CRLF / CR を LF に統一
  2. 全角空白 (U+3000) を半角空白に変換
  3. 各行の末尾 whitespace を strip
  4. 連続した空行 (3 行以上) を 2 行に圧縮 (= 段落間の最大 1 つの空行)
  5. 前後の whitespace を strip
"""

from __future__ import annotations

import hashlib
import re


_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_MULTI_BLANK = re.compile(r"\n{3,}")


def canonicalize(text: str) -> str:
    """Return the canonical form of `text` for hashing/equality checks."""
    if text is None:
        return ""
    # 1. Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 2. Full-width space → half-width space
    text = text.replace("　", " ")
    # 3. Strip trailing whitespace on each line
    text = _TRAILING_WS.sub("", text)
    # 4. Collapse 3+ blank lines to 2 (= 1 empty line)
    text = _MULTI_BLANK.sub("\n\n", text)
    # 5. Strip leading/trailing whitespace
    return text.strip()


def sha256_of(text: str) -> str:
    """SHA-256 hex digest of the canonicalized text."""
    canon = canonicalize(text)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()

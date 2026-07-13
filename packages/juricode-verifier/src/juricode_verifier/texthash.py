"""Text-hash verification: prove a text matches its manifest sha256 (source fidelity).

Why: corpus 本文が一次ソース (e-Gov XML) から改変されていないことの証明は、manifest に
ロックされた sha256 との照合で機械化できる。本モジュールはその照合の純関数だけを提供する。

境界 (重要): canonicalize は本モジュールに持ち込まない。manifest の期待値は canonicalize
済みテキストの sha256 なので、呼び出し側が canonicalize 済みテキストを渡すこと。何を
canonicalize と定義するかはデータパイプライン側の責務であり、本関数は「渡された文字列を
UTF-8 で hash した値が期待値と一致するか」だけを検査する。
"""

from __future__ import annotations

import hashlib
import re

from .violation import Violation

#: sha256 hex digest の形 (64 桁の小文字 hex)。大文字は正規化して受ける。
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def verify_text_hash(canonical_text: str, expected_sha256: str) -> Violation | None:
    """canonical_text の sha256 (UTF-8) が expected_sha256 と一致するか検査。一致なら None.

    Why: 出典検証の鎖の最終環。quote が chunk 本文の逐語部分文字列で (G2)、chunk が渡した
    hits に在り (G1)、さらにその本文の元テキストが manifest のロック値と一致する (本検査)
    ことで、引用が一次ソース由来であることを機械的に示せる。

    期待値が sha256 hex digest の形をしていない場合も HASH 違反として返す
    (黙って比較して常に不一致にするより、原因が分かる detail を出す)。
    """
    expected = (expected_sha256 or "").strip().lower()
    if not _SHA256_HEX_RE.fullmatch(expected):
        return Violation(
            "HASH", f"malformed expected sha256 (need 64 hex chars): {expected_sha256!r}"
        )
    actual = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    if actual != expected:
        return Violation("HASH", f"sha256 mismatch: expected {expected}, got {actual}")
    return None

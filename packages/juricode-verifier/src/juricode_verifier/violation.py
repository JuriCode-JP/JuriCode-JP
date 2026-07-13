"""Violation: the single result type shared by every verification check.

Why a single type: verification results from the core checks (citation existence,
verbatim quotes, text hash) and from any caller-side policy checks must be
aggregatable into one list. Keeping the type in ONE place (this package) prevents
the drift that duplicate definitions would inevitably produce.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    """One verification failure. `code` identifies the check, `detail` is human-readable evidence.

    Codes emitted by this package:
        G1   : citation chunk_id is not in the allowed (provided) set
        G2   : citation quote is not a verbatim byte substring of the source body
        HASH : text sha256 does not match the expected manifest value
    Callers may add their own codes for policy checks; they are outside this package.
    """

    code: str
    detail: str

"""juricode-verifier: domain-independent source-citation verification for legal RAG.

Scope (what this package verifies):
    - snap_quote            : locate an LLM anchor in the source body and cut the
                              verbatim quote from the ORIGINAL bytes (never the LLM's text)
    - check_citations_exist : every cited chunk_id is in the provided (allowed) set (G1)
    - check_quotes_verbatim : every quote is a verbatim byte substring of its source (G2)
    - valid_citations_only  : filter citations down to those passing G1+G2
    - verify_text_hash      : sha256 of a canonical text matches its locked manifest value

Out of scope (deliberately): answer correctness and application policy (assertion bans,
numeric-output bans, disclaimers, professional-practice notices). Those are the calling
application's responsibility; mixing them in would tie this package to one domain.
"""

from __future__ import annotations

from .citations import check_citations_exist, check_quotes_verbatim, valid_citations_only
from .snap import DEFAULT_MAX_LEN, snap_quote
from .texthash import verify_text_hash
from .violation import Violation

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_MAX_LEN",
    "Violation",
    "__version__",
    "check_citations_exist",
    "check_quotes_verbatim",
    "snap_quote",
    "valid_citations_only",
    "verify_text_hash",
]

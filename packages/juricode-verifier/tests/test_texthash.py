"""Unit tests for text-hash verification (juricode_verifier.texthash).

Covers: match / mismatch / empty text / malformed expected values, plus the
uppercase-hex normalization. The expected values mirror the manifest format used
by the corpus pipeline (sha256 hex digest of the canonicalized UTF-8 text).
"""

from __future__ import annotations

import hashlib

from juricode_verifier import verify_text_hash

TEXT = "第三十六条　急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。"
TEXT_SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()


def test_matching_hash_returns_none():
    assert verify_text_hash(TEXT, TEXT_SHA) is None


def test_mismatch_returns_hash_violation_with_both_digests():
    other = hashlib.sha256(b"altered").hexdigest()
    v = verify_text_hash(TEXT, other)
    assert v is not None
    assert v.code == "HASH"
    assert other in v.detail  # expected digest in evidence
    assert TEXT_SHA in v.detail  # actual digest in evidence


def test_empty_text_hashes_deterministically():
    empty_sha = hashlib.sha256(b"").hexdigest()
    assert verify_text_hash("", empty_sha) is None
    v = verify_text_hash("", TEXT_SHA)
    assert v is not None and v.code == "HASH"


def test_uppercase_and_padded_expected_is_normalized():
    assert verify_text_hash(TEXT, "  " + TEXT_SHA.upper() + "\n") is None


def test_malformed_expected_is_reported_not_silently_mismatched():
    for bad in ("", "zz", "0123", TEXT_SHA[:-1], TEXT_SHA + "0", "g" * 64, None):
        v = verify_text_hash(TEXT, bad)  # type: ignore[arg-type]
        assert v is not None
        assert v.code == "HASH"
        assert "malformed" in v.detail

"""Tests for qlog.schema (Phase A).

Why this test exists:
    Pins the strict-typing invariants (extra=forbid, frozen), the V2-1 dwell cap
    applied at construction time, UUID normalization, and UTC timestamp
    canonicalization so regressions cannot silently corrupt the question-log
    data moat. Covers normal / abnormal / edge cases per the Phase A plan.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from juricode_shared.qlog.schema import (
    ClickEntry,
    FeedbackEntry,
    QuestionLog,
    ResultEntry,
    apply_dwell_cap,
    normalize_utc_iso,
)

TS = "2026-05-30T11:45:00+00:00"


def uid() -> str:
    return str(uuid.uuid4())


def make_question(**kw) -> QuestionLog:
    base = {
        "id": uid(),
        "session_id": uid(),
        "asked_at": TS,
        "pii_detected": 0,
        "k": 10,
        "embedder": "tfidf",
        "corpus_version": "v0.2",
    }
    base.update(kw)
    return QuestionLog(**base)


def make_click(**kw) -> ClickEntry:
    base = {
        "id": uid(),
        "question_id": uid(),
        "clicked_at": TS,
        "rank": 1,
        "article_id": "keihou-art-36",
    }
    base.update(kw)
    return ClickEntry(**base)


# ---- normal ----
def test_t1_question_pii0() -> None:
    q = make_question()
    assert q.pii_detected == 0
    assert q.question_text is None


def test_t2_question_pii1() -> None:
    q = make_question(pii_detected=1, question_text=None, pii_pattern_matched="phone_jp")
    assert q.pii_pattern_matched == "phone_jp"


def test_t3_other_models_build() -> None:
    qid = uid()
    assert ResultEntry(rank=1, article_id="a", score=0.5).rank == 1
    assert FeedbackEntry(id=uid(), question_id=qid, given_at=TS, signal="good").signal == "good"
    assert make_click().rank == 1


# ---- abnormal ----
def test_t4_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        make_question(unexpected_field=1)


def test_t5_frozen() -> None:
    q = make_question()
    with pytest.raises((ValidationError, TypeError)):
        q.k = 99


def test_t6_signal_literal() -> None:
    with pytest.raises(ValidationError):
        FeedbackEntry(id=uid(), question_id=uid(), given_at=TS, signal="maybe")


def test_t7_negative_dwell_and_rank() -> None:
    with pytest.raises(ValidationError):
        make_click(dwell_seconds=-1.0)
    with pytest.raises(ValidationError):
        make_click(rank=0)


def test_t11_bad_asked_at() -> None:
    with pytest.raises(ValidationError):
        make_question(asked_at="not-a-date")


def test_t12_bad_id() -> None:
    with pytest.raises(ValidationError):
        make_question(id="xxx")


# ---- uuid normalization ----
def test_t18_uuid_normalized_lowercase() -> None:
    upper = "550E8400-E29B-41D4-A716-446655440000"
    q = make_question(id=upper)
    assert q.id == "550e8400-e29b-41d4-a716-446655440000"


def test_t19_invalid_uuid_rejected() -> None:
    with pytest.raises(ValidationError):
        FeedbackEntry(id=uid(), question_id="not-a-uuid", given_at=TS, signal="good")


# ---- apply_dwell_cap ----
def test_t13_cap_none() -> None:
    assert apply_dwell_cap(None) == (None, None)


def test_t14_cap_zero() -> None:
    assert apply_dwell_cap(0.0) == (0.0, None)


def test_t15_cap_boundary_exact() -> None:
    assert apply_dwell_cap(300.0) == (300.0, None)


def test_t16_cap_just_over() -> None:
    assert apply_dwell_cap(300.0001) == (300.0, 300.0001)


def test_t17_cap_large() -> None:
    assert apply_dwell_cap(500.0) == (300.0, 500.0)


# ---- dwell cap at construction ----
def test_t20_click_caps_at_construction() -> None:
    c = make_click(dwell_seconds=500.0)
    assert c.dwell_seconds == 300.0
    assert c.dwell_seconds_raw == 500.0


def test_t21_roundtrip_guard_preserves_raw() -> None:
    c = make_click(dwell_seconds=300.0, dwell_seconds_raw=500.0)
    assert c.dwell_seconds == 300.0
    assert c.dwell_seconds_raw == 500.0


# ---- utc normalization ----
def test_t22_offset_shifted_to_utc() -> None:
    assert normalize_utc_iso("2026-05-30T11:45:00+09:00") == "2026-05-30T02:45:00.000000+00:00"


def test_t23_z_suffix() -> None:
    assert normalize_utc_iso("2026-05-30T02:45:00Z") == "2026-05-30T02:45:00.000000+00:00"


def test_t24_naive_assumed_utc() -> None:
    assert normalize_utc_iso("2026-05-30T02:45:00") == "2026-05-30T02:45:00.000000+00:00"


def test_t25_invalid_raises() -> None:
    with pytest.raises(ValueError):
        normalize_utc_iso("not-a-date")


# ---- fixed-width / lexicographic ----
def test_t26_fixed_width_lexicographic() -> None:
    a = normalize_utc_iso("2026-05-30T11:45:00+00:00")
    b = normalize_utc_iso("2026-05-30T11:45:00.500000+00:00")
    c = normalize_utc_iso("2026-05-30T11:45:01+00:00")
    assert a.endswith(".000000+00:00")
    assert a < b < c


# ---- validator does not mutate caller dict ----
def test_t27_caller_dict_not_mutated() -> None:
    src = {
        "id": uid(),
        "question_id": uid(),
        "clicked_at": TS,
        "rank": 1,
        "article_id": "a",
        "dwell_seconds": 500.0,
    }
    ClickEntry.model_validate(src)  # passes src by reference; validator must copy
    assert src["dwell_seconds"] == 500.0
    assert "dwell_seconds_raw" not in src

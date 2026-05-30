"""Tests that pii_detected / pii_pattern_matched persist correctly (Phase D, V2-3).

Why this test exists:
    The data moat depends on raw being dropped when PII is detected, and on the
    matched pattern names surviving as a CSV so false positives can be tuned later.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from juricode_shared.qlog import store
from juricode_shared.qlog.schema import QuestionLog


def _q(**kw) -> QuestionLog:
    base = {
        "id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "asked_at": "2026-05-30T00:00:00+00:00",
        "pii_detected": 0,
        "k": 10,
        "embedder": "tfidf",
        "corpus_version": "v0.2",
    }
    base.update(kw)
    return QuestionLog(**base)


def test_pii_row_drops_raw_and_keeps_pattern_csv(tmp_path: Path) -> None:
    db = tmp_path / "l.db"
    store.init_db(db)
    q = _q(
        question_text=None,
        question_text_anonymized="[N] のこと",
        pii_detected=1,
        pii_pattern_matched="email,phone_jp",
    )
    store.record_question(db, q)
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT question_text, question_text_anonymized, pii_detected, pii_pattern_matched "
        "FROM questions"
    ).fetchone()
    con.close()
    assert row[0] is None  # raw not stored
    assert row[1] == "[N] のこと"
    assert row[2] == 1
    assert row[3].split(",") == ["email", "phone_jp"]  # CSV splits back to labels


def test_non_pii_row_keeps_raw_null_pattern(tmp_path: Path) -> None:
    db = tmp_path / "l.db"
    store.init_db(db)
    q = _q(question_text="正当防衛の要件", pii_detected=0)
    store.record_question(db, q)
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT question_text, pii_detected, pii_pattern_matched FROM questions"
    ).fetchone()
    con.close()
    assert row[0] == "正当防衛の要件"
    assert row[1] == 0
    assert row[2] is None

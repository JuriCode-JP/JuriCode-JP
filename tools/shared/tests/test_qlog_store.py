"""Tests for qlog.store (Phase A).

Why this test exists:
    Pins the SQLite CRUD contract: idempotent init, atomic writes, FK enforcement,
    V2-1 dwell persistence, V2-2 busy_timeout, WAL (with delete fallback), and the
    packaging / round-trip / mapping guards from the Phase A plan. Without these,
    silent data loss or lock-up in the question-log moat would go undetected.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from importlib.resources import files
from pathlib import Path

import pytest

from juricode_shared.qlog import store
from juricode_shared.qlog.schema import (
    ClickEntry,
    FeedbackEntry,
    QuestionLog,
    ResultEntry,
)

TS = "2026-05-30T11:45:00+00:00"


def uid() -> str:
    return str(uuid.uuid4())


def a_question(qid: str | None = None) -> QuestionLog:
    return QuestionLog(
        id=qid or uid(),
        session_id=uid(),
        asked_at=TS,
        pii_detected=0,
        k=10,
        embedder="tfidf",
        corpus_version="v0.2",
    )


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "logs.db"
    store.init_db(p)
    return p


# ---- normal ----
def test_s1_four_tables(db: Path) -> None:
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"questions", "results", "feedback", "clicks"} <= names


def test_s2_record_question_count(db: Path) -> None:
    store.record_question(db, a_question())
    assert store.count_questions(db) == 1


def test_s3_record_results(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    rows = [ResultEntry(rank=i, article_id=f"a{i}", score=0.1 * i) for i in (1, 2, 3)]
    store.record_results(db, q.id, rows)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 3
    con.close()


def test_s4_feedback_good_bad(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    for sig in ("good", "bad"):
        store.record_feedback(
            db, FeedbackEntry(id=uid(), question_id=q.id, given_at=TS, signal=sig)
        )
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 2
    con.close()


def test_s5_click_normal_raw_null(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    store.record_click(
        db,
        ClickEntry(
            id=uid(), question_id=q.id, clicked_at=TS, rank=1, article_id="a", dwell_seconds=30.0
        ),
    )
    con = sqlite3.connect(db)
    row = con.execute("SELECT dwell_seconds, dwell_seconds_raw FROM clicks").fetchone()
    con.close()
    assert row == (30.0, None)


def test_s6_click_capped(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    store.record_click(
        db,
        ClickEntry(
            id=uid(), question_id=q.id, clicked_at=TS, rank=1, article_id="a", dwell_seconds=500.0
        ),
    )
    con = sqlite3.connect(db)
    row = con.execute("SELECT dwell_seconds, dwell_seconds_raw FROM clicks").fetchone()
    con.close()
    assert row == (300.0, 500.0)


# ---- abnormal ----
def test_s7_fk_violation(db: Path) -> None:
    rows = [ResultEntry(rank=1, article_id="a", score=0.1)]
    with pytest.raises(sqlite3.IntegrityError):
        store.record_results(db, uid(), rows)  # question_id absent from questions -> FK


def test_s8_duplicate_pk_question(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    with pytest.raises(sqlite3.IntegrityError):
        store.record_question(db, q)


def test_s9_duplicate_result_pk(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    r = ResultEntry(rank=1, article_id="a", score=0.1)
    store.record_results(db, q.id, [r])
    with pytest.raises(sqlite3.IntegrityError):
        store.record_results(db, q.id, [r])


def test_s10_check_constraint_signal(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO feedback (id, question_id, given_at, signal) VALUES (?,?,?,?)",
            (uid(), q.id, TS, "maybe"),
        )
        con.commit()
    con.close()


# ---- edge / pragma ----
def test_s11_init_idempotent(db: Path) -> None:
    store.init_db(db)  # second call must not raise
    assert store.count_questions(db) == 0


def test_s12_busy_timeout(db: Path) -> None:
    con = store._connect(db)
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
    con.close()


def test_s13_journal_mode_wal_or_delete(db: Path) -> None:
    con = store._connect(db)
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()
    assert mode in ("wal", "delete")


def test_s14_foreign_keys_on(db: Path) -> None:
    con = store._connect(db)
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    con.close()


def test_s15_concurrent_writes(db: Path) -> None:
    n = 5
    errors: list[Exception] = []

    def worker() -> None:
        try:
            store.record_question(db, a_question())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert store.count_questions(db) == n


# ---- mapping / packaging / iso guards ----
def test_s16_not_null_columns_have_model_fields(db: Path) -> None:
    table_model = {
        "questions": QuestionLog,
        "results": ResultEntry,
        "feedback": FeedbackEntry,
        "clicks": ClickEntry,
    }
    # v5: results.question_id is supplied by the record_results param, not the model.
    caller_supplied = {"results": {"question_id"}}
    con = sqlite3.connect(db)
    for table, model in table_model.items():
        info = con.execute(f"PRAGMA table_info({table})").fetchall()
        not_null = {c[1] for c in info if c[3] == 1}
        fields = set(model.model_fields) | caller_supplied.get(table, set())
        missing = not_null - fields
        assert not missing, f"{table}: NOT NULL columns missing from {model.__name__}: {missing}"
    con.close()


def test_s17_none_text_roundtrip(db: Path) -> None:
    q = a_question(uid())
    store.record_question(db, q)
    con = sqlite3.connect(db)
    val = con.execute("SELECT question_text FROM questions WHERE id=?", (q.id,)).fetchone()[0]
    con.close()
    assert val is None


def test_s18_schema_loadable_via_resources() -> None:
    sql = files("juricode_shared.qlog").joinpath("schema.sql").read_text(encoding="utf-8")
    assert sql.count("CREATE TABLE") == 4


def test_s19_executemany_atomic_rollback(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    rows = [
        ResultEntry(rank=1, article_id="a", score=0.1),
        ResultEntry(rank=2, article_id="b", score=0.2),
        ResultEntry(rank=1, article_id="c", score=0.3),  # duplicate (question_id, rank) PK
    ]
    with pytest.raises(sqlite3.IntegrityError):
        store.record_results(db, q.id, rows)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
    con.close()


def test_s20_row_to_dict_reconstruct_preserves_raw(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    store.record_click(
        db,
        ClickEntry(
            id=uid(), question_id=q.id, clicked_at=TS, rank=1, article_id="a", dwell_seconds=500.0
        ),
    )
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM clicks").fetchone()
    con.close()
    rebuilt = ClickEntry.model_validate(dict(row))
    assert rebuilt.dwell_seconds == 300.0
    assert rebuilt.dwell_seconds_raw == 500.0


def test_s21_range_query_and_datetime_fn(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    con = sqlite3.connect(db)
    hit = con.execute(
        "SELECT id FROM questions WHERE asked_at >= ?", ("2000-01-01T00:00:00.000000+00:00",)
    ).fetchone()
    parsed = con.execute("SELECT datetime(asked_at) FROM questions").fetchone()[0]
    con.close()
    assert hit is not None
    assert parsed is not None


def test_s22_param_question_id_binds_all_rows(db: Path) -> None:
    q = a_question()
    store.record_question(db, q)
    r = ResultEntry(rank=1, article_id="a", score=0.1)
    store.record_results(db, q.id, [r])
    con = sqlite3.connect(db)
    stored_qid = con.execute("SELECT question_id FROM results").fetchone()[0]
    con.close()
    assert stored_qid == q.id  # param bound to row; ResultEntry carries no question_id
    assert "question_id" not in ResultEntry.model_fields  # non-destructive contract (v5)


def test_s23_question_with_results_atomic(db: Path) -> None:
    q = a_question()
    rows = [
        ResultEntry(rank=1, article_id="a", score=0.1),
        ResultEntry(rank=1, article_id="b", score=0.2),  # duplicate (question_id, rank) PK
    ]
    with pytest.raises(sqlite3.IntegrityError):
        store.record_question_with_results(db, q, rows)
    con = sqlite3.connect(db)
    assert (
        con.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
    )  # parent rolled back too
    assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
    con.close()


def test_s24_question_with_results_happy(db: Path) -> None:
    q = a_question()
    rows = [ResultEntry(rank=i, article_id=f"a{i}", score=0.1 * i) for i in (1, 2, 3)]
    store.record_question_with_results(db, q, rows)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 3
    con.close()

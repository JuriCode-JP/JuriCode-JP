"""qlog SQLite CRUD (Phase A).

Why: server.py から SQLite I/O を分離する. 接続設定 (WAL / busy_timeout / FK) を
_connect に局所化し, 全 record 関数が同じ設定で接続することを保証する. 書き込みは
closing + with conn パターンで原子性 (例外時 ROLLBACK / 成功時 COMMIT) と接続クローズを
担保する.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path

from juricode_shared.qlog.schema import (
    SQLITE_CONNECT_TIMEOUT,
    ClickEntry,
    FeedbackEntry,
    QuestionLog,
    ResultEntry,
)

_SCHEMA_SQL = files("juricode_shared.qlog").joinpath("schema.sql").read_text(encoding="utf-8")


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with WAL + busy_timeout + FK enforcement.

    Why: timeout / PRAGMA を 1 箇所に局所化し, 接続毎に明示 execute することで
    環境/接続初期化による設定消失リスクを排除する. busy_timeout は connect(timeout=)
    と二重で保証する.
    """
    conn = sqlite3.connect(db_path, timeout=SQLITE_CONNECT_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create tables idempotently (CREATE TABLE IF NOT EXISTS)."""
    with closing(_connect(db_path)) as conn, conn:
        conn.executescript(_SCHEMA_SQL)


def record_question(db_path: Path, log: QuestionLog) -> None:
    """Insert one question row."""
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO questions (id, session_id, asked_at, question_text, "
            "question_text_anonymized, pii_detected, pii_pattern_matched, k, embedder, "
            "corpus_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log.id,
                log.session_id,
                log.asked_at,
                log.question_text,
                log.question_text_anonymized,
                log.pii_detected,
                log.pii_pattern_matched,
                log.k,
                log.embedder,
                log.corpus_version,
            ),
        )


def record_results(db_path: Path, question_id: str, results: list[ResultEntry]) -> None:
    """Insert result rows atomically (executemany under one transaction)."""
    with closing(_connect(db_path)) as conn, conn:
        conn.executemany(
            "INSERT INTO results (question_id, rank, article_id, score) VALUES (?, ?, ?, ?)",
            [(question_id, r.rank, r.article_id, r.score) for r in results],
        )


def record_feedback(db_path: Path, fb: FeedbackEntry) -> None:
    """Insert one feedback row."""
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO feedback (id, question_id, given_at, signal, comment, "
            "comment_anonymized) VALUES (?, ?, ?, ?, ?, ?)",
            (fb.id, fb.question_id, fb.given_at, fb.signal, fb.comment, fb.comment_anonymized),
        )


def record_click(db_path: Path, click: ClickEntry) -> None:
    """Insert one click row.

    Why: cap は ClickEntry 生成時に完了済 (schema._cap_dwell). store は値をそのまま
    バインドするだけ -> memory==DB を保証する.
    """
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO clicks (id, question_id, clicked_at, rank, article_id, "
            "dwell_seconds, dwell_seconds_raw) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                click.id,
                click.question_id,
                click.clicked_at,
                click.rank,
                click.article_id,
                click.dwell_seconds,
                click.dwell_seconds_raw,
            ),
        )


def count_questions(db_path: Path) -> int:
    """Return the number of question rows (admin / health)."""
    with closing(_connect(db_path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]

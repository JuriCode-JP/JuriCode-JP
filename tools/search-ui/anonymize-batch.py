#!/usr/bin/env python3
"""Backfill anonymized columns in the question-log SQLite (Phase D).

Fills questions.question_text_anonymized and feedback.comment_anonymized for rows
where the anonymized column is NULL but the source text is present. Idempotent
(already-anonymized rows are skipped). Column-targeted UPDATE only (RACE-safe).

使い方:
    python tools/search-ui/anonymize-batch.py --db build/search-ui-logs.db --dry-run
    python tools/search-ui/anonymize-batch.py --db build/search-ui-logs.db --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _shared_src() -> Path:
    return Path(__file__).resolve().parent.parent / "shared" / "src"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill anonymized columns (Phase D).")
    parser.add_argument("--db", type=Path, required=True, help="search-ui-logs.db path")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="count only, no write")
    group.add_argument("--apply", action="store_true", help="write anonymized columns")
    args = parser.parse_args()

    # lazy imports (keep --help fast, no heavy top-level)
    import sqlite3

    sys.path.insert(0, str(_shared_src()))
    from juricode_shared.anonymize import anonymize_text

    if not args.db.exists():
        print(f"ERROR: db not found: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    try:
        q_rows = conn.execute(
            "SELECT id, question_text FROM questions "
            "WHERE question_text_anonymized IS NULL AND question_text IS NOT NULL"
        ).fetchall()
        f_rows = conn.execute(
            "SELECT id, comment FROM feedback "
            "WHERE comment_anonymized IS NULL AND comment IS NOT NULL"
        ).fetchall()
        print(f"questions to anonymize: {len(q_rows)}")
        print(f"feedback comments to anonymize: {len(f_rows)}")
        if not args.apply:
            print("(dry-run; no changes written)")
            return 0
        with conn:
            for rid, text in q_rows:
                conn.execute(
                    "UPDATE questions SET question_text_anonymized = ? WHERE id = ?",
                    (anonymize_text(text), rid),
                )
            for rid, text in f_rows:
                conn.execute(
                    "UPDATE feedback SET comment_anonymized = ? WHERE id = ?",
                    (anonymize_text(text), rid),
                )
        print(f"applied: {len(q_rows)} questions, {len(f_rows)} feedback")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

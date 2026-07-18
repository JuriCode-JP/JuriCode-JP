"""test_caselaw_decision_date_nonnull.py -- every case-law store row has a non-null decision_date (CI-safe).

Why (U-3 invariant lock): decision_date is 100% non-null across all committed case-law stores
(2203/2203 as of 2026-07-18). This locks that invariant so a future ingest that drops a
decision_date fails CI instead of silently shipping a gap. data/v0.2 is not gitignored so the
stores exist in CI (hermetic).
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CASE_LAW = _REPO_ROOT / "data" / "v0.2" / "case-law"


def _store_files() -> list[Path]:
    return sorted(_CASE_LAW.glob("*/rulings.jsonl")) + sorted(_CASE_LAW.glob("*/precedents.jsonl"))


def test_case_law_stores_present() -> None:
    # Vacuity guard: an empty glob would make the non-null assertion pass over zero rows.
    files = _store_files()
    assert len(files) >= 7, (
        f"expected >=7 case-law stores, found {len(files)}: {[str(f) for f in files]}"
    )


def test_decision_date_non_null_in_every_store() -> None:
    files = _store_files()
    assert files, "no case-law stores found"
    missing: list[tuple[str, str]] = []
    total = 0
    for f in files:
        rows = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert rows, f"empty store: {f}"
        for i, line in enumerate(rows):
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                missing.append(
                    (f.relative_to(_REPO_ROOT).as_posix(), f"row{i} (malformed JSON: {e})")
                )
                continue
            total += 1
            if d.get("decision_date") in (None, "", []):
                missing.append(
                    (f.relative_to(_REPO_ROOT).as_posix(), str(d.get("case_id", f"row{i}")))
                )
    assert not missing, f"{len(missing)} of {total} rows have null decision_date: {missing[:10]}"

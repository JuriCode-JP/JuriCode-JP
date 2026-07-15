"""test_g0_verdict.py -- the G0 gate's exit code must follow its findings.

Why: g0_fidelity_gate used to count violations, print them, and return 0
unconditionally, so "G0 is green" only ever meant the violations happened to be
zero. These tests pin the verdict layer added on top of the (unchanged) measurement:
the classification must cover every aggregate counter in both directions, a violation
makes the gate exit non-zero, a dropped law (skipped_no_xml) does too, and the
owner-classified diagnostic never does. All aggregates here are synthetic -- no
cache/laws XML -- so this runs in CI, where that 133 MB cache does not exist.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_V02_DIR = Path(__file__).resolve().parent.parent
if str(_V02_DIR) not in sys.path:
    sys.path.insert(0, str(_V02_DIR))

_spec = importlib.util.spec_from_file_location("g0_fidelity_gate", _V02_DIR / "g0_fidelity_gate.py")
g0 = importlib.util.module_from_spec(_spec)
sys.modules["g0_fidelity_gate"] = g0
_spec.loader.exec_module(g0)

CLS = g0.load_classification()


def _zero_agg() -> dict:
    """A complete all-zero aggregate with exactly the real 36 keys.

    aggregate([]) runs no reports, so it returns the initialized dict verbatim -- the
    ground truth for what keys exist, without hand-listing 36 names that could drift.
    """
    return g0.aggregate([])


def _exit_code(agg: dict, skipped: list[str]) -> int:
    total, _ = g0.count_violations(agg, skipped, CLS)
    return 1 if total >= 1 else 0


# --- classification covers aggregate() exactly, both directions ------------------


def test_classification_covers_aggregate_both_ways() -> None:
    agg = _zero_agg()
    g0.check_classification_covers_aggregate(agg, CLS)  # must not raise
    classified = set(CLS["violation"]) | set(CLS["diagnostic"]) | set(CLS["descriptor"])
    assert classified == set(agg)  # exact, no extras on either side
    assert len(CLS["violation"]) + len(CLS["diagnostic"]) + len(CLS["descriptor"]) == len(agg) == 36
    assert set(CLS["non_aggregate_violation"]).isdisjoint(agg)


def test_unclassified_aggregate_key_raises() -> None:
    agg = _zero_agg()
    agg["some_new_counter"] = 0  # a key nobody classified
    with pytest.raises(ValueError):
        g0.check_classification_covers_aggregate(agg, CLS)


def test_phantom_classified_key_raises() -> None:
    agg = _zero_agg()
    bad = json.loads(json.dumps(CLS))
    bad["violation"].append("not_a_real_aggregate_key")
    with pytest.raises(ValueError):
        g0.check_classification_covers_aggregate(agg, bad)


# --- exit follows the findings ---------------------------------------------------


def test_all_zero_aggregate_exits_zero() -> None:
    assert _exit_code(_zero_agg(), []) == 0


def test_one_numeric_violation_exits_one() -> None:
    agg = _zero_agg()
    agg["g0a_diff"] = 1
    total, breakdown = g0.count_violations(agg, [], CLS)
    assert total >= 1
    assert "g0a_diff" in breakdown
    assert _exit_code(agg, []) == 1


def test_list_violation_exits_one() -> None:
    agg = _zero_agg()
    agg["manifest_xml_sha_mismatch_laws"] = ["keihou"]  # non-empty list is a violation
    assert _exit_code(agg, []) == 1


def test_diagnostic_only_exits_zero() -> None:
    """paragraph_count_mismatch is a diagnostic by owner decision -> never fails."""
    agg = _zero_agg()
    agg["g0a_paragraph_count_mismatch"] = 1
    total, breakdown = g0.count_violations(agg, [], CLS)
    assert total == 0
    assert breakdown == {}
    assert _exit_code(agg, []) == 0


def test_skipped_no_xml_exits_one() -> None:
    agg = _zero_agg()
    total, breakdown = g0.count_violations(agg, ["somelaw (id)"], CLS)
    assert total >= 1
    assert "skipped_no_xml" in breakdown
    assert _exit_code(agg, ["somelaw (id)"]) == 1

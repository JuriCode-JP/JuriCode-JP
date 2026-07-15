"""Tests for the T6 pass/fail verdict (reproduce_a3._verdict).

Why:
    The verdict used to read honbun only, so a new-layer shortfall printed next to its
    target and never reached the exit code. These tests pin the fixed behaviour: a
    new-layer N or R@20 shortfall fails, a group mismatch in EITHER direction fails
    (unknown-group / unmeasured-target), an all-match run passes, and every failure
    reason names the check that failed -- so a red gate can never be silently tuned green.

CI note (deliberate skip):
    reproduce_a3.py imports numpy at module top, and CI's dev deps do not include numpy;
    importing the module in a CI-enumerated test fails collection (a real
    ModuleNotFoundError happened this way in a recent run). Every test guards with
    pytest.importorskip("numpy") BEFORE anything pulls reproduce_a3 in -- the same
    ordering test_harness_stamp_equals_the_anchor_digest uses -- so these skip cleanly in
    CI and run locally. That skip is a known gap, accepted here: making the numpy import
    lazy is the real fix but belongs to a separate change (doing it here would confound
    this one). tools/serve is not a package, so the module is loaded by file path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]


def _load_harness():
    """Load reproduce_a3 by file path, guarded so CI (no numpy) skips instead of erroring.

    Why the ordering matters: importorskip has to fire BEFORE the module is pulled in,
    or collection dies before the guard is reached. So the guard, the sys.path insertion,
    and the by-path load all live inside this function, and every test calls it first.
    """
    pytest.importorskip("numpy")
    import importlib.util

    serve = _REPO / "tools" / "serve"
    for p in (serve, _REPO / "tools" / "embed", _REPO / "tools" / "shared" / "src"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location("reproduce_a3", serve / "reproduce_a3.py")
    assert spec and spec.loader
    harness = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(harness)
    except Exception as exc:  # missing retrieval-stack deps locally -> not this test's job
        pytest.skip(f"harness dependencies unavailable: {exc}")
    return harness


def _good():
    """Measured == target on every check (the locked, green shape).

    _recall returns integer HIT COUNTS in recall (not ratios) and always includes "n"
    plus every cut key, so these dicts mirror the real ones without .get chains.
    """
    honbun_off = {"n": 97, "recall": {"R@10": 78, "R@20": 85}}
    newlayer = {
        "tsutatsu": {
            "fold_off": {"n": 15, "recall": {"R@20": 15}},
            "fold_on": {"n": 15, "recall": {"R@20": 14}},
        },
        "taxanswer": {
            "fold_off": {"n": 17, "recall": {"R@20": 17}},
            "fold_on": {"n": 17, "recall": {"R@20": 16}},
        },
    }
    target = {"N": 97, "R@10": 78, "R@20": 85}
    newlayer_target = {"tsutatsu": {"N": 15, "R@20": 15}, "taxanswer": {"N": 17, "R@20": 17}}
    return honbun_off, newlayer, target, newlayer_target


def test_all_match_passes() -> None:
    h = _load_harness()
    ok, reasons = h._verdict(*_good())
    assert ok is True
    assert reasons == []


def test_honbun_r10_short_fails_and_names_it() -> None:
    h = _load_harness()
    honbun_off, newlayer, target, newlayer_target = _good()
    honbun_off["recall"]["R@10"] = 77  # one below the locked line
    ok, reasons = h._verdict(honbun_off, newlayer, target, newlayer_target)
    assert ok is False
    assert any("honbun R@10" in r for r in reasons)


def test_tsutatsu_n_short_fails_and_names_it() -> None:
    h = _load_harness()
    honbun_off, newlayer, target, newlayer_target = _good()
    newlayer["tsutatsu"]["fold_off"]["n"] = 12  # denominator silently shrank
    ok, reasons = h._verdict(honbun_off, newlayer, target, newlayer_target)
    assert ok is False
    assert any("tsutatsu N" in r for r in reasons)


def test_taxanswer_r20_short_fails_and_names_it() -> None:
    h = _load_harness()
    honbun_off, newlayer, target, newlayer_target = _good()
    newlayer["taxanswer"]["fold_off"]["recall"]["R@20"] = 16
    ok, reasons = h._verdict(honbun_off, newlayer, target, newlayer_target)
    assert ok is False
    assert any("taxanswer R@20" in r for r in reasons)


def test_measured_group_without_target_fails() -> None:
    """A group we measured but never recorded a pass line for is not a pass."""
    h = _load_harness()
    honbun_off, newlayer, target, newlayer_target = _good()
    newlayer["surprise"] = {
        "fold_off": {"n": 3, "recall": {"R@20": 3}},
        "fold_on": {"n": 3, "recall": {"R@20": 3}},
    }
    ok, reasons = h._verdict(honbun_off, newlayer, target, newlayer_target)
    assert ok is False
    assert any("surprise" in r and "no recorded target" in r for r in reasons)


def test_target_group_without_measurement_fails() -> None:
    """A recorded pass line with no measured group behind it is not a line met."""
    h = _load_harness()
    honbun_off, newlayer, target, newlayer_target = _good()
    newlayer_target["ghost"] = {"N": 5, "R@20": 5}
    ok, reasons = h._verdict(honbun_off, newlayer, target, newlayer_target)
    assert ok is False
    assert any("ghost" in r and "not measured" in r for r in reasons)


def test_fold_on_shortfall_does_not_fail() -> None:
    """fold_on is report-only: a fold_on drop must not flip the verdict (keep the asymmetry)."""
    h = _load_harness()
    honbun_off, newlayer, target, newlayer_target = _good()
    newlayer["tsutatsu"]["fold_on"]["recall"]["R@20"] = 0
    ok, reasons = h._verdict(honbun_off, newlayer, target, newlayer_target)
    assert ok is True
    assert reasons == []

"""Tests for the outward-README public-claims gate (VA-5-data).

The gate scans only MARKETING_FILES (README.md), so the detection core can be
tested with literal accuracy figures without the gate flagging this test file --
the driver never reads it. Split into a pure `find_accuracy_claims(text)` and a
`scan_marketing(repo)` driver so the two concerns are tested apart.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_GATE = Path(__file__).resolve().parents[1] / "check-public-claims.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_public_claims", _GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


def test_current_readme_is_clean():
    # After the scrub, the outward surfaces (README.md AND README-EXT.md) carry no
    # retrieval accuracy figure -- scan_marketing covers every MARKETING_FILES entry.
    assert gate.scan_marketing(gate.REPO) == []


def test_readme_ext_is_scanned_and_clean():
    # The external reproduction runbook is an outward surface, so it is in scope...
    assert "README-EXT.md" in gate.MARKETING_FILES
    # ...and it is figure-free: its own text pairs no accuracy term with a number.
    runbook = (gate.REPO / "README-EXT.md").read_text(encoding="utf-8")
    assert gate.find_accuracy_claims(runbook) == []


def test_catches_accuracy_figure():
    assert gate.find_accuracy_claims("自治体 RAG R@1 65.7%")
    assert gate.find_accuracy_claims("Recall@3 = 88.6%")
    assert gate.find_accuracy_claims("精度 92%")


def test_no_false_positive_on_structural_counts():
    # Badges, structural counts, versions, and URL-encoded values carry no
    # accuracy context term, so they must not be flagged.
    assert gate.find_accuracy_claims("Articles: 11,758") == []
    assert gate.find_accuracy_claims("tests-46 passing") == []
    assert gate.find_accuracy_claims("Phase 1 / v0.2.0") == []
    assert gate.find_accuracy_claims("query%20string%20with%2020") == []


def test_catches_accuracy_figure_in_runbook_text():
    # A runbook line that paired an accuracy term with a number would be caught --
    # this is what keeps figures off README-EXT.md, redirected to benchmarks/.
    assert gate.find_accuracy_claims("再現手順の一例: R@1 68.6% を達成")
    assert gate.find_accuracy_claims("Recall@3 = 88.6% on the eval set")


def test_scope_is_marketing_files_only():
    # The detection core WOULD flag a benchmarks-style Recall line...
    assert gate.find_accuracy_claims("Recall@1 = 88.6% (95% CI)")
    # ...but the driver only ever reads MARKETING_FILES, so open research under
    # benchmarks/ is out of scope by construction.
    assert gate.MARKETING_FILES == ("README.md", "README-EXT.md")

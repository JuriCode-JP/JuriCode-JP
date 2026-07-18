"""Tests for the fidelity-claims gate (VA-6 / C-FID).

The gate ties each outward fidelity claim to the G0 counters that enforce it. The
detection core is a pure `find_claim_violations(...)`, tested here with both the
shipped ledger (must be clean) and synthetic claims that each trip exactly one
check. The driver reads gates/ and README.md; the pure function is what these
tests exercise, so no file is mutated.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[3]  # tools/scripts/tests/<this> -> repo root
_GATE = _HERE.parents[1] / "check-fidelity-claims.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_fidelity_claims", _GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


def _real_violation_set() -> set[str]:
    data = json.loads((_REPO / "gates" / "g0-classification.json").read_text(encoding="utf-8"))
    return set(data.get("violation", []))


def _real_claims() -> list[dict]:
    data = json.loads((_REPO / "gates" / "fidelity-claims.json").read_text(encoding="utf-8"))
    return data["claims"]


def _real_readme() -> str:
    return (_REPO / "README.md").read_text(encoding="utf-8")


def _both_required(**overrides) -> list[dict]:
    """A minimal well-formed ledger holding both required claims, so only the field
    under test can trip a violation. `overrides` patches the first claim."""
    first = {
        "claim_id": "body-equals-egov",
        "readme_anchors": [],
        "gate_ids": [],
        "enforced_by": "README.md",  # a real file, so the enforced_by check passes
    }
    first.update(overrides)
    second = {
        "claim_id": "no-ruby-contamination",
        "readme_anchors": [],
        "gate_ids": [],
        "enforced_by": "README.md",
    }
    return [first, second]


# 1. the shipped ledger, real counters, real README -> clean (true repo root).
def test_current_ledger_is_clean():
    problems = gate.find_claim_violations(
        _real_claims(), _real_violation_set(), _real_readme(), _REPO
    )
    assert problems == [], problems


# 2. a cited gate_id that is not in the violation set is caught.
def test_nonexistent_gate_id_is_caught():
    claims = _both_required(gate_ids=["g0z_nonexistent"])
    problems = gate.find_claim_violations(claims, _real_violation_set(), _real_readme(), _REPO)
    assert any("g0z_nonexistent" in p for p in problems)


# 3. a readme_anchor that is not on the README is caught.
def test_nonexistent_anchor_is_caught():
    claims = _both_required(readme_anchors=["この文はREADMEに無い"])
    problems = gate.find_claim_violations(claims, _real_violation_set(), _real_readme(), _REPO)
    assert any("readme_anchor[0]" in p for p in problems)


# 4. an enforced_by path that does not exist is caught.
def test_missing_enforced_by_is_caught():
    claims = _both_required(enforced_by="tools/does/not/exist.py")
    problems = gate.find_claim_violations(claims, _real_violation_set(), _real_readme(), _REPO)
    assert any("enforced_by" in p and "exist.py" in p for p in problems)


# 5. dropping a required claim is a structural violation (gutted-ledger guard).
def test_missing_required_claim_is_structural_violation():
    claims = [
        {
            "claim_id": "body-equals-egov",
            "readme_anchors": [],
            "gate_ids": [],
            "enforced_by": "README.md",
        }
    ]  # no-ruby-contamination removed
    problems = gate.find_claim_violations(claims, _real_violation_set(), _real_readme(), _REPO)
    assert any("structural" in p and "no-ruby-contamination" in p for p in problems)


# 6. anchor matching is resilient to decoration/whitespace but sensitive to wording.
def test_anchor_matching_is_decoration_and_whitespace_resilient():
    readme = "**空白の畳み込みを 除いて  完全に一致**"
    # decoration + stray spaces around an unspaced anchor -> still matches (no violation)
    matching = _both_required(readme_anchors=["空白の畳み込みを除いて完全に一致"])
    assert gate.find_claim_violations(matching, _real_violation_set(), readme, _REPO) == []
    # a real wording change is still caught
    changed = _both_required(readme_anchors=["完全一致"])
    problems = gate.find_claim_violations(changed, _real_violation_set(), readme, _REPO)
    assert any("readme_anchor[0]" in p for p in problems)


# 7. no false positive: the shipped two-claim ledger is clean (same as case 1,
#    stated separately so a regression naming either claim is unambiguous).
def test_no_false_positive_on_shipped_claims():
    claims = _real_claims()
    assert {c["claim_id"] for c in claims} == {"body-equals-egov", "no-ruby-contamination"}
    assert gate.find_claim_violations(claims, _real_violation_set(), _real_readme(), _REPO) == []

"""Drift guard: run-ci.py's target sets must equal ci.yml's.

Why:
    run-ci.py duplicates CI's invocations so a contributor can reproduce CI locally
    with one command. A duplicated list is only safe if something compares the copies
    -- an un-compared duplicate is exactly how the local runner drifted to roughly a
    sixth of CI's coverage while still printing ALL GREEN (and, separately, diffed
    only two of CI's four schema files). These tests are that comparison: they parse
    both sides and assert the sets are equal, so adding (or removing) an entry on one
    side without the other fails HERE instead of silently going unrun locally.

    Parsing happens in the test, not in run-ci.py itself: the runner keeps a literal
    copy (no YAML dependency at runtime, no indentation change able to break it), and
    these tests are what keep that copy honest.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]
_CI_YML = _REPO / ".github" / "workflows" / "ci.yml"
_RUN_CI = _REPO / "tools" / "scripts" / "run-ci.py"

_PYTEST_STEP_NAME = "Pytest (all workspace packages)"
_SCHEMA_STEP_NAME = "Regenerate JSON Schema and check for drift"


def _ci_steps() -> list[dict]:
    doc = yaml.safe_load(_CI_YML.read_text(encoding="utf-8"))
    return doc["jobs"]["lint-and-test"]["steps"]


def _step_run(name: str) -> str:
    return next(s["run"] for s in _ci_steps() if s.get("name") == name)


def _ci_pytest_paths() -> set[str]:
    """Path arguments of ci.yml's single pytest command (flags dropped)."""
    tokens = _step_run(_PYTEST_STEP_NAME).split()
    assert tokens and tokens[0] == "pytest", f"unexpected pytest command: {tokens[:1]!r}"
    return {t for t in tokens[1:] if not t.startswith("-")}


def _ci_schema_files() -> set[str]:
    """Schema files ci.yml runs `git diff --exit-code` against."""
    run_cmd = _step_run(_SCHEMA_STEP_NAME)
    files = set(re.findall(r"git diff --exit-code (schema/\S+\.json)", run_cmd))
    assert files, f"no schema diffs found in step {_SCHEMA_STEP_NAME!r}"
    return files


def _run_ci_module():
    """Import run-ci.py (the module has no import-time side effects)."""
    spec = importlib.util.spec_from_file_location("run_ci", _RUN_CI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_ci_pytest_paths_match_ci_yaml() -> None:
    ci = _ci_pytest_paths()
    local = set(_run_ci_module().PYTEST_PATHS)
    assert local == ci, (
        "run-ci.py and ci.yml pytest target sets diverged -- add the path in BOTH:\n"
        f"  only in ci.yml : {sorted(ci - local)}\n"
        f"  only in run-ci : {sorted(local - ci)}"
    )


def test_run_ci_schema_files_match_ci_yaml() -> None:
    ci = _ci_schema_files()
    local = set(_run_ci_module().SCHEMA_DRIFT_FILES)
    assert local == ci, (
        "run-ci.py and ci.yml schema-drift target sets diverged -- add the schema in BOTH:\n"
        f"  only in ci.yml : {sorted(ci - local)}\n"
        f"  only in run-ci : {sorted(local - ci)}"
    )

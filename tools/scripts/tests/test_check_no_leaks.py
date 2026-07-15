"""Hermetic tests for the leak gate (git-independent: only scan_line is exercised).

The literal maintainer name is never written here either; it is base64-decoded at
runtime, matching the gate's own encoding so this test file carries no plaintext name.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_no_leaks import SELF_FILES, scan_line  # noqa: E402


def test_dist_scanner_is_self_excluded():
    """The dist leak scanner + its test define banned tokens as rule literals, so
    they must be in SELF_FILES or the gate would flag its own introduction. Pin
    the exact paths (regression guard for D2, 2026-07-15). No wildcard entries."""
    assert "tools/dist/scan_artifacts.py" in SELF_FILES
    assert "tools/dist/tests/test_scan_artifacts.py" in SELF_FILES
    assert not any("*" in f for f in SELF_FILES)  # explicit paths only, no globs


def test_flags_name_encoded():
    name = base64.b64decode("5L2Q6Jek").decode("utf-8")  # test also avoids the literal name
    assert scan_line(f"per {name} ruling")


def test_flags_terms():
    assert scan_line("see 105_ design")
    assert scan_line("Cowork planning")
    assert scan_line("per the briefing")


def test_clean_and_allowlist():
    assert not scan_line("normal deterministic code line")
    assert not scan_line("二重貼付 double-paste guard")  # allowlisted
    assert not scan_line("law id 363AC0000000108_20230401")  # 0108_ excluded
    assert not scan_line("chunk range 150_000 items")  # numeric literal excluded

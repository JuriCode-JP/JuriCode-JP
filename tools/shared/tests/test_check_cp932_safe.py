"""Self-test for tools/scripts/check-cp932-safe.py (FU-505)."""

import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/scripts/check-cp932-safe.py"


def test_help_runs() -> None:
    """check-cp932-safe.py --help should exit 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout


def test_happy_path_clean_dir(tmp_path: Path) -> None:
    """A directory with only safe files should exit 0."""
    (tmp_path / "safe.py").write_text('"""safe -- no unsafe chars."""\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--path", str(tmp_path)],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert b"cp932-safe" in result.stdout


def test_detects_unsafe_file(tmp_path: Path) -> None:
    """A file with em dash should cause exit 1 with FAIL output."""
    unsafe = tmp_path / "bad.py"
    unsafe.write_text('"""bad -- has em dash — here."""\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--path", str(tmp_path)],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert b"FAIL" in result.stderr

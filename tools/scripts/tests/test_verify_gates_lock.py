"""Tests for the locked-pass-lines checksum gate.

Why:
    The retrieval pass line now lives in gates/pass-lines.json and is anchored by a
    digest held outside the repo (a CI variable). These tests pin the guard-the-guard
    behaviour: the digest binds paths as well as contents, the pre-activation bridge
    announces itself, an activated gate fails a mismatch, and the committed file still
    carries the exact owner-locked values.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]
_SCRIPT = _REPO / "tools" / "scripts" / "verify-gates-lock.py"
_PASS_LINES = _REPO / "gates" / "pass-lines.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_gates_lock", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(env_value: str | None) -> subprocess.CompletedProcess[str]:
    """Run the gate as a subprocess so we exercise the real exit code and env bridge."""
    env = {"PATH": __import__("os").environ.get("PATH", "")}
    if env_value is not None:
        env["GATES_LOCK_SHA256"] = env_value
    return subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO),
    )


# --- digest is stable and path-binding -------------------------------------------


def test_combined_digest_is_stable() -> None:
    mod = _load_module()
    assert mod.combined_digest(_REPO) == mod.combined_digest(_REPO)


def test_combined_digest_binds_content(tmp_path: Path) -> None:
    """Changing the file's content changes the digest."""
    mod = _load_module()
    (tmp_path / "gates").mkdir()
    orig = (_REPO / "gates" / "pass-lines.json").read_bytes()
    (tmp_path / "gates" / "pass-lines.json").write_bytes(orig)
    before = mod.combined_digest(tmp_path)
    (tmp_path / "gates" / "pass-lines.json").write_bytes(orig + b"\n// tampered\n")
    after = mod.combined_digest(tmp_path)
    assert before != after


def test_combined_digest_binds_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The path is hashed too: identical bytes under a different locked path differ."""
    mod = _load_module()
    content = b'{"pass_lines": {}}\n'
    (tmp_path / "gates").mkdir()
    (tmp_path / "gates" / "pass-lines.json").write_bytes(content)
    d_normal = mod.combined_digest(tmp_path)

    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "renamed.json").write_bytes(content)
    monkeypatch.setattr(mod, "LOCKED_FILES", ["other/renamed.json"])
    d_renamed = mod.combined_digest(tmp_path)
    assert d_normal != d_renamed


# --- activation bridge -----------------------------------------------------------


def test_unset_variable_is_inactive_and_announces_itself() -> None:
    """Unset -> exit 0 AND the INACTIVE warning appears (the bridge is not silent)."""
    proc = _run(env_value=None)
    assert proc.returncode == 0
    assert "pass-line lock gate INACTIVE" in proc.stderr


def test_set_and_matching_exits_zero() -> None:
    mod = _load_module()
    digest = mod.combined_digest(_REPO)
    proc = _run(env_value=digest)
    assert proc.returncode == 0
    assert "INACTIVE" not in proc.stderr


def test_set_and_mismatching_exits_one() -> None:
    proc = _run(env_value="0" * 64)
    assert proc.returncode == 1
    assert "have changed" in proc.stderr


def test_gate_prints_digest_in_greppable_shape() -> None:
    """approve-gates-lock.sh greps for this exact prefix; keep it stable."""
    proc = _run(env_value=None)
    assert any(line.startswith("pass-lines combined SHA256: ") for line in proc.stdout.splitlines())


# --- the committed file carries the exact locked values --------------------------


def test_pass_lines_parses_and_holds_locked_values() -> None:
    doc = json.loads(_PASS_LINES.read_text(encoding="utf-8"))
    pl = doc["pass_lines"]
    assert set(pl) == {"v0.2-aug-v8b-gemini", "v0.2-aug-v9-gemini"}

    v8b = pl["v0.2-aug-v8b-gemini"]
    assert v8b["honbun"] == {"N": 97, "R@10": 84, "R@20": 87}
    assert v8b["newlayer"]["tsutatsu"] == {"N": 15, "R@20": 15}
    assert v8b["newlayer"]["taxanswer"] == {"N": 17, "R@20": 17}

    v9 = pl["v0.2-aug-v9-gemini"]
    assert v9["honbun"] == {"N": 97, "R@10": 78, "R@20": 85}
    assert v9["newlayer"]["tsutatsu"] == {"N": 15, "R@20": 15}
    assert v9["newlayer"]["taxanswer"] == {"N": 17, "R@20": 17}


# --- the harness stamp must agree with the anchor (makes the duplication safe) ----


def _harness_locked_files() -> list[str]:
    """Extract reproduce_a3's _LOCKED_GATE_FILES WITHOUT importing the module.

    Why not import it: reproduce_a3 imports numpy + the retrieval stack at module top,
    and numpy is deliberately absent from CI's dev deps, so importing it in a
    CI-enumerated test would fail collection. We only need the list, so read it out of
    the source with ast.
    """
    import ast

    src = (_REPO / "tools" / "serve" / "reproduce_a3.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "_LOCKED_GATE_FILES" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("_LOCKED_GATE_FILES not found in reproduce_a3.py")


def test_harness_locked_files_match_the_gate() -> None:
    """The harness's copy of the locked-file list must equal the gate's list.

    This is the check that makes duplicating the digest logic safe: when a later step
    adds a file to the lock and updates the gate but forgets the harness, THIS fails in
    CI -- instead of the harness quietly stamping a digest that no longer matches the
    GATES_LOCK_SHA256 anchor. It runs unconditionally (ast, no heavy import), so the
    guard holds in CI where numpy is absent.
    """
    mod = _load_module()
    assert _harness_locked_files() == mod.LOCKED_FILES


def test_harness_stamp_equals_the_anchor_digest() -> None:
    """reproduce_a3's stamped digest == verify-gates-lock's combined_digest.

    This is the end-to-end value check. It imports the harness, which pulls in numpy +
    the retrieval stack (absent from CI dev deps), so it runs locally and skips in CI;
    the list-level agreement above is what guards CI. Locally it proves the actual
    stamped value equals the anchor byte-for-byte.
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
    gate = _load_module()
    assert harness._pass_lines_digest() == gate.combined_digest(_REPO)

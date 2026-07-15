#!/usr/bin/env python3
"""Verify the locked retrieval pass lines against an out-of-band SHA256.

Why:
    The retrieval harness proves a build reproduces a recorded pass line. That
    pass line used to live as a code literal, which means whoever can edit the
    code (including an AI agent) can also move the line to match a worse build --
    "the gate passed" would then only mean "it passed the line the same agent
    could have lowered". Moving the pass line into gates/pass-lines.json and
    anchoring that file with a digest held OUTSIDE this agent's write scope (a CI
    secret / repo variable) closes that loop.

Guard-the-guard:
    The expected digest is NOT stored in the repo. It is injected via the
    GATES_LOCK_SHA256 environment variable (GitHub Actions secret/variable).
    Because the agent cannot write the secret, it cannot quietly move the goalpost
    to match a tampered pass-lines file. Editing THIS script to bypass the check is
    still possible in principle, so the workflow file and this gate should be
    covered by branch protection requiring human review. This mirrors the eval-set
    checksum gate (tools/scripts/verify-eval-set-checksum.py, FU-515 D-b).

Legitimate updates:
    To change a pass line legitimately, a human runs
    tools/scripts/approve-gates-lock.sh to print the new digest, then updates the
    CI variable. The agent has no path to do this, which keeps pass-line updates
    behind a human signature.

Activation:
    - GATES_LOCK_SHA256 unset -> gate INACTIVE: prints the current digest and a
      warning, exits 0. This is the pre-activation bridge so the very first PR (which
      introduces the file before the variable exists) is not blocked.
    - GATES_LOCK_SHA256 set    -> gate ACTIVE: mismatch exits 1 (hard fail).

Usage:
    python tools/scripts/verify-gates-lock.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

# Locked gate-contract files. Explicit list, NOT a glob: a wildcard silently
# swallows files added later, so a new contract could slip in unhashed (the leak
# scanner learned this the hard way -- see tools/scripts/check_no_leaks.py).
LOCKED_FILES = [
    "gates/pass-lines.json",
]

ENV_VAR = "GATES_LOCK_SHA256"


def combined_digest(repo_root: Path) -> str:
    """Combined SHA256 over sorted (path, LF-normalized-bytes) pairs.

    Why: a single combined digest binds BOTH the file contents AND their paths, so
    neither swapping file contents nor renaming can pass undetected.
    """
    h = hashlib.sha256()
    for rel in sorted(LOCKED_FILES):
        path = repo_root / rel
        if not path.exists():
            print(f"ERROR: locked gate file missing: {rel}", file=sys.stderr)
            sys.exit(2)
        norm = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode("utf-8") + b"\0" + norm)
    return h.hexdigest()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    actual = combined_digest(repo_root)
    expected = os.environ.get(ENV_VAR, "").strip().lower()

    print(f"pass-lines combined SHA256: {actual}")
    for rel in sorted(LOCKED_FILES):
        norm = (repo_root / rel).read_bytes().replace(b"\r\n", b"\n")
        print(f"  {hashlib.sha256(norm).hexdigest()}  {rel}")

    if not expected:
        print(
            f"\nWARNING: {ENV_VAR} is not set -> pass-line lock gate INACTIVE.\n"
            f"  Set the CI secret/variable {ENV_VAR}={actual} to activate the gate.\n"
            f"  (Run tools/scripts/approve-gates-lock.sh as a human to (re)compute it.)",
            file=sys.stderr,
        )
        return 0

    if actual == expected:
        print(f"\nOK: pass lines match locked digest in {ENV_VAR}.")
        return 0

    print(
        f"\nFAIL: the locked pass lines have changed.\n"
        f"  expected ({ENV_VAR}): {expected}\n"
        f"  actual (on disk)    : {actual}\n"
        f"  The locked pass lines must not be edited to make a run pass. If this change\n"
        f"  is legitimate, a human must run tools/scripts/approve-gates-lock.sh and update\n"
        f"  the {ENV_VAR} variable.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Verify locked eval-set golden files against an out-of-band SHA256.

Why:
    FU-515 D-b locked the G1-local / G3-sp golden answer keys (data/eval-set/).
    The locked expected values must never be silently edited to make an eval
    "pass" (reward hacking). A human PR review alone cannot catch a "flip then
    revert before commit" trick, so we add a machine gate: recompute the combined
    SHA256 of the locked files and compare against an expected digest held
    OUTSIDE this agent's write scope (a CI secret / repo variable). See lock plan
    fu-515-db-golden-lock-plan-2026-06-20.md AC-3 / AC-7 / AC-12.

Guard-the-guard (AC-7):
    The expected digest is NOT stored in the repo. It is injected via the
    EVALSET_GOLDEN_SHA256 environment variable (GitHub Actions secret/variable).
    Because the agent cannot write the secret, it cannot quietly move the goalpost
    to match a tampered golden file. Editing THIS script to bypass the check is
    still possible in principle, so the workflow file and this gate should be
    covered by branch protection requiring human review (an L3 control).

Legitimate updates (AC-12):
    To change the golden legitimately, a human runs tools/scripts/approve-eval-set.sh
    to print the new digest, then updates the CI secret. The agent has no path to do
    this, which keeps golden updates behind a human signature.

Activation:
    - EVALSET_GOLDEN_SHA256 unset  -> gate INACTIVE: prints the current digest and a
      warning, exits 0. This is the pre-activation bridge so the very first PR (which
      introduces the golden before the secret exists) is not blocked.
    - EVALSET_GOLDEN_SHA256 set     -> gate ACTIVE: mismatch exits 1 (hard fail).

Usage:
    python tools/scripts/verify-eval-set-checksum.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

# Locked golden files (sorted; both LF-normalized before hashing for OS stability).
GOLDEN_FILES = [
    "data/eval-set/tax-honbun-local/g1-local.jsonl",
    "data/eval-set/tax-supplproviso-probe/g3-sp.jsonl",
]

ENV_VAR = "EVALSET_GOLDEN_SHA256"


def combined_digest(repo_root: Path) -> str:
    """Combined SHA256 over sorted (path, LF-normalized-bytes) pairs.

    Why: a single combined digest binds BOTH files and their paths, so neither
    swapping file contents nor renaming can pass undetected.
    """
    h = hashlib.sha256()
    for rel in sorted(GOLDEN_FILES):
        path = repo_root / rel
        if not path.exists():
            print(f"ERROR: locked golden file missing: {rel}", file=sys.stderr)
            sys.exit(2)
        norm = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode("utf-8") + b"\0" + norm)
    return h.hexdigest()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    actual = combined_digest(repo_root)
    expected = os.environ.get(ENV_VAR, "").strip().lower()

    print(f"eval-set golden combined SHA256: {actual}")
    for rel in sorted(GOLDEN_FILES):
        norm = (repo_root / rel).read_bytes().replace(b"\r\n", b"\n")
        print(f"  {hashlib.sha256(norm).hexdigest()}  {rel}")

    if not expected:
        print(
            f"\nWARNING: {ENV_VAR} is not set -> checksum gate INACTIVE.\n"
            f"  Set the CI secret/variable {ENV_VAR}={actual} to activate the gate.\n"
            f"  (Run tools/scripts/approve-eval-set.sh as a human to (re)compute it.)",
            file=sys.stderr,
        )
        return 0

    if actual == expected:
        print(f"\nOK: golden matches locked digest in {ENV_VAR}.")
        return 0

    print(
        f"\nFAIL: eval-set golden has changed.\n"
        f"  expected ({ENV_VAR}): {expected}\n"
        f"  actual (on disk)    : {actual}\n"
        f"  The locked golden must not be edited. If this change is legitimate, a human\n"
        f"  must run tools/scripts/approve-eval-set.sh and update the {ENV_VAR} secret.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

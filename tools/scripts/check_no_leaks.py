#!/usr/bin/env python3
"""Leak gate: block personal names + internal process refs from public history.

Scans a base..HEAD range: (1) added diff lines, (2) commit messages.
Personal-name tokens are BASE64-ENCODED below so the literal name never appears
in this public file. Exit 1 (with report) if any banned pattern is found.

Self-exclusion: this file and its test necessarily contain the pattern literals
(the term patterns and the base64 name), so scanning their own added diff lines
would flag the gate's own introduction. They are excluded from the diff scan
(a leak detector does not treat its own rule definitions as leaks). Commit
messages are always scanned (they must never carry a banned token).
"""

from __future__ import annotations

import argparse
import base64
import re
import subprocess
import sys

# Base64 of personal-name tokens (decoded at runtime). Keeps the literal name
# OUT of this public file. To add a name: base64.b64encode("X".encode()).decode().
DENY_NAMES_B64 = ["5L2Q6Jek"]  # maintainer surname
NAME_PATTERNS = [re.escape(base64.b64decode(b).decode("utf-8")) for b in DENY_NAMES_B64]

# Plain process/term patterns (not sensitive to list here).
TERM_PATTERNS = [
    r"Cowork",
    r"briefing",
    # internal doc refs e.g. 1XX_ ; excludes law ids (...0108_) and numeric
    # literals (150_000) via the surrounding lookaround.
    r"(?<![0-9A-Za-z])1[0-9]{2}_(?![0-9])",
]
ALLOW = ["二重貼付"]  # technical term containing a banned substring; stripped before matching

PATTERNS = [re.compile(p) for p in NAME_PATTERNS + TERM_PATTERNS]

# The gate's own files define the patterns above and cannot be scanned for them.
SELF_FILES = frozenset(
    {
        "tools/scripts/check_no_leaks.py",
        "tools/scripts/tests/test_check_no_leaks.py",
    }
)


def sh(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8").stdout


def scan_line(text: str) -> list[str]:
    for a in ALLOW:
        text = text.replace(a, "")
    return [p.pattern for p in PATTERNS if p.search(text)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    a = ap.parse_args()
    hits = []
    # 1) added diff lines (three-dot = changes introduced by the branch)
    diff = sh("diff", "--unified=0", f"{a.base}...{a.head}")
    cur = "?"
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            if cur in SELF_FILES:
                continue
            for pat in scan_line(ln[1:]):
                hits.append((cur, "diff", pat, ln[1:].strip()[:120]))
    # 2) commit messages in range (always scanned; never self-excluded)
    for h in sh("rev-list", f"{a.base}..{a.head}").split():
        for line in sh("log", "-1", "--format=%B", h).splitlines():
            for pat in scan_line(line):
                hits.append((h[:10], "commit-msg", pat, line.strip()[:120]))
    if hits:
        print("LEAK GATE: banned content found (blocking):", file=sys.stderr)
        for where, kind, pat, sample in hits:
            print(f"  [{kind}] {where}: /{pat}/ -> {sample}", file=sys.stderr)
        return 1
    print("leak gate: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

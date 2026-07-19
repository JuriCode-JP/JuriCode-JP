#!/usr/bin/env python3
"""check-public-claims-gate.py -- outward guarantee-claim gate.

Why:
    A public board (README / spec page / package README) may state that the
    corpus is "verified", "round-trip" checked, a "verbatim" copy, and so on.
    Such a guarantee is only trustworthy if it names the gate that enforces it.
    This check fails a board when a guarantee word appears WITHOUT an adjacent
    gate id ([G0-a] / (G0-a) / [HASH] / [G1] / [G2]) that points at the gate
    backing it. A bare promise -- a guarantee with no gate behind it -- is
    exactly what this removes. It also keeps retrieval/accuracy figures off the
    boards (they belong in benchmarks/, where the methodology is open).

Layout discipline (the rule the boards must follow):
    A guarantee word and its gate id sit on the SAME LINE, ADJACENT (the id
    immediately after the word). A claim hard-wrapped across lines is rewritten
    so the word and its id share one line. Two properties fall out of this:
      - a claim split by a soft line break never false-fails (the id is on the
        word's line by construction), and
      - a gate id sitting far from the word -- a parasite that would otherwise
        make an unrelated word look backed -- still fails (it is outside the
        adjacency window).
    A regex cannot judge meaning, so an adjacent MIS-attribution can still slip
    through; that residue is caught by the narrow dictionary plus human review,
    which this file does not claim to replace.

Scope and vocabulary are intentionally narrow and are configuration, not code:
    BOARD_FILES, DICTIONARY, METRIC_TERMS and the exclusion markers are all
    owner-locked. Changing any of them requires repository-owner approval; they
    start narrow on purpose and are widened deliberately, not incidentally.

exit 0: every board is clean.
exit 1: at least one bare guarantee or accuracy figure remains (file:line report
        on stderr). ASCII-only report (the console may be cp932).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Curated boards only -- NOT the whole repo. These are the outward surfaces
#: where a guarantee is a promise to a reader. The deeper v0.2 format spec is
#: deliberately NOT here: it DESCRIBES the verification machinery, where the same
#: vocabulary is mechanism, not a promise, and a word-level gate cannot tell the
#: two apart. The v0.1 format spec IS in scope -- its fidelity statement is a
#: guarantee, so it carries a gate id. Widening this list is an owner decision.
BOARD_FILES = (
    "README.md",
    "README-EXT.md",
    "docs/strategy.md",
    "docs/licensing.md",
    "docs/format-spec.md",
    "docs/verification-framework.md",
    "packages/juricode-verifier/README.md",
    "packages/juricode-retrieval/README.md",
)

#: The narrow guarantee vocabulary. A match here demands an adjacent gate id.
#: Bare "100%" is deliberately NOT a trigger: a coverage estimate ("~100%") is
#: allowed (owner ruling), and a "100%" that is a guarantee is already carried by
#: one of these words next to it. Widening this list is an owner decision.
DICTIONARY = (
    "検証済",
    "保証",
    "完全",
    "一切改変しない",
    "round-trip",
    "バイト一致",
    "逐語",
    "verbatim",
    "verified",
    "guarantee",
)

#: A gate id: [G0-a]..[G0-e], [G1], [G2], [HASH] (or the same in round brackets).
GATE_ID = re.compile(r"[\[(](?:G0-[a-e]|G[12]|HASH)[\])]")

#: Adjacency window: a gate id must start within this many characters AFTER the
#: guarantee word (same line). Owner-set guideline of 25.
PROXIMITY = 25

#: Retrieval/accuracy figures banned on every board. Boundary + digit, so a
#: metric DEFINITION ("Recall@K", K not a digit) and an "@mention" are not
#: caught -- only an actual figure (Recall@3, ...). Coverage/completeness "%"
#: and plain counts ("11,758 条") are allowed and are not listed here.
METRIC_TERMS = re.compile(
    r"\bR@\d+\b|\bRecall@\d+\b|\bMRR\b|\bnDCG\b|\bPrecision@\d+\b|再現率|適合率",
    re.IGNORECASE,
)

#: Case-insensitive matchers for the dictionary (ASCII terms need it; the
#: Japanese terms are unaffected by the flag).
DICT_PATTERNS = [re.compile(re.escape(w), re.IGNORECASE) for w in DICTIONARY]

# Exclusion markers for the GUARANTEE check only (the metric ban still applies to
# these lines). Each corresponds to a false-positive class: a guarantee word that
# is not a live promise.
#   (a) goal declaration -- a stated aim, not a current guarantee
GOAL_MARKERS = ("北極星", "最終ビジョン")
#   (b) disclaimer -- the line withdraws or qualifies the guarantee
DISCLAIMERS = ("完全な一覧ではない", "保証でき", "nothing was verified", "訂正")
#   (c) limitation -- the line states the guarantee does NOT apply here
LIMITATIONS = ("不可", "対象ではない", "対象外")
#   (d) field name -- a schema field that happens to contain a term
FIELD_NAMES = ("last_verified",)
#   (e) progress-log bullet -- a dated history entry, not a standing claim
DATE_LOG = re.compile(r"^\s*[-*]\s*(?:\*\*)?\s*\d{4}-\d{2}")

FENCE = re.compile(r"^\s*```")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
EMPH = re.compile(r"\*\*|\*")


def normalize(line: str) -> str:
    """Length-preserving normalization for word/id matching.

    Inline code spans, markdown-link URLs and emphasis markers are replaced with
    spaces of equal length, so offsets stay aligned with the raw line (the
    adjacency distance is measured in these coordinates). Stripping inline code
    also drops backticked identifiers -- e.g. `check_quotes_verbatim` or
    `last_verified` -- so a term inside a code span is not read as a claim.
    """

    def blank(m: re.Match[str]) -> str:
        return " " * len(m.group())

    s = INLINE_CODE.sub(blank, line)
    s = LINK.sub(lambda m: m.group(1).ljust(len(m.group())), s)
    s = EMPH.sub(blank, s)
    return s


def is_excluded_for_guarantee(line: str) -> bool:
    """True if a guarantee word on this line is a known false positive (a-e)."""
    if any(mark in line for mark in GOAL_MARKERS):
        return True
    if any(mark in line for mark in DISCLAIMERS):
        return True
    if any(mark in line for mark in LIMITATIONS):
        return True
    if any(mark in line for mark in FIELD_NAMES):
        return True
    if DATE_LOG.match(line):
        return True
    return False


def scan_text(text: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (bare_guarantees, metric_hits) as (lineno, sample) lists."""
    bare: list[tuple[int, str]] = []
    metrics: list[tuple[int, str]] = []
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        norm = normalize(raw)

        # Metric ban: applies to every board line (even a dated log line), so a
        # figure can never re-enter a board unnoticed.
        if METRIC_TERMS.search(norm):
            metrics.append((lineno, raw.strip()[:120]))

        # Guarantee check: skip the false-positive classes (a-e).
        if is_excluded_for_guarantee(raw):
            continue
        ids = [m.start() for m in GATE_ID.finditer(norm)]
        for pat in DICT_PATTERNS:
            for m in pat.finditer(norm):
                end = m.end()
                if not any(0 <= start - end <= PROXIMITY for start in ids):
                    bare.append((lineno, raw.strip()[:120]))
                    break
    return bare, metrics


def main() -> int:
    argparse.ArgumentParser(
        description="Fail a board when a guarantee word has no adjacent gate id "
        "(or an accuracy figure appears)."
    ).parse_args()

    failures: list[str] = []
    for rel in BOARD_FILES:
        path = REPO / rel
        if not path.exists():
            failures.append(f"  {rel}: MISSING (board not found)")
            continue
        bare, metrics = scan_text(path.read_text(encoding="utf-8"))
        for lineno, sample in bare:
            failures.append(
                f"  {rel}:{lineno}: guarantee word with no adjacent gate id -> {sample!a}"
            )
        for lineno, sample in metrics:
            failures.append(f"  {rel}:{lineno}: accuracy figure on a board -> {sample!a}")

    if failures:
        print("FAIL: bare guarantee claim(s) / accuracy figure(s) on the boards:", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        print(
            "\nEvery guarantee word must carry an adjacent gate id "
            "([G0-a]/(G0-a)/[HASH]/[G1]/[G2]); accuracy figures belong in benchmarks/.",
            file=sys.stderr,
        )
        return 1

    print(f"public-claims gate passed ({len(BOARD_FILES)} board(s); every guarantee is gated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

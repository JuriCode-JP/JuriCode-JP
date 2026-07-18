#!/usr/bin/env python3
"""check-public-claims.py -- outward-facing README accuracy-figure scanner.

Why (VA-5-data / STOP #2):
The top-level README is an outward-facing marketing surface. Retrieval accuracy
figures (Recall@k, MRR, ...) belong in the open benchmarks/ directory, not on
the marketing README. This gate fails if such a figure reappears there, so the
rule is enforced by structure, not discipline.

scan 対象: MARKETING_FILES のみ (README.md)。
  benchmarks/ ・ docs/ ・ tools/*/README などの公開研究/評価方法論は L-OPENCORE の
  与える側ゆえ対象外 (リポ全体は走査しない)。
detection: 文脈語 (R@ / recall / precision / grounded / MRR / nDCG / 再現率 /
  適合率 / 精度・大小無視) の同一行に数値トークン (\\d+(\\.\\d+)?%? または
  \\d+\\s*/\\s*\\d+) があれば違反。文脈語なしの裸の数値 (バッジ・構造カウント・
  バージョン・URL エンコード) は拾わない。
exit 0: クリーン (対外面に精度数値なし)
exit 1: 1 件以上の精度数値あり (stderr に file:line と該当を出力)

self-scan は非問題: このゲートは MARKETING_FILES だけを走査し、自身やテストは
走査しない。将来 MARKETING_FILES にこのスクリプトを含めないこと。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Outward-facing marketing surface(s) only. NOT the whole repo: benchmarks/ and
#: other open research/methodology keep their figures (L-OPENCORE, the giving side).
MARKETING_FILES = ("README.md",)

#: Accuracy context terms. A number on the same line as one of these reads as a
#: retrieval-accuracy figure. The Japanese terms are cp932-safe.
CONTEXT_TERMS = (
    "R@",
    "recall",
    "precision",
    "grounded",
    "MRR",
    "nDCG",
    "再現率",
    "適合率",
    "精度",
)

#: A number token: a fraction (n/n) or a plain/decimal figure with optional %.
NUMBER = re.compile(r"\d+\s*/\s*\d+|\d+(?:\.\d+)?%?")


def find_accuracy_claims(text: str) -> list[tuple[int, str, str]]:
    """Return (lineno, context_term, number) for each line that pairs an accuracy
    context term with a number. A line with no context term is ignored, so bare
    structural counts, badges, versions, and URL-encoded values are not flagged.
    """
    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        term = next((t for t in CONTEXT_TERMS if t.lower() in low), None)
        if term is None:
            continue
        m = NUMBER.search(line)
        if m:
            hits.append((lineno, term, m.group()))
    return hits


def scan_marketing(repo_root: Path) -> list[tuple[str, int, str, str]]:
    """Scan MARKETING_FILES only; return (relpath, lineno, term, number) failures."""
    failures: list[tuple[str, int, str, str]] = []
    for rel in MARKETING_FILES:
        path = repo_root / rel
        if not path.exists():
            failures.append((rel, 0, "MISSING", "file-not-found"))
            continue
        for lineno, term, number in find_accuracy_claims(path.read_text(encoding="utf-8")):
            failures.append((rel, lineno, term, number))
    return failures


def main() -> int:
    argparse.ArgumentParser(
        description="Scan the outward README(s) for retrieval accuracy figures (VA-5-data)."
    ).parse_args()

    failures = scan_marketing(REPO)
    if failures:
        # ASCII-only report: the console running this may be cp932.
        print("FAIL: accuracy figures found on the outward marketing surface(s):", file=sys.stderr)
        for rel, lineno, term, number in failures:
            print(
                f"  {rel}:{lineno}: accuracy figure {number!a} near {term!a}",
                file=sys.stderr,
            )
        return 1

    print(
        f"public-claims gate passed ({len(MARKETING_FILES)} marketing file(s); no accuracy figures)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

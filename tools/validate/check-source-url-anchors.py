#!/usr/bin/env python3
"""Gate: statute-layer article source_url must be a well-formed e-Gov deep link.

Why this is a separate deterministic gate: whether an anchor actually scrolls
to the intended article can only be observed in a rendered DOM (fragments are
never sent to the server -- RFC 3986 sec. 3.5 -- and laws.e-gov.go.jp is a SPA
whose HTML carries no article markup). That check is a network probe and stays
out of CI. What CI *can* prove, offline and for every row, is that each URL has
the exact shape the anchor builder is supposed to emit, and that the source XML
those anchors are derived from is present for every law in the corpus.

Two checks, both fatal:

  1. Format: every statute-layer article document's ``source_url`` is
     ``https://laws.e-gov.go.jp/law/<law_id>`` with an optional
     ``#Mp[-<Level>_<Num>]...-At_<Num>`` fragment. Anything else is malformed.
  2. Coverage: every law_id in the ledger has a tracked ``cache/laws/*.xml``.
     A missing file is not a crash -- those articles quietly degrade to
     law-level URLs -- so it has to fail loudly here instead.

Counts for all three buckets (anchored / law-level fallback / malformed) are
always printed, including when the gate passes: a fallback that is never
reported is a silent truncation, and "every link is fine" must never be
inferred from a green gate that only looked at shape.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

#: Law-level base, e.g. https://laws.e-gov.go.jp/law/340AC0000000034
_BASE = re.compile(r"^https://laws\.e-gov\.go\.jp/law/(?P<law_id>[0-9A-Za-z]+)$")

#: Anchor path. Laws without 編/章 shorten to a bare ``Mp-At_<Num>`` -- the
#: hierarchy levels are optional precisely because e-Gov omits levels that do
#: not exist (measured); requiring them would fail every flat law.
_ANCHOR = re.compile(r"^Mp(?:-(?:Pa|Ch|Se|Ss|Di)_[0-9_]+)*-At_[0-9_]+$")

STATUTE_LAYERS = ("statute", "enforcement")


def is_article_row(row: dict) -> bool:
    """Statute-layer ARTICLE rows only (附則 rows carry no article_number)."""
    return row.get("layer") in STATUTE_LAYERS and row.get("article_number") is not None


def classify(source_url: str | None, law_id: str | None) -> str:
    """Return 'anchored' | 'fallback' | 'malformed' for one row."""
    if not source_url:
        return "malformed"
    base, sep, frag = source_url.partition("#")
    m = _BASE.match(base)
    if not m or (law_id is not None and m.group("law_id") != law_id):
        return "malformed"
    if not sep:
        return "fallback"
    return "anchored" if _ANCHOR.match(frag) else "malformed"


def check_documents(documents_path: Path) -> tuple[dict[str, int], list[str], set[str]]:
    """Classify every statute-layer article row. Returns (counts, samples, law_ids)."""
    counts = {"anchored": 0, "fallback": 0, "malformed": 0}
    samples: list[str] = []
    law_ids: set[str] = set()
    with documents_path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("law_id"):
                law_ids.add(row["law_id"])
            if not is_article_row(row):
                continue
            verdict = classify(row.get("source_url"), row.get("law_id"))
            counts[verdict] += 1
            if verdict == "malformed" and len(samples) < 10:
                samples.append(f"{row.get('juri_id')}: {row.get('source_url')!r}")
    return counts, samples, law_ids


def check_coverage(cache_dir: Path, law_ids: set[str]) -> list[str]:
    """Law_ids in the ledger that have no tracked source XML."""
    return sorted(lid for lid in law_ids if not (cache_dir / f"{lid}.xml").exists())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--documents", type=Path, default=_REPO / "build" / "registry" / "documents.jsonl"
    )
    p.add_argument("--cache-dir", type=Path, default=_REPO / "cache" / "laws")
    args = p.parse_args()

    if not args.documents.exists():
        print(f"ERROR: documents.jsonl not found: {args.documents}", file=sys.stderr)
        return 1

    counts, samples, law_ids = check_documents(args.documents)
    missing = check_coverage(args.cache_dir, law_ids)
    total = sum(counts.values())

    print("== source_url anchor gate ==")
    print(f"statute-layer article documents : {total}")
    print(f"  anchored (per-article)        : {counts['anchored']}")
    print(f"  law-level fallback            : {counts['fallback']}")
    print(f"  malformed                     : {counts['malformed']}")
    print(f"laws in ledger                  : {len(law_ids)}")
    print(f"laws missing tracked source XML : {len(missing)}")

    failed = False
    if counts["malformed"]:
        print(f"FAIL: {counts['malformed']} malformed source_url", file=sys.stderr)
        for s in samples:
            print(f"  {s}", file=sys.stderr)
        failed = True
    if missing:
        print(f"FAIL: {len(missing)} law(s) without tracked XML: {missing}", file=sys.stderr)
        failed = True
    if failed:
        return 1

    print("OK: all statute-layer article source_url well-formed; XML coverage complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

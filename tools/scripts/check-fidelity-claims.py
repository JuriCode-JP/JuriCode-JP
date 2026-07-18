#!/usr/bin/env python3
"""check-fidelity-claims.py -- machine-check the outward fidelity-claims ledger.

Why (VA-6 / C-FID):
    JuriCode-JP makes fidelity claims on its outward README ("the body equals the
    e-Gov XML modulo whitespace", "ruby readings removed"). A claim is only
    trustworthy if a gate actually enforces it. gates/fidelity-claims.json is the
    ledger that ties each claim to the G0 counters that gate it; this script keeps
    that ledger honest by checking:

      0. the core claims are present -- a gutted ledger (one with a claim quietly
         deleted) fails here, so the ledger cannot be hollowed out to dodge a red,
      1. every cited gate_id is in gates/g0-classification.json's violation set --
         a claim cannot cite a counter that does not gate,
      2. every readme_anchor still appears on the outward README, resilient to
         markdown decoration and whitespace but sensitive to wording changes, so
         the ledger stays in sync with the surface it describes,
      3. every enforced_by path exists.

    This gate does NOT touch gate logic or thresholds. Changing the ledger is an
    owner decision (gates/ is owner-reviewed), not a fix for a red build. Future
    hardening candidate: grep-match that enforced_by actually computes the cited
    counter (deferred -- counter names may not appear as literals in the enforcing
    script, which would false-fail).

exit 0: the ledger is consistent with the counters and the README.
exit 1: one or more violations (listed on stderr).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Claims that must always be present. Deleting one to dodge a red build is itself
#: a structural violation (a gutted ledger is not a passing ledger).
REQUIRED_CLAIM_IDS = ("body-equals-egov", "no-ruby-contamination")

#: Markdown inline emphasis / code characters, dropped before substring matching so
#: an anchor still matches when the README wraps it in **bold**, _em_, or `code`.
#: Wording changes still show through, because the anchor text itself is compared.
_DECORATION = re.compile(r"[*_`]")
_WHITESPACE = re.compile(r"\s+")


def _norm(s: str) -> str:
    """Drop markdown decoration and all whitespace, for resilient substring matching.

    Whitespace is removed, not collapsed to a single space: Japanese has no word
    spaces, so an anchor written without them ("...除いて完全に一致") must still match
    a README that happens to carry stray spaces or a line wrap inside the phrase.
    English anchors lose their spaces on both sides identically, so they still match;
    a genuine wording change ("完全に一致" -> "完全一致") still shows through.
    """
    return _WHITESPACE.sub("", _DECORATION.sub("", s))


def find_claim_violations(
    claims: list[dict], violation_set: set[str], readme_text: str, repo_root: Path
) -> list[str]:
    """Return an English description for each ledger inconsistency (empty == clean).

    Messages are keyed on the ASCII claim_id / gate_id / anchor index, so the report
    is cp932-console-safe without mangling any Japanese to \\uXXXX escapes.
    """
    problems: list[str] = []

    # 0. core claims present (gutted-ledger guard).
    present = {c.get("claim_id") for c in claims}
    for required in REQUIRED_CLAIM_IDS:
        if required not in present:
            problems.append(f"structural: required claim {required!r} is missing from the ledger")

    norm_readme = _norm(readme_text)
    for claim in claims:
        cid = claim.get("claim_id", "<no claim_id>")

        # 1. every cited gate_id actually gates.
        for gid in claim.get("gate_ids", []):
            if gid not in violation_set:
                problems.append(
                    f"claim {cid!r}: gate_id {gid!r} is not in the g0-classification violation set"
                )

        # 2. every anchor still appears on the README (decoration/whitespace resilient).
        for i, anchor in enumerate(claim.get("readme_anchors", [])):
            if _norm(anchor) not in norm_readme:
                problems.append(f"claim {cid!r}: readme_anchor[{i}] not found in README")

        # 3. enforced_by path exists.
        enforced_by = claim.get("enforced_by")
        if not enforced_by or not (repo_root / enforced_by).exists():
            problems.append(f"claim {cid!r}: enforced_by path {enforced_by!r} does not exist")

    return problems


def _emit(line: str) -> None:
    """Write a line to stderr without a cp932 console crash (keeps any JP readable)."""
    sys.stderr.buffer.write(line.encode("utf-8", errors="backslashreplace") + b"\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check the fidelity-claims ledger against the G0 counters and the README."
    )
    ap.add_argument("--repo", type=Path, default=REPO, help="repository root (default: this repo)")
    args = ap.parse_args(argv)
    repo_root = args.repo

    classification = json.loads(
        (repo_root / "gates" / "g0-classification.json").read_text(encoding="utf-8")
    )
    violation_set = set(classification.get("violation", []))
    ledger = json.loads((repo_root / "gates" / "fidelity-claims.json").read_text(encoding="utf-8"))
    claims = ledger.get("claims", [])
    readme_text = (repo_root / "README.md").read_text(encoding="utf-8")

    problems = find_claim_violations(claims, violation_set, readme_text, repo_root)
    if problems:
        _emit("FAIL: the fidelity-claims ledger is inconsistent:")
        for p in problems:
            _emit(f"  {p}")
        return 1

    print(
        f"fidelity-claims gate passed ({len(claims)} claim(s); "
        "every gate_id gates, every anchor is on the README)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

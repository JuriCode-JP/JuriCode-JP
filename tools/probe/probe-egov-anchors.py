#!/usr/bin/env python3
"""Probe: do the built anchors actually resolve to the intended article?

NOT a CI gate -- this needs the network and a real browser, and CI must stay
deterministic and offline. The offline half lives in
tools/validate/check-source-url-anchors.py (shape + source coverage); this is
the half that can catch a well-formed link pointing at the wrong article.

Why a headless browser and not curl: a fragment is never sent to the server
(RFC 3986 sec. 3.5) and laws.e-gov.go.jp renders its articles client-side, so
the response body is identical for every anchor. An HTTP 200 therefore proves
nothing beyond what the offline gate already proved. The check here is:
render the page at the anchor, then assert the fragment names a real element
and that element is the article we meant.

Two measurement traps this script avoids, both of which produced false
"everything passes" readings during C-1:

  * The SPA keeps its scroll position across in-page navigations, so each case
    loads about:blank first. Without that, a later case inherits the previous
    case's scroll and every anchor looks like it worked.
  * "Is it visible" alone is not enough -- an anchor that does not exist can
    still leave the target on screen. Element existence is asserted separately.

Usage (requires: pip install playwright && playwright install chromium):
    python tools/probe/probe-egov-anchors.py
    python tools/probe/probe-egov-anchors.py --law 340AC0000000034 --article 132-2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools" / "registry"))

from egov_anchor_index import build_anchor_index, to_egov_article_key  # noqa: E402

BASE_URL = "https://laws.e-gov.go.jp/law/{law_id}"

#: Sample set locked by the plan: every shape that could break the rule.
#: (law_id, article_number(registry form), why this case exists)
DEFAULT_SAMPLE = [
    ("129AC0000000089", "1", "平条 (民法)"),
    ("129AC0000000089", "424", "目(Di)まで入れ子"),
    ("340AC0000000034", "22", "節/款入れ子"),
    ("340AC0000000034", "132-2", "単一枝番"),
    ("340AC0000000034", "142-2-2", "二重枝番"),
    ("340AC0000000034", "22-2", "枝番 + 目(Di)"),
    ("340AC0000000034", "4-2", "枝番の章 (Ch_2_2)"),
    ("325M50000040017", "1", "平坦法令 (編章なし)"),
    ("325M50000040017", "1-2", "平坦法令 + 枝番"),
    ("325CO0000000245", "48-9-7-2", "三重枝番 (施行令)"),
    ("325AC0000000226", "193", "削除条 (本文が「削除」のみ)"),
    ("325AC0000000226", "19-3", "削除条 + 枝番"),
]


def check_one(page, law_id: str, article_number: str, anchor: str) -> tuple[bool, str]:
    """Load the anchored URL and report whether it lands on the intended article."""
    url = BASE_URL.format(law_id=law_id) + "#" + anchor
    page.goto("about:blank")  # drop any inherited scroll position
    page.goto(url, wait_until="networkidle", timeout=180_000)
    page.wait_for_timeout(6_000)
    result = page.evaluate(
        """(anchor) => {
            const el = document.getElementById(anchor);
            if (!el) return {exists: false, onScreen: false, top: null};
            const top = Math.round(el.getBoundingClientRect().top);
            return {exists: true, onScreen: top > -50 && top < 900, top};
        }""",
        anchor,
    )
    if not result["exists"]:
        return False, f"fragment names no element (id={anchor!r} absent)"
    if not result["onScreen"]:
        return False, f"element exists but page did not land on it (top={result['top']})"
    return True, f"resolved (top={result['top']})"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cache-dir", type=Path, default=_REPO / "cache" / "laws")
    p.add_argument("--law", help="single law_id to probe (default: the locked sample)")
    p.add_argument("--article", help="single article_number, registry form (e.g. 132-2)")
    args = p.parse_args()

    if bool(args.law) != bool(args.article):
        print("ERROR: --law and --article must be given together", file=sys.stderr)
        return 2
    sample = [(args.law, args.article, "ad-hoc")] if args.law else DEFAULT_SAMPLE

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERROR: playwright not installed "
            "(pip install playwright && playwright install chromium)",
            file=sys.stderr,
        )
        return 2

    indexes: dict[str, dict[str, str]] = {}
    failures = 0
    skipped = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        for law_id, article_number, why in sample:
            if law_id not in indexes:
                xml_path = args.cache_dir / f"{law_id}.xml"
                if not xml_path.exists():
                    print(f"SKIP {law_id} {article_number:<10} no tracked XML  [{why}]")
                    skipped += 1
                    continue
                indexes[law_id] = build_anchor_index(xml_path)
            anchor = indexes[law_id].get(to_egov_article_key(article_number))
            if anchor is None:
                # Not a probe failure: the builder deliberately falls back here,
                # and the offline gate counts it. Report it, never hide it.
                print(f"SKIP {law_id} {article_number:<10} falls back to law-level  [{why}]")
                skipped += 1
                continue
            ok, detail = check_one(page, law_id, article_number, anchor)
            status = "PASS" if ok else "FAIL"
            failures += not ok
            print(f"{status} {law_id} {article_number:<10} {anchor:<40} {detail}  [{why}]")
        browser.close()

    print(f"\n{len(sample) - skipped - failures} passed, {failures} failed, {skipped} skipped")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

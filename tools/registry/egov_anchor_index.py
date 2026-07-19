#!/usr/bin/env python3
"""Deterministic e-Gov article-anchor index (per-article deep links).

Why this module exists: ``documents.jsonl`` used to carry a LAW-level
``source_url`` (``https://laws.e-gov.go.jp/law/<law_id>``), so every citation
landed a reader at the top of a multi-thousand-article statute. e-Gov does
expose per-article fragments, but the anchor is NOT derivable from
``law_id`` + ``article_number``: it is the article's position in the document
tree. Measured on the rendered DOM (2026-07-20):

    Mp[-Pa_<編>][-Ch_<章>][-Se_<節>][-Ss_<款>][-Di_<目>]-At_<条>

    法人税法 第132条の2          Mp-Pa_2-Ch_5-At_132_2
    民法 第424条 (目まで入れ子)   Mp-Pa_3-Ch_1-Se_2-Ss_3-Di_1-At_424
    所得税法施行規則 第1条の2      Mp-At_1_2          (編章のない法令)

Only the FULL path resolves: partial anchors (``#At_132_2``) and paths with a
wrong hierarchy do not resolve at all. Laws without 編/章 shorten the path --
dummy levels must never be inserted.

Where the hierarchy comes from: the tracked source XML under ``cache/laws/``
(``.gitignore`` keeps ``/cache/*`` out but re-includes ``!/cache/laws/``), the
same bytes ``build_registry.load_law_nums`` already reads and the manifests
pin by sha256. Nothing here touches ``data/`` markdown, the parser, or the
corpus -- this is a citation-quality change, not a fidelity change, so
``hash_basis``/``text_sha256`` are untouched.

Two notation details that silently break naive implementations:

  * Branch numbers live in the raw ``Num`` attribute with ``_`` separators
    (``<Article Num="4_2">``, ``<Chapter Num="2_2">``). ``Num`` must NEVER be
    coerced to int -- ``int("2_2")`` raises and any fallback invents a wrong
    level. Keys are therefore kept in e-Gov's own notation; callers translate
    the registry's ``-`` form back to ``_`` at lookup time.
  * The XML has no ``eId``/``id`` attributes (measured: zero occurrences), so
    the path must be constructed from the structure; there is nothing to read.

Supplementary provisions live in a separate namespace
(``<amending_law_id>-Sp-At_<N>``) and are deliberately out of scope: only
``MainProvision`` is walked, which also makes the bare article number
unambiguous (``At_22`` occurs once in 本則 but 12 more times across 附則).
"""

from __future__ import annotations

import warnings
from pathlib import Path

#: XML structure element -> e-Gov anchor abbreviation. Measured on the
#: rendered DOM; ``Division`` is ``Di`` (not ``Dv``), and getting it wrong
#: silently breaks every article nested under a 目.
STRUCTURE_ABBREV = {
    "Part": "Pa",
    "Chapter": "Ch",
    "Section": "Se",
    "Subsection": "Ss",
    "Division": "Di",
}

#: MainProvision (本則) namespace prefix. 附則 use ``<law_id>-Sp`` instead.
MAIN_PROVISION_PREFIX = "Mp"


class AnchorIndexError(RuntimeError):
    """Fatal anchor-index error (STOP condition). Never degrade to a warning."""


def _element_tree():
    """Prefer defusedxml (XXE / billion-laughs); same idiom as build_registry."""
    try:
        import defusedxml.ElementTree as ET
    except ImportError:  # pragma: no cover - CI installs defusedxml
        import xml.etree.ElementTree as ET

        warnings.warn(
            "defusedxml not installed; falling back to stdlib ElementTree",
            RuntimeWarning,
            stacklevel=3,
        )
    return ET


def to_egov_article_key(article_number: str) -> str:
    """Translate a registry ``article_number`` to e-Gov's raw ``Num`` notation.

    The parser normalises e-Gov's ``105_2`` to ``105-2`` for the IR spec
    (tools/parse/parse-egov.py). Reversing it is a whole-string replacement,
    which is safe because every ``article_number`` in the corpus is digits and
    hyphens only (forms ``N``, ``N-N``, ``N-N-N``, ``N-N-N-N``).
    """
    return article_number.replace("-", "_")


def build_anchor_index(xml_path: Path) -> dict[str, str]:
    """Map ``article_key`` (raw e-Gov ``Num``) -> anchor path, for one law.

    Walks ``MainProvision`` only, accumulating the abbreviation + raw ``Num``
    of each enclosing structure element. Articles nested directly under
    ``MainProvision`` yield the short ``Mp-At_<N>`` form.

    Ambiguous keys (the same article number reachable by two paths) are
    DROPPED rather than guessed, so the caller falls back to the law-level URL
    and the gate counts it. Silently picking one path could emit a link to the
    wrong article, which is worse than a coarse link.
    """
    ET = _element_tree()
    try:
        root = ET.parse(xml_path).getroot()
    except OSError as exc:
        raise AnchorIndexError(f"cannot read XML: {xml_path}: {exc}") from exc

    # Cached files are e-Gov API v2 <law_data_response> wrappers with <Law>
    # nested inside; older/synthetic files may have <Law> as the root.
    law_el = root if root.tag == "Law" else root.find(".//Law")
    if law_el is None:
        raise AnchorIndexError(f"no <Law> element in {xml_path}")
    main = law_el.find(".//LawBody/MainProvision")
    if main is None:
        raise AnchorIndexError(f"no <LawBody/MainProvision> in {xml_path}")

    index: dict[str, str] = {}
    ambiguous: set[str] = set()

    def walk(elem, path: list[str]) -> None:
        for child in elem:
            if child.tag == "Article":
                num = (child.get("Num") or "").strip()
                if not num:
                    continue  # no anchor is derivable; caller falls back
                anchor = "-".join([MAIN_PROVISION_PREFIX, *path, f"At_{num}"])
                if num in index and index[num] != anchor:
                    ambiguous.add(num)
                index[num] = anchor
            elif child.tag in STRUCTURE_ABBREV:
                num = (child.get("Num") or "").strip()
                if not num:
                    # A structure level we cannot name would produce a wrong
                    # path for everything beneath it; skip the whole subtree.
                    continue
                walk(child, [*path, f"{STRUCTURE_ABBREV[child.tag]}_{num}"])
            # Any other tag (AppdxTable, Preamble, ...) is not part of the
            # article hierarchy and is not descended into.

    walk(main, [])
    for num in ambiguous:
        index.pop(num, None)
    return index


def load_anchor_indexes(cache_dir: Path, law_ids: list[str]) -> dict[str, dict[str, str]]:
    """Build the anchor index for each law_id; missing XML yields no entry.

    A missing cache file is not fatal here -- it degrades those articles to the
    law-level URL, and the coverage gate
    (tools/validate/check-source-url-anchors.py) is what fails the build.
    """
    indexes: dict[str, dict[str, str]] = {}
    for law_id in sorted(set(law_ids)):
        xml_path = cache_dir / f"{law_id}.xml"
        if not xml_path.exists():
            continue
        indexes[law_id] = build_anchor_index(xml_path)
    return indexes


def resolve_article_anchor(
    anchor_index: dict[str, dict[str, str]],
    law_id: str,
    article_number_raw: str,
    base_url: str,
) -> tuple[str, bool]:
    """Return ``(url, anchored)`` for one article.

    ``anchored`` is returned explicitly rather than left for the caller to
    infer from ``url == base_url``: fallbacks must be counted, never silent.
    Falls back to ``base_url`` when the law has no index (XML absent), the
    article is not in 本則, or its key was dropped as ambiguous.
    """
    per_law = anchor_index.get(law_id)
    if not per_law:
        return base_url, False
    anchor = per_law.get(to_egov_article_key(article_number_raw))
    if not anchor:
        return base_url, False
    return f"{base_url}#{anchor}", True

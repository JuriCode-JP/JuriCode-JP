#!/usr/bin/env python3
"""Citation registry builder (W6 MVP): chunk -> canonical document ledger.

Builds two deterministic JSONL files under ``build/registry/`` (gitignored):

  documents.jsonl  -- one row per canonical DOCUMENT (not per chunk): source
                      metadata + content hash. This is the single ledger that
                      MCP ``get_article`` and the BQ exporter consume.
  chunks.jsonl     -- child -> parent mapping (chunk_id -> juri_id) for every
                      chunk in the retrieval corpus.

Why deterministic / LLM-free: the ledger is the anchor of the citation
verification chain (G2 quote check -> document hash -> external source).
Any nondeterminism here would produce false diff bursts and break audits,
so the build is pure file-in / file-out, sorted by ``juri_id``, and the CLI
builds twice and asserts byte identity before writing.

hash_basis (3 values -- never overstate what was verified):

  egov-xml-canonical   statute/enforcement articles. ``text_sha256`` is the
                       manifest ``ja_text_sha256`` copied VERBATIM (never
                       recomputed here). It was produced by the deterministic
                       e-Gov XML round-trip pipeline and is CI-verified
                       against the source (tools/parse/verify.py).
  egov-xml-derived     supplementary provisions (附則). Text also comes from
                       the deterministic e-Gov XML parse, but there is no
                       per-article manifest anchor for 附則 yet (FU-558), so
                       the hash is computed here over the stored chunk text.
  juricode-stored-text tsutatsu / taxanswer / ruling layers. sha256 of the
                       text WE ingested -- a self-declared fingerprint, NOT a
                       comparison against the publisher's original (FU-557).

Per-layer document text (= what ``get_article`` must return, byte-exact;
the registry hash is defined over exactly this string):

  statute/enforcement  canonical ja text anchored by the manifest hash
                       (recomputation for spot checks uses
                       tools/parse/verify.py extraction + _canonicalize).
  suppl (附則)         if the document has a ``-rollup`` chunk: that chunk's
                       ``text_raw`` verbatim; otherwise the ``text_raw`` of
                       its chunks joined with "\\n" in corpus file order.
  tsutatsu             store row ``text`` (store rows are directive-level).
  taxanswer            store row ``text`` (store rows are document-level;
                       ``-subN`` splitting exists only in the corpus).
  ruling               ``case_name_ja + "\\n" + summary_ja`` (K-1 lock; the
                       corpus text field matches this rule byte-for-byte
                       for all rulings, verified 2026-07-13).

Discipline (maintainer rulings, 2026-07-13):
  - No rglob over ``build/chunks``: stores are enumerated by explicit
    allow-list; unexpected store-shaped entries abort the build (stale
    caches such as ``build-chunks-backup`` are in a known-ignore list).
  - Missing metadata stays null and is COUNTED, never fabricated
    (tsutatsu/ruling have no version_date; ruling decision_date is kept as
    its own field, not a version_date substitute).
  - Document counts are asserted against locked expectations; any drift is
    a hard stop, not a silent re-baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# =====================================================
# Constants (locked; tests reference these directly)
# =====================================================

HASH_EGOV_CANONICAL = "egov-xml-canonical"
HASH_EGOV_DERIVED = "egov-xml-derived"
HASH_STORED_TEXT = "juricode-stored-text"

#: License label for e-Gov statute text, exactly as named by docs/licensing.md
#: ("法令本文 / e-Gov" section). Deliberately NOT "政府標準利用規約" -- the
#: verified in-repo licensing doc names the e-Gov terms, and this ledger must
#: not assert a license the licensing doc does not.
LICENSE_EGOV = "e-Gov利用規約"

#: Explicit store allow-list under build/chunks (no rglob -- see module doc).
TAXANSWER_STORES = (
    "gensen-taxanswer",
    "hojin-taxanswer",
    "inshi-taxanswer",
    "joto-taxanswer",
    "shohi-taxanswer",
    "shotoku-taxanswer",
    "sozoku-taxanswer",
)
TSUTATSU_STORE_DIRS = (
    "hojin-kihon-tsutatsu",
    "shouhi-kihon-tsutatsu",
    "zaisan-hyoka-kihon-tsutatsu",
    "sochi-40jou-tsutatsu",
    "sochi-gensen-tsutatsu",
    "sochi-hojin-tsutatsu",
    "sochi-joto-tsutatsu",
    "sochi-kabushiki-tsutatsu",
    "sochi-shotoku-tsutatsu",
    "sochi-sozoku-tsutatsu",
)
#: Two tsutatsu stores live as top-level FILES under build/chunks (historical).
TSUTATSU_STORE_FILES = (
    "shotoku-kihon-tsutatsu.tsutatsu.chunks.jsonl",
    "souzoku-kihon-tsutatsu.tsutatsu.chunks.jsonl",
)
KFS_STORE_DIRS = ("kfs-hojin", "kfs-kokutsu", "kfs-shohi", "kfs-shotoku", "kfs-sozoku")

#: Entries under build/chunks that LOOK store-shaped but are known non-stores.
#: Why: rglob once ingested stale caches; anything store-shaped that is
#: neither allow-listed nor listed here aborts the build (fail-loud).
KNOWN_IGNORED_ENTRIES = frozenset({"build-chunks-backup"})

#: Locked document-count expectations (measured 2026-07-13, maintainer
#: adjudication). Drift = STOP; update only with maintainer approval.
EXPECTED_COUNTS = {
    "articles": 16332,  # manifest article total (statute + enforcement)
    "taxanswer": 656,
    "tsutatsu": 5135,
    "ruling": 13,
}

#: segment_types that are intentionally absent from the embed index. These are
#: the ``-rollup`` aggregation chunks: build_v8_corpus S-1 marks them
#: ``embed_skip=True`` because their body text is the sum of child (項/号) chunks
#: which ARE embedded individually, so embedding the rollup too would be
#: redundant. filter_v8_embed drops exactly these + empty-text rows. This is the
#: ONLY non-empty-text category allowed to be missing from the index -- see
#: ``assert_embed_exclusions``.
EMBED_SKIP_SEGMENT_TYPES = frozenset({"rollup", "supplproviso_rollup"})

#: Layers whose document text is the store row verbatim. The dispatch key for
#: the text resolver: these use the store text, the rest are re-derived from
#: e-Gov XML keyed by hash_basis.
_STORED_LAYERS = frozenset({"tsutatsu", "taxanswer", "ruling"})

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
#: Sub-article unit suffixes on 附則 chunk ids (項/分割/表/列/rollup)。
_SUPPL_UNIT_SUFFIX_RE = re.compile(r"(?:-p\d+|-sub\d+|-tbl\d+|-w\d+|-rollup)+$")
#: Shape of a valid 附則 document id after stripping unit suffixes. The art
#: token may be a RANGE ("art39:40", "art5_2:5_3"): e-Gov range Nums appear
#: as single 附則 units in the corpus (6 chunks, measured 2026-07-13); the
#: colon is kept verbatim in the juri_id (faithful to the chunk id).
_SUPPL_DOC_RE = re.compile(r"^[a-z0-9-]+-supplproviso-[0-9_]+(?:-art[0-9_]+(?::[0-9_]+)?)?$")
_TAXANSWER_SUB_RE = re.compile(r"-sub\d+$")


class RegistryError(RuntimeError):
    """Fatal build error (STOP condition). Never degrade to a warning."""


@dataclass(frozen=True)
class RegistryPaths:
    """Input/output locations. All reads are confined to these roots."""

    data_dir: Path
    cache_dir: Path
    chunks_dir: Path
    corpus_path: Path
    embed_path: Path
    out_dir: Path


@dataclass
class BuildReport:
    """Per-layer breakdown reported to the operator (DoD requirement)."""

    docs_by_layer: dict[str, int] = field(default_factory=dict)
    chunks_by_layer: dict[str, int] = field(default_factory=dict)
    docs_by_hash_basis: dict[str, int] = field(default_factory=dict)
    null_source_url: int = 0
    null_version_date: int = 0
    law_num_duplicate_values: int = 0
    suppl_docs: int = 0
    suppl_chunks: int = 0
    articles_not_in_corpus: int = 0
    #: 旧索引にあって新 corpus に無い chunk_id の数。索引が corpus より古いときだけ
    #: 非ゼロになる (index_coverage="measure" のとき集計され、"assert" では 0 か STOP)。
    stale_index_chunk_ids: int = 0
    #: corpus にあって索引に無い chunk の内訳 (逆方向ゲート assert_embed_exclusions)。
    #: index_coverage="assert" のときだけ算出。measure では None のまま。
    embed_exclusions: dict[str, int] | None = None


# =====================================================
# ID normalization / 附則 document derivation (pure)
# =====================================================


def normalize_article_id(article_id: str) -> str:
    """Fold corpus branch-number underscores into manifest hyphens.

    Why: 156 corpus article_ids write 条枝番 as ``art-144_3`` while the
    manifest canonically writes ``art-144-3`` (measured 2026-07-13; the
    mapping resolves all 156 with zero ambiguity). The manifest form is
    canonical, so the corpus form is normalized on the way in.
    """
    return article_id.replace("_", "-")


def suppl_doc_id(chunk_id: str) -> str:
    """Derive the 附則 document id (条 unit) from a supplproviso chunk id.

    Maintainer rule: drop the 項-and-below suffix. ``...-art1-p1`` -> ``...-art1``;
    group-direct chunks (``...-supplproviso-71-p1-sub2``) and the group rollup
    both collapse to the group id. Unparseable shapes are a hard stop --
    silently guessing a parent would corrupt the ledger.
    """
    doc = _SUPPL_UNIT_SUFFIX_RE.sub("", chunk_id)
    if not _SUPPL_DOC_RE.match(doc):
        raise RegistryError(f"unrecognized supplproviso chunk id shape: {chunk_id!r}")
    return doc


def ruling_doc_text(case_name_ja: str, summary_ja: str) -> str:
    """K-1 locked ruling document text: case name + newline + summary."""
    return f"{case_name_ja}\n{summary_ja}"


def sha256_text(text: str) -> str:
    """sha256 hex of the exact stored text (no normalization, by design)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def suppl_doc_text(chunks_in_corpus_order: list[dict]) -> str:
    """Document text for one 附則 document (see module doc for the rule).

    Why rollup-wins: the ``-rollup`` chunk is the XML-derived full text of the
    附則 group and is the only chunk at group level when 条 substructure
    exists; joining paragraph chunks would double-count against it.
    """
    rollups = [c for c in chunks_in_corpus_order if c["chunk_id"].endswith("-rollup")]
    if len(rollups) > 1:
        ids = [c["chunk_id"] for c in rollups]
        raise RegistryError(f"multiple rollup chunks for one 附則 document: {ids}")
    if rollups:
        return rollups[0]["text_raw"]
    return "\n".join(c["text_raw"] for c in chunks_in_corpus_order)


# =====================================================
# Input loaders (each confined to one source)
# =====================================================


def scan_store_allowlist(chunks_dir: Path) -> None:
    """Abort if a store-shaped entry exists outside the explicit allow-list.

    Why: the review adjudication banned rglob after a stale cache directory
    (``build-chunks-backup``) was found inside ``build/chunks``. This scan is
    the belt-and-suspenders companion: a NEW store dropped next to the
    allow-listed ones must fail loudly instead of being silently skipped.
    """
    allowed = (
        set(TAXANSWER_STORES)
        | set(TSUTATSU_STORE_DIRS)
        | set(KFS_STORE_DIRS)
        | set(TSUTATSU_STORE_FILES)
    )
    unexpected: list[str] = []
    for entry in sorted(chunks_dir.iterdir(), key=lambda p: p.name):
        name = entry.name
        if name in allowed or name in KNOWN_IGNORED_ENTRIES:
            continue
        # Layer-store markers. Per-law statute chunk dirs (keihou/ etc.) carry
        # none of these in their names and are intentionally not read.
        looks_store = (
            name.endswith("-taxanswer")
            or ".taxanswer." in name
            or "tsutatsu" in name
            or name.startswith("kfs-")
            or ".saiketsu." in name
        )
        if looks_store:
            unexpected.append(name)
    if unexpected:
        raise RegistryError(
            "store-shaped entries outside the allow-list (stale cache or "
            f"unregistered store?): {unexpected} -- refusing to guess"
        )


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_manifests(data_dir: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load all _source-manifest.json files.

    Returns:
        (laws, articles): ``laws`` maps law_abbrev -> manifest header,
        ``articles`` maps article_id -> manifest entry + law linkage.
    """
    laws: dict[str, dict] = {}
    articles: dict[str, dict] = {}
    manifest_paths = sorted(data_dir.rglob("_source-manifest.json"))
    if not manifest_paths:
        raise RegistryError(f"no manifests under {data_dir}")
    for mp in manifest_paths:
        m = json.loads(mp.read_text(encoding="utf-8"))
        abbrev = m["law_abbrev"]
        laws[abbrev] = {**m, "_dir": mp.parent}
        for a in m["articles"]:
            aid = a["article_id"]
            if aid in articles:
                raise RegistryError(f"duplicate article_id across manifests: {aid}")
            if not _SHA256_HEX_RE.match(a["ja_text_sha256"]):
                raise RegistryError(f"malformed ja_text_sha256 for {aid}")
            articles[aid] = {**a, "law_abbrev": abbrev}
    return laws, articles


def load_frontmatter_meta(laws: dict[str, dict], articles: dict[str, dict]) -> dict[str, dict]:
    """Read source_url / version_date / last_verified from each article's md.

    Why frontmatter (not manifest): the maintainer designated frontmatter as
    the per-article source for these fields; version_date can diverge from
    the law-level manifest value after amendment updates.
    """
    import yaml  # lazy: not needed for --help

    fm_re = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
    meta: dict[str, dict] = {}
    for aid, entry in articles.items():
        md_path = laws[entry["law_abbrev"]]["_dir"] / entry["filename"]
        m = fm_re.match(md_path.read_text(encoding="utf-8"))
        if not m:
            raise RegistryError(f"missing frontmatter: {md_path}")
        fm = yaml.safe_load(m.group(1)) or {}
        meta[aid] = {
            "source_url": fm.get("source_url"),
            "version_date": str(fm["version_date"]) if fm.get("version_date") else None,
            "last_verified": str(fm["last_verified"]) if fm.get("last_verified") else None,
        }
    return meta


def load_law_nums(cache_dir: Path, laws: dict[str, dict]) -> tuple[dict[str, str], int]:
    """Extract <LawNum> per law_id from the cached e-Gov XML.

    Asserts law_id -> law_num is single-valued (exactly one direct LawNum
    element). Duplicate law_num VALUES across different law_ids are a WARN
    with a count, not fatal (maintainer adjudication: the BQ exporter, where
    law_num is a key, owns the fatal check).
    """
    # Security: prefer defusedxml (XXE / billion-laughs); same idiom as
    # tools/parse/parse-egov.py.
    try:
        import defusedxml.ElementTree as ET
    except ImportError:  # pragma: no cover - CI installs defusedxml
        import xml.etree.ElementTree as ET

        warnings.warn(
            "defusedxml not installed; falling back to stdlib ElementTree",
            RuntimeWarning,
            stacklevel=2,
        )

    law_nums: dict[str, str] = {}
    for abbrev in sorted(laws):
        law_id = laws[abbrev]["law_id"]
        xml_path = cache_dir / f"{law_id}.xml"
        if not xml_path.exists():
            raise RegistryError(f"cached XML missing for {abbrev}: {xml_path}")
        root = ET.parse(xml_path).getroot()
        # Cached files are e-Gov API v2 <law_data_response> wrappers with the
        # <Law> element nested inside; older/synthetic files may have <Law>
        # as the root. The single-value assert is defined at the Law level
        # (direct children only -- amendment text never nests LawNum there).
        law_el = root if root.tag == "Law" else root.find(".//Law")
        if law_el is None:
            raise RegistryError(f"law_id {law_id}: no <Law> element in {xml_path}")
        nums = law_el.findall("LawNum")
        if len(nums) != 1 or not (nums[0].text or "").strip():
            raise RegistryError(f"law_id {law_id}: expected exactly one non-empty <LawNum>")
        law_nums[law_id] = nums[0].text.strip()
    value_counts: dict[str, int] = {}
    for v in law_nums.values():
        value_counts[v] = value_counts.get(v, 0) + 1
    dup_values = sum(1 for c in value_counts.values() if c > 1)
    if dup_values:
        warnings.warn(
            f"{dup_values} law_num value(s) shared by multiple law_ids (WARN only; "
            "the BQ exporter must treat this as fatal)",
            RuntimeWarning,
            stacklevel=2,
        )
    return law_nums, dup_values


def load_corpus(corpus_path: Path) -> list[dict]:
    """Load the retrieval corpus, keeping only the fields the ledger needs."""
    keep_common = ("chunk_id", "layer", "segment_type")
    rows: list[dict] = []
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            row = {k: r.get(k) for k in keep_common}
            # Mirror filter_v8_embed EXACTLY: a row is embed-excluded on empty
            # text via ``(text or "").strip()``. Captured here so the reverse
            # exclusion gate can distinguish empty-text drops from unexpected
            # ones without re-reading the corpus.
            row["text_empty"] = not (r.get("text") or "").strip()
            lay = row["layer"]
            if lay in ("statute", "enforcement"):
                row["article_id"] = r.get("article_id")
                row["law_id"] = r.get("law_id")
                if r.get("article_id") is None:
                    row["text_raw"] = r.get("text_raw", "")
            elif lay == "tsutatsu":
                row["directive_id"] = r.get("directive_id")
            elif lay == "ruling":
                row["case_id"] = r.get("case_id")
            elif lay != "taxanswer":
                raise RegistryError(f"unknown layer in corpus: {lay!r} ({row['chunk_id']})")
            rows.append(row)
    if not rows:
        raise RegistryError(f"empty corpus: {corpus_path}")
    return rows


def load_taxanswer_stores(chunks_dir: Path) -> dict[str, dict]:
    """Document-level taxanswer rows keyed by store id (== doc juri_id)."""
    docs: dict[str, dict] = {}
    for name in TAXANSWER_STORES:
        for r in _read_jsonl(chunks_dir / name / f"{name}.taxanswer.chunks.jsonl"):
            if r["id"] in docs:
                raise RegistryError(f"duplicate taxanswer store id: {r['id']}")
            docs[r["id"]] = r
    return docs


def load_tsutatsu_stores(chunks_dir: Path) -> dict[str, dict]:
    """Directive-level tsutatsu rows keyed by directive_id."""
    docs: dict[str, dict] = {}
    paths = [chunks_dir / d / f"{d}.tsutatsu.chunks.jsonl" for d in TSUTATSU_STORE_DIRS]
    paths += [chunks_dir / f for f in TSUTATSU_STORE_FILES]
    for p in paths:
        for r in _read_jsonl(p):
            if r["directive_id"] in docs:
                raise RegistryError(f"duplicate tsutatsu directive_id: {r['directive_id']}")
            docs[r["directive_id"]] = r
    return docs


def load_ruling_stores(chunks_dir: Path) -> dict[str, dict]:
    """Ruling (裁決要旨) rows keyed by case_id, from kfs-*/*.saiketsu.jsonl."""
    docs: dict[str, dict] = {}
    for name in KFS_STORE_DIRS:
        for p in sorted((chunks_dir / name).glob("kfs-*.saiketsu.jsonl")):
            for r in _read_jsonl(p):
                if r["case_id"] in docs:
                    raise RegistryError(f"duplicate ruling case_id: {r['case_id']}")
                docs[r["case_id"]] = r
    return docs


# =====================================================
# Document row assembly (one function per layer)
# =====================================================


def _doc_row(**kw: object) -> dict:
    """Uniform documents.jsonl row (fixed key order = byte determinism)."""
    row = {
        "juri_id": None,
        "layer": None,
        "law_id": None,
        "law_num": None,
        "law_name_ja": None,
        "article_number": None,
        "version_date": None,
        "decision_date": None,
        "source_url": None,
        "text_sha256": None,
        "hash_basis": None,
        "license": None,
        "last_verified": None,
    }
    unknown = set(kw) - set(row)
    if unknown:
        raise RegistryError(f"unknown document fields: {unknown}")
    row.update(kw)
    return row


def build_article_documents(
    laws: dict[str, dict],
    articles: dict[str, dict],
    fm_meta: dict[str, dict],
    law_nums: dict[str, str],
    layer_by_law: dict[str, str],
) -> list[dict]:
    """One document per manifest article (16,332 -- the canonical ledger,
    independent of what the current retrieval index happens to reference)."""
    out = []
    for aid, entry in articles.items():
        law = laws[entry["law_abbrev"]]
        fm = fm_meta[aid]
        out.append(
            _doc_row(
                juri_id=aid,
                layer=layer_by_law[law["law_id"]],
                law_id=law["law_id"],
                law_num=law_nums[law["law_id"]],
                law_name_ja=law["law_name_ja"],
                article_number=str(entry["article_number"]),
                version_date=fm["version_date"],
                source_url=fm["source_url"],
                text_sha256=entry["ja_text_sha256"],  # verbatim; never recomputed
                hash_basis=HASH_EGOV_CANONICAL,
                license=LICENSE_EGOV,
                last_verified=fm["last_verified"],
            )
        )
    return out


def build_suppl_documents(
    suppl_chunks_by_doc: dict[str, list[dict]],
    laws: dict[str, dict],
    law_nums: dict[str, str],
    layer_by_law: dict[str, str],
    law_source_url: dict[str, str],
) -> list[dict]:
    """One document per 附則 unit (group or 条). version_date stays null:
    附則 originate from amendment acts and the law-level date would be a
    fabrication (maintainer ruling)."""
    abbrev_by_law_id = {law["law_id"]: ab for ab, law in laws.items()}
    out = []
    for doc_id, chs in suppl_chunks_by_doc.items():
        law_ids = {c["law_id"] for c in chs}
        if len(law_ids) != 1 or None in law_ids:
            raise RegistryError(f"附則 doc {doc_id}: inconsistent law_id {law_ids}")
        law_id = next(iter(law_ids))
        if law_id not in abbrev_by_law_id:
            raise RegistryError(f"附則 doc {doc_id}: law_id {law_id} not in manifests")
        out.append(
            _doc_row(
                juri_id=doc_id,
                layer=layer_by_law[law_id],
                law_id=law_id,
                law_num=law_nums[law_id],
                law_name_ja=laws[abbrev_by_law_id[law_id]]["law_name_ja"],
                source_url=law_source_url.get(law_id),
                text_sha256=sha256_text(suppl_doc_text(chs)),
                hash_basis=HASH_EGOV_DERIVED,
                license=LICENSE_EGOV,
            )
        )
    return out


def build_tsutatsu_documents(store: dict[str, dict]) -> list[dict]:
    return [
        _doc_row(
            juri_id=did,
            layer="tsutatsu",
            law_name_ja=r.get("law_name_ja"),
            source_url=r.get("source_url"),
            text_sha256=sha256_text(r["text"]),
            hash_basis=HASH_STORED_TEXT,
            license=r.get("license"),
        )
        for did, r in store.items()
    ]


def build_taxanswer_documents(store: dict[str, dict]) -> list[dict]:
    return [
        _doc_row(
            juri_id=doc_id,
            layer="taxanswer",
            law_name_ja=r.get("law_name_ja"),
            version_date=r.get("version_date"),
            source_url=r.get("source_url"),
            text_sha256=sha256_text(r["text"]),
            hash_basis=HASH_STORED_TEXT,
            license=r.get("license"),
        )
        for doc_id, r in store.items()
    ]


def build_ruling_documents(store: dict[str, dict]) -> list[dict]:
    """Ruling docs. decision_date is its own field; version_date stays null
    (a decision date is not a text-version date -- maintainer ruling)."""
    return [
        _doc_row(
            juri_id=cid,
            layer="ruling",
            decision_date=r.get("decision_date"),
            source_url=r.get("url"),
            text_sha256=sha256_text(ruling_doc_text(r["case_name_ja"], r["summary_ja"])),
            hash_basis=HASH_STORED_TEXT,
            license=r.get("source_license"),
        )
        for cid, r in store.items()
    ]


# =====================================================
# Chunk mapping + invariants
# =====================================================


def map_chunk_to_doc(row: dict) -> str:
    """Resolve one corpus chunk to its parent juri_id (pure)."""
    lay = row["layer"]
    if lay in ("statute", "enforcement"):
        if row.get("article_id"):
            return normalize_article_id(row["article_id"])
        return suppl_doc_id(row["chunk_id"])
    if lay == "tsutatsu":
        derived = _TAXANSWER_SUB_RE.sub("", row["chunk_id"])
        if row.get("directive_id") != derived:
            raise RegistryError(
                f"tsutatsu chunk {row['chunk_id']}: directive_id "
                f"{row.get('directive_id')!r} != derived {derived!r}"
            )
        return row["directive_id"]
    if lay == "taxanswer":
        return _TAXANSWER_SUB_RE.sub("", row["chunk_id"])
    if lay == "ruling":
        return row["case_id"]
    raise RegistryError(f"unmappable layer: {lay!r}")


def assert_invariants(
    documents: list[dict],
    chunk_rows: list[dict],
    embed_ids: set[str],
    expected: dict[str, int],
    index_coverage: str = "assert",
) -> int:
    """Hard gates (§6): uniqueness, orphans, hash_basis presence, counts,
    embed-index coverage. Any failure is a STOP.

    index_coverage:
        "assert"  -- 索引の chunk_id が corpus に全て存在すること (既定)。
        "measure" -- 存在しない数を報告するだけ (索引が corpus より古い移行期用)。

    Returns:
        索引にあって corpus に無い chunk_id の数 (0 なら索引は corpus に追随している)。
    """
    doc_ids = [d["juri_id"] for d in documents]
    if len(doc_ids) != len(set(doc_ids)):
        seen: set[str] = set()
        dups: list[str] = []
        for i in doc_ids:
            if i in seen:
                dups.append(i)
            seen.add(i)
        raise RegistryError(f"duplicate juri_id in documents: {sorted(set(dups))[:10]}")
    doc_set = set(doc_ids)
    orphans = sorted({c["juri_id"] for c in chunk_rows} - doc_set)
    if orphans:
        raise RegistryError(f"orphan juri_id in chunks (first 10): {orphans[:10]}")
    missing_basis = [d["juri_id"] for d in documents if not d["hash_basis"] or not d["text_sha256"]]
    if missing_basis:
        raise RegistryError(f"documents missing hash_basis/text_sha256: {missing_basis[:10]}")
    chunk_ids = {c["chunk_id"] for c in chunk_rows}
    uncovered = sorted(embed_ids - chunk_ids)
    if uncovered:
        msg = (
            f"{len(uncovered)} embed-index chunk_ids missing from chunks.jsonl "
            f"(get_article coverage hole), first 5: {uncovered[:5]}"
        )
        if index_coverage == "assert":
            raise RegistryError(msg)
        # measure モード: 索引がまだ corpus に追いついていない移行期に使う。
        # Why: PR #138 で chunk が全面的に作り直され (枝番・号が入った)、旧索引 v8b の
        # chunk_id はもう新 corpus に存在しない。再 embed (索引 v9) ができるまでこの
        # assert は必ず落ちるが、それは索引が古いという既知の事実であって、
        # レジストリ側の欠陥ではない。**落として止めるのではなく、数を報告する**。
        # 索引を作り直したら assert モードに戻すこと。
        print(f"WARN [index-coverage=measure] {msg}", file=sys.stderr)
    got = {
        "articles": sum(1 for d in documents if d["hash_basis"] == HASH_EGOV_CANONICAL),
        "taxanswer": sum(1 for d in documents if d["layer"] == "taxanswer"),
        "tsutatsu": sum(1 for d in documents if d["layer"] == "tsutatsu"),
        "ruling": sum(1 for d in documents if d["layer"] == "ruling"),
    }
    for key, want in expected.items():
        if got[key] != want:
            raise RegistryError(f"document count drift for {key}: expected {want}, got {got[key]}")
    return len(uncovered)


def assert_embed_exclusions(corpus: list[dict], embed_ids: set[str]) -> dict[str, int]:
    """Gate the REVERSE direction: every corpus chunk absent from the embed
    index must be either a ``-rollup`` aggregation (embed_skip=True by design)
    or an empty-text chunk (nothing to embed). Anything else is a STOP.

    Why (maintainer ruling 2026-07-16): ``assert_invariants`` only checks
    ``embed ⊆ chunks`` (forward). A future parser change that stamps a BODY
    chunk ``embed_skip=True`` would silently drop it from search and sail
    through the forward gate -- the same class of hole as G0-e. This closes it:
    the one-off manual proof that the corpus/index row gap is EXACTLY
    ``{rollup, supplproviso_rollup} ∪ {empty-text}`` now runs on every build.

    Runs only when the index is current (index_coverage="assert"); a stale
    index (measure mode, e.g. mid chunk-rebuild) has an unrelated chunk_id
    universe and would make this gate meaningless.

    Args:
        corpus: rows from ``load_corpus`` (need ``chunk_id`` / ``segment_type``
            / ``text_empty``).
        embed_ids: chunk_ids actually present in the row-aligned embed corpus.

    Returns:
        Exclusion breakdown for the operator report (rollup_family / empty_text
        / total_gap). ``rollup_family + empty_text == total_gap`` by construction.
    """
    gap = [c for c in corpus if c["chunk_id"] not in embed_ids]
    unexpected = [
        c["chunk_id"]
        for c in gap
        if c["segment_type"] not in EMBED_SKIP_SEGMENT_TYPES and not c["text_empty"]
    ]
    if unexpected:
        raise RegistryError(
            f"{len(unexpected)} body chunk(s) in the corpus but absent from the embed "
            f"index, and neither a -rollup aggregation nor empty-text "
            f"(a body chunk marked embed_skip=True?), first 5: {sorted(unexpected)[:5]}"
        )
    rollup_family = sum(1 for c in gap if c["segment_type"] in EMBED_SKIP_SEGMENT_TYPES)
    # empty_text counts the non-rollup remainder so the two buckets partition
    # the gap exactly (a rollup chunk always carries its aggregated text).
    empty_text = len(gap) - rollup_family
    return {"rollup_family": rollup_family, "empty_text": empty_text, "total_gap": len(gap)}


# =====================================================
# Build orchestration
# =====================================================


def build_registry(
    paths: RegistryPaths,
    expected: dict[str, int] | None = None,
    index_coverage: str = "assert",
) -> tuple[bytes, bytes, BuildReport]:
    """Assemble both ledgers in memory. Returns (documents_bytes,
    chunks_bytes, report); writing is the caller's job so determinism can be
    proven by building twice and comparing bytes."""
    expected = expected if expected is not None else EXPECTED_COUNTS
    scan_store_allowlist(paths.chunks_dir)

    laws, articles = load_manifests(paths.data_dir)
    fm_meta = load_frontmatter_meta(laws, articles)
    law_nums, dup_values = load_law_nums(paths.cache_dir, laws)
    corpus = load_corpus(paths.corpus_path)

    layer_by_law: dict[str, str] = {}
    for row in corpus:
        if row["layer"] in ("statute", "enforcement") and row.get("law_id"):
            prev = layer_by_law.setdefault(row["law_id"], row["layer"])
            if prev != row["layer"]:
                raise RegistryError(f"law {row['law_id']} appears in two layers")
    missing_layer = [law["law_id"] for law in laws.values() if law["law_id"] not in layer_by_law]
    if missing_layer:
        raise RegistryError(f"laws absent from corpus (cannot infer layer): {missing_layer}")

    # 附則: group chunks by derived doc id, preserving corpus file order.
    suppl_by_doc: dict[str, list[dict]] = {}
    for row in corpus:
        if row["layer"] in ("statute", "enforcement") and not row.get("article_id"):
            suppl_by_doc.setdefault(suppl_doc_id(row["chunk_id"]), []).append(row)

    # Law-level source_url for 附則 docs = the (uniform) frontmatter value.
    law_source_url: dict[str, str] = {}
    for aid, entry in articles.items():
        law_id = laws[entry["law_abbrev"]]["law_id"]
        url = fm_meta[aid]["source_url"]
        prev = law_source_url.setdefault(law_id, url)
        if prev != url:
            raise RegistryError(f"law {law_id}: articles disagree on source_url")

    documents = (
        build_article_documents(laws, articles, fm_meta, law_nums, layer_by_law)
        + build_suppl_documents(suppl_by_doc, laws, law_nums, layer_by_law, law_source_url)
        + build_tsutatsu_documents(load_tsutatsu_stores(paths.chunks_dir))
        + build_taxanswer_documents(load_taxanswer_stores(paths.chunks_dir))
        + build_ruling_documents(load_ruling_stores(paths.chunks_dir))
    )
    documents.sort(key=lambda d: d["juri_id"])

    chunk_rows = [
        {
            "chunk_id": row["chunk_id"],
            "juri_id": map_chunk_to_doc(row),
            "layer": row["layer"],
            "segment_type": row["segment_type"],
        }
        for row in corpus
    ]
    chunk_rows.sort(key=lambda c: (c["juri_id"], c["chunk_id"]))
    cids = [c["chunk_id"] for c in chunk_rows]
    if len(cids) != len(set(cids)):
        raise RegistryError("duplicate chunk_id in corpus")

    embed_ids = {json.loads(line)["chunk_id"] for line in paths.embed_path.open(encoding="utf-8")}
    stale_index_ids = assert_invariants(
        documents, chunk_rows, embed_ids, expected, index_coverage=index_coverage
    )
    # Reverse gate: only meaningful when the index tracks the corpus. In measure
    # mode the index is stale (different chunk_id universe) so the gap is not the
    # {rollup ∪ empty} partition and the gate is skipped.
    embed_exclusions = (
        assert_embed_exclusions(corpus, embed_ids) if index_coverage == "assert" else None
    )

    report = BuildReport(law_num_duplicate_values=dup_values)
    report.stale_index_chunk_ids = stale_index_ids
    report.embed_exclusions = embed_exclusions
    for d in documents:
        report.docs_by_layer[d["layer"]] = report.docs_by_layer.get(d["layer"], 0) + 1
        report.docs_by_hash_basis[d["hash_basis"]] = (
            report.docs_by_hash_basis.get(d["hash_basis"], 0) + 1
        )
        report.null_source_url += d["source_url"] is None
        report.null_version_date += d["version_date"] is None
    for c in chunk_rows:
        report.chunks_by_layer[c["layer"]] = report.chunks_by_layer.get(c["layer"], 0) + 1
    report.suppl_docs = len(suppl_by_doc)
    report.suppl_chunks = sum(len(v) for v in suppl_by_doc.values())
    referenced = {c["juri_id"] for c in chunk_rows}
    report.articles_not_in_corpus = sum(1 for a in articles if a not in referenced)

    def to_bytes(rows: list[dict]) -> bytes:
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")

    return to_bytes(documents), to_bytes(chunk_rows), report


def _document_text_fn(paths: RegistryPaths):
    """Build ``f(doc) -> str`` re-deriving each document's text from source by
    the SAME per-layer rules the ledger hashes.

    Why one shared resolver: ``--sample-verify`` and ``--emit-texts`` must
    operate on the identical byte string, or texts.jsonl could ship text that
    does not hash to the ledger value the sampler blessed. statute/enforcement
    text is re-derived via tools/parse/verify.py extraction + _canonicalize (the
    CI round-trip path), NOT taken from the corpus ``text`` field.
    """
    import importlib.util

    parse_dir = _REPO / "tools" / "parse"
    if str(parse_dir) not in sys.path:
        sys.path.insert(0, str(parse_dir))
    spec = importlib.util.spec_from_file_location("_registry_verify", parse_dir / "verify.py")
    vf = importlib.util.module_from_spec(spec)
    # Register before exec: verify.py defines dataclasses under
    # `from __future__ import annotations`, whose field resolution looks the
    # module up in sys.modules (absent -> AttributeError).
    sys.modules["_registry_verify"] = vf
    spec.loader.exec_module(vf)

    laws, articles = load_manifests(paths.data_dir)
    dirs_by_abbrev = {ab: law["_dir"] for ab, law in laws.items()}
    tsut = load_tsutatsu_stores(paths.chunks_dir)
    taxa = load_taxanswer_stores(paths.chunks_dir)
    ruli = load_ruling_stores(paths.chunks_dir)
    corpus = load_corpus(paths.corpus_path)
    suppl_by_doc: dict[str, list[dict]] = {}
    for row in corpus:
        if row["layer"] in ("statute", "enforcement") and not row.get("article_id"):
            suppl_by_doc.setdefault(suppl_doc_id(row["chunk_id"]), []).append(row)

    def statute_text(doc: dict) -> str:
        entry = articles[doc["juri_id"]]
        md = dirs_by_abbrev[entry["law_abbrev"]] / entry["filename"]
        paragraphs = vf.extract_ja_paragraphs_from_md(md.read_text(encoding="utf-8"))
        return vf.canonicalize("\n\n".join(paragraphs))

    recompute = {
        HASH_EGOV_CANONICAL: statute_text,
        HASH_EGOV_DERIVED: lambda d: suppl_doc_text(suppl_by_doc[d["juri_id"]]),
    }
    stored = {
        "tsutatsu": lambda d: tsut[d["juri_id"]]["text"],
        "taxanswer": lambda d: taxa[d["juri_id"]]["text"],
        "ruling": lambda d: ruling_doc_text(
            ruli[d["juri_id"]]["case_name_ja"], ruli[d["juri_id"]]["summary_ja"]
        ),
    }

    def text_for(d: dict) -> str:
        fn = stored.get(d["layer"]) or recompute[d["hash_basis"]]
        return fn(d)

    return text_for


def sample_verify(paths: RegistryPaths, documents_bytes: bytes, per_layer: int = 20) -> int:
    """Recompute the document hash from the SOURCE for N samples per layer
    and compare against the emitted ledger via juricode_verifier.

    Why: the locked invariant is sha256(get_article text) == ledger value for
    every layer; this closes the chain on the real data at build time
    (statute recomputation goes through tools/parse/verify.py extraction +
    _canonicalize, i.e. the same path CI uses for round-trip checks).
    """
    verifier_src = _REPO / "packages" / "juricode-verifier" / "src"
    if str(verifier_src) not in sys.path:
        sys.path.insert(0, str(verifier_src))
    from juricode_verifier import verify_text_hash

    text_for = _document_text_fn(paths)
    docs = [json.loads(line) for line in documents_bytes.decode("utf-8").splitlines()]
    by_group: dict[str, list[dict]] = {}
    for d in docs:
        key = d["layer"] if d["layer"] in _STORED_LAYERS else d["hash_basis"]
        by_group.setdefault(key, []).append(d)
    checked = 0
    for _key, group in sorted(by_group.items()):
        for d in group[:per_layer]:  # docs are juri_id-sorted -> deterministic
            violation = verify_text_hash(text_for(d), d["text_sha256"])
            if violation is not None:
                raise RegistryError(f"sample verify failed for {d['juri_id']}: {violation.detail}")
            checked += 1
    return checked


def build_texts(paths: RegistryPaths, documents_bytes: bytes) -> bytes:
    """Emit the get_article payload store: one ``{juri_id, text}`` row per
    document, verifying sha256(text) == the ledger's text_sha256 for EVERY
    document (the full M6 equality, not a sample), sorted by juri_id.

    Why full verification: texts.jsonl is the byte string a consumer actually
    reads; the ledger hash is only trustworthy if the shipped text hashes to it.
    Any mismatch is a hard STOP (never ship text that fails its own hash).
    """
    verifier_src = _REPO / "packages" / "juricode-verifier" / "src"
    if str(verifier_src) not in sys.path:
        sys.path.insert(0, str(verifier_src))
    from juricode_verifier import verify_text_hash

    text_for = _document_text_fn(paths)
    # documents_bytes is already juri_id-sorted -> texts.jsonl inherits the order.
    docs = [json.loads(line) for line in documents_bytes.decode("utf-8").splitlines()]
    rows: list[dict] = []
    for d in docs:
        text = text_for(d)
        violation = verify_text_hash(text, d["text_sha256"])
        if violation is not None:
            raise RegistryError(f"texts hash mismatch for {d['juri_id']}: {violation.detail}")
        rows.append({"juri_id": d["juri_id"], "text": text})
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")


# =====================================================
# CLI
# =====================================================


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build the citation registry (W6 MVP).")
    p.add_argument("--data-dir", type=Path, default=_REPO / "data" / "v0.2")
    p.add_argument("--cache-dir", type=Path, default=_REPO / "cache" / "laws")
    p.add_argument("--chunks-dir", type=Path, default=_REPO / "build" / "chunks")
    p.add_argument("--corpus", type=Path, default=_REPO / "build" / "corpus-v9.jsonl")
    p.add_argument("--embed", type=Path, default=_REPO / "build" / "corpus-v9-embed.jsonl")
    p.add_argument("--out-dir", type=Path, default=_REPO / "build" / "registry")
    p.add_argument("--sample-verify", type=int, default=20, help="samples per layer (0=skip)")
    p.add_argument(
        "--index-coverage",
        choices=("assert", "measure"),
        default="assert",
        help=(
            "embed index chunk_ids must all exist in the corpus. "
            "'measure' only reports the shortfall -- use while the index is "
            "older than the corpus (e.g. after a chunk rebuild, until re-embed). "
            "Return to 'assert' once the index is rebuilt."
        ),
    )
    p.add_argument(
        "--emit-texts",
        action="store_true",
        help=(
            "also write texts.jsonl (one {juri_id, text} row per document), "
            "verifying sha256(text)==text_sha256 for EVERY document (full M6 "
            "equality). Heavy: re-derives statute text from every md."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    paths = RegistryPaths(
        data_dir=args.data_dir,
        cache_dir=args.cache_dir,
        chunks_dir=args.chunks_dir,
        corpus_path=args.corpus,
        embed_path=args.embed,
        out_dir=args.out_dir,
    )
    docs1, chunks1, report = build_registry(paths, index_coverage=args.index_coverage)
    docs2, chunks2, _ = build_registry(  # determinism gate (§5)
        paths, index_coverage=args.index_coverage
    )
    if docs1 != docs2 or chunks1 != chunks2:
        raise RegistryError("nondeterministic build: two runs differ byte-wise")
    if args.sample_verify:
        checked = sample_verify(paths, docs1, per_layer=args.sample_verify)
        print(f"sample-verify: {checked} documents re-hashed from source, all match")

    sys.path.insert(0, str(_REPO / "tools" / "shared" / "src"))
    from juricode_shared.safe_write import safe_write_text

    args.out_dir.mkdir(parents=True, exist_ok=True)
    safe_write_text(args.out_dir / "documents.jsonl", docs1.decode("utf-8"), newline="\n")
    safe_write_text(args.out_dir / "chunks.jsonl", chunks1.decode("utf-8"), newline="\n")

    n_texts = None
    if args.emit_texts:
        texts1 = build_texts(paths, docs1)
        texts2 = build_texts(paths, docs1)  # determinism gate (§5), same as documents/chunks
        if texts1 != texts2:
            raise RegistryError("nondeterministic texts build: two runs differ byte-wise")
        safe_write_text(args.out_dir / "texts.jsonl", texts1.decode("utf-8"), newline="\n")
        n_texts = texts1.count(b"\n")

    print("== registry build report ==")
    print(f"documents by layer      : {dict(sorted(report.docs_by_layer.items()))}")
    print(f"documents by hash_basis : {dict(sorted(report.docs_by_hash_basis.items()))}")
    print(f"chunks by layer         : {dict(sorted(report.chunks_by_layer.items()))}")
    print(f"附則 docs/chunks        : {report.suppl_docs} / {report.suppl_chunks}")
    print(f"null source_url         : {report.null_source_url}")
    print(f"null version_date       : {report.null_version_date}")
    print(f"law_num duplicate values: {report.law_num_duplicate_values}")
    print(f"manifest articles not referenced by corpus: {report.articles_not_in_corpus}")
    if report.embed_exclusions is not None:
        print(f"embed exclusions (corpus−index): {report.embed_exclusions}")
    else:
        print("embed exclusions (corpus−index): SKIPPED (index-coverage=measure)")
    if n_texts is not None:
        print(f"texts.jsonl             : {n_texts} rows, all sha256(text)==text_sha256")
    return 0


if __name__ == "__main__":
    sys.exit(main())

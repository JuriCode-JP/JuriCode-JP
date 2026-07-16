#!/usr/bin/env python3
"""build_snapshot.py -- generate ``snapshot.json`` for a distributed index+registry.

A snapshot is the name tag of a **self-contained flat distribution directory**::

    <snapshot>/
      snapshot.json          <- this file
      index/   <name>.npy | <name>.meta.jsonl | <name>.vec.json
      corpus/  row-aligned-corpus.jsonl        (= corpus-v9-embed.jsonl, 143,749)
      registry/ documents.jsonl | chunks.jsonl | texts.jsonl

The consumer downloads the directory and points ``JURICODE_SNAPSHOT_DIR`` at it;
every path in ``files`` is snapshot-relative (never ``build/...``). The MCP loader
reads ``snapshot.json`` at start-up and rejects any drift, so this generator's job
is to make the manifest describe the bytes that are actually shipped.

Contract rev.4 (maintainer, 2026-07-16) -- the exact shape MCP validates:
  - REQUIRED top-level keys: snapshot_id, pipeline_version, index, counts, files.
    (created_at and embed_exclusions are extra; MCP passes unknown top-level keys
    through.)
  - ``index`` = EXACTLY {index_name, embedding_model} (missing OR unexpected key
    is a load error). embedding_model is read from the index ``.vec.json``; the
    generator never writes the value itself.
  - ``counts`` = {documents, chunks, texts, index_rows}.
  - ``files`` = snapshot-relative path -> sha256, for the 7 shipped files. The
    ``.npy`` sha256 is over its FINAL patched bytes; snapshot.json itself and the
    (undistributed) full corpus are not listed, and ``.vec.pkl`` is never shipped
    (unpickling runs arbitrary code -- a verifiability product must not ask the
    consumer to trust a pickle).
  - ``pipeline_version`` is read from the source manifests and asserted single-valued.
  - ``embed_exclusions`` = the corpus-minus-index gap, split by reason. Every gap
    chunk must be a ``-rollup`` aggregation (embed_skip=True by design) or empty
    text; a BODY chunk in the gap is a STOP (the same G0-e-class hole the registry
    reverse gate guards).

Why deterministic: like the registry build, this is pure file-in / manifest-out.
The CLI builds the manifest twice and asserts byte identity before writing, so a
nondeterministic snapshot can never be published.

★ Ordering discipline (operator): patch the ``.npy`` to its final form FIRST, then
run this generator. The sha256 recorded here is a byte-level fingerprint of the
``.npy`` as it exists at generation time; a row-count-preserving byte change made
AFTER generation would not be caught at MCP start-up (only ``--verify-snapshot``
re-hashes), so the ``.npy`` must already be final.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# build_registry owns the definition of which segment_types are the embed-skipped
# rollup family; import it so the two agree on "which types" (the COUNTS are
# recomputed here independently as a cross-check of the registry reverse gate).
sys.path.insert(0, str(_REPO / "tools" / "registry"))
from build_registry import EMBED_SKIP_SEGMENT_TYPES  # noqa: E402

# =====================================================
# Locked expectations (drift = STOP; update with maintainer approval)
# =====================================================

#: Providers whose index state is portable JSON ({provider, model}). tfidf state
#: carries a fitted vectorizer that cannot be JSON-serialized, so a tfidf index
#: has no ``.vec.json`` and cannot be distributed by this path.
API_PROVIDERS = frozenset({"gemini", "openai"})

#: The corpus-minus-index exclusion split, measured 2026-07-16 on corpus-v9 for
#: the 2026-07 / v9-gemini snapshot (maintainer adjudication). Recomputed from
#: real data on every build and asserted equal -- any drift is a hard stop, not a
#: silent re-baseline. **Snapshot-specific**: when the index/corpus is rebuilt,
#: re-measure and update this with maintainer approval.
EXPECTED_EMBED_EXCLUSIONS = {
    "rollup": 16332,
    "supplproviso_rollup": 8797,
    "empty_text": 4,
    "total": 25133,
}

_CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NPY_MAGIC = b"\x93NUMPY"


class SnapshotError(RuntimeError):
    """Fatal snapshot build error (STOP condition). Never degrade to a warning."""


@dataclass(frozen=True)
class SnapshotPaths:
    """Local source locations. ``index_prefix`` is the extension-less prefix
    (``<prefix>.npy`` / ``.meta.jsonl`` / ``.vec.json`` are derived)."""

    index_prefix: Path
    registry_dir: Path
    corpus_full: Path  # corpus-v9.jsonl (all chunks; needed for the gap, not shipped)
    corpus_embed: Path  # corpus-v9-embed.jsonl (row-aligned = shipped corpus)
    data_dir: Path  # data/v0.2 (source manifests -> pipeline_version)


# =====================================================
# Pure readers
# =====================================================


def sha256_of(path: Path) -> str:
    """Streaming sha256 hex of a file (1 MiB blocks; handles the 1.7 GB .npy)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    """Number of newline-terminated rows in a JSONL file."""
    n = 0
    with path.open(encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def read_npy_shape(path: Path) -> tuple[int, ...]:
    """Parse the ``shape`` from an ``.npy`` header WITHOUT numpy (CI has none).

    The NPY format is: magic ``\\x93NUMPY``, one version byte pair, a little-endian
    header length (uint16 for v1, uint32 for v2+), then an ASCII Python-dict
    literal (``{'descr': ..., 'fortran_order': ..., 'shape': (rows, cols), }``).
    Reading only the header avoids loading the multi-GB array.
    """
    with path.open("rb") as f:
        magic = f.read(6)
        if magic != _NPY_MAGIC:
            raise SnapshotError(f"not an .npy file (bad magic): {path}")
        major, _minor = f.read(2)
        if major == 1:
            (hlen,) = struct.unpack("<H", f.read(2))
        else:
            (hlen,) = struct.unpack("<I", f.read(4))
        header = f.read(hlen).decode("latin1")
    try:
        meta = ast.literal_eval(header)
        shape = meta["shape"]
    except (ValueError, SyntaxError, KeyError) as exc:
        raise SnapshotError(f"unparseable .npy header in {path}: {exc}") from exc
    if not isinstance(shape, tuple) or not shape:
        raise SnapshotError(f"unexpected .npy shape {shape!r} in {path}")
    return shape


def read_embedding_model(vec_json_path: Path) -> str:
    """Read the embedding model from the index ``.vec.json`` sidecar.

    The value is NEVER hard-coded here (contract): it is the single source of
    truth for what produced the vectors. tfidf (non-API) indexes have no
    ``.vec.json`` and cannot be shipped by this path.
    """
    if not vec_json_path.exists():
        raise SnapshotError(
            f"missing {vec_json_path.name} (a distributable index must ship "
            ".vec.json, not a pickle -- re-embed or run the .vec.json migration)"
        )
    state = json.loads(vec_json_path.read_text(encoding="utf-8"))
    provider = state.get("provider")
    if provider not in API_PROVIDERS:
        raise SnapshotError(
            f"index provider {provider!r} is not distributable (expected one of "
            f"{sorted(API_PROVIDERS)}; tfidf state is not portable JSON)"
        )
    model = state.get("model")
    if not model:
        raise SnapshotError(f"{vec_json_path.name} has no 'model' field")
    return model


def read_pipeline_version(data_dir: Path) -> str:
    """Single ``parser_version`` shared by all source manifests (asserted).

    A snapshot mixing pipeline versions would make the ledger's provenance
    ambiguous, so a non-single value is a hard stop.
    """
    values: set[str] = set()
    manifests = sorted(data_dir.rglob("_source-manifest.json"))
    if not manifests:
        raise SnapshotError(f"no _source-manifest.json under {data_dir}")
    for mp in manifests:
        m = json.loads(mp.read_text(encoding="utf-8"))
        pv = m.get("parser_version")
        if not pv:
            raise SnapshotError(f"manifest missing parser_version: {mp}")
        values.add(pv)
    if len(values) != 1:
        raise SnapshotError(f"pipeline_version not single-valued: {sorted(values)}")
    return next(iter(values))


def compute_embed_exclusions(corpus_full: Path, corpus_embed: Path) -> dict[str, int]:
    """Split the corpus-minus-index gap by reason and lock it against expectation.

    Every gap chunk MUST be a rollup-family aggregation (embed_skip=True by
    design) or empty text. A body chunk in the gap -- neither rollup nor empty --
    is a silent search hole (G0-e class) and a STOP. The empty-text test mirrors
    ``filter_v8_embed`` exactly: ``not (text or "").strip()``.
    """
    embed_ids: set[str] = set()
    with corpus_embed.open(encoding="utf-8") as f:
        for line in f:
            embed_ids.add(json.loads(line)["chunk_id"])

    counts = {"rollup": 0, "supplproviso_rollup": 0, "empty_text": 0}
    unexpected: list[str] = []
    total = 0
    with corpus_full.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["chunk_id"] in embed_ids:
                continue
            total += 1
            seg = r.get("segment_type")
            if seg in EMBED_SKIP_SEGMENT_TYPES:
                counts[seg] += 1
            elif not (r.get("text") or "").strip():
                counts["empty_text"] += 1
            else:
                unexpected.append(r["chunk_id"])
    if unexpected:
        raise SnapshotError(
            f"{len(unexpected)} body chunk(s) in the corpus but absent from the "
            f"index (neither -rollup nor empty-text -- a silent search hole), "
            f"first 5: {sorted(unexpected)[:5]}"
        )
    counts["total"] = total
    if counts != EXPECTED_EMBED_EXCLUSIONS:
        raise SnapshotError(
            f"embed_exclusions drift: expected {EXPECTED_EMBED_EXCLUSIONS}, got {counts} "
            "(re-measure and update EXPECTED_EMBED_EXCLUSIONS with maintainer approval "
            "only if the index/corpus was intentionally rebuilt)"
        )
    return counts


# =====================================================
# File plan (single source of truth; publish_to_hf reuses this)
# =====================================================


def file_plan(paths: SnapshotPaths) -> list[tuple[Path, str]]:
    """(local source path, snapshot-relative dest) for the 7 shipped files.

    Ordered registry -> corpus -> index so ``files`` in snapshot.json has a
    stable, byte-deterministic key order. publish_to_hf imports this so the
    manifest and the upload can never disagree on paths.
    """
    name = paths.index_prefix.name
    return [
        (paths.registry_dir / "documents.jsonl", "registry/documents.jsonl"),
        (paths.registry_dir / "chunks.jsonl", "registry/chunks.jsonl"),
        (paths.registry_dir / "texts.jsonl", "registry/texts.jsonl"),
        (paths.corpus_embed, "corpus/row-aligned-corpus.jsonl"),
        (Path(str(paths.index_prefix) + ".meta.jsonl"), f"index/{name}.meta.jsonl"),
        (Path(str(paths.index_prefix) + ".vec.json"), f"index/{name}.vec.json"),
        (Path(str(paths.index_prefix) + ".npy"), f"index/{name}.npy"),
    ]


# =====================================================
# Manifest assembly
# =====================================================


def build_snapshot(paths: SnapshotPaths, snapshot_id: str, created_at: str) -> dict:
    """Assemble the snapshot.json dict (contract rev.4). Pure: same inputs ->
    byte-identical output. Raises SnapshotError on any drift / inconsistency."""
    if not _CREATED_AT_RE.match(created_at):
        raise SnapshotError(f"created_at must be YYYY-MM-DD, got {created_at!r}")

    plan = file_plan(paths)
    for src, _dest in plan:
        if not src.exists():
            raise SnapshotError(f"missing shipped file: {src}")

    index_name = paths.index_prefix.name
    embedding_model = read_embedding_model(Path(str(paths.index_prefix) + ".vec.json"))
    pipeline_version = read_pipeline_version(paths.data_dir)

    documents = count_lines(paths.registry_dir / "documents.jsonl")
    texts = count_lines(paths.registry_dir / "texts.jsonl")
    chunks = count_lines(paths.registry_dir / "chunks.jsonl")
    index_rows = count_lines(Path(str(paths.index_prefix) + ".meta.jsonl"))
    corpus_full_rows = count_lines(paths.corpus_full)
    corpus_embed_rows = count_lines(paths.corpus_embed)
    npy_shape = read_npy_shape(Path(str(paths.index_prefix) + ".npy"))

    # Structural cross-checks (version-independent; catch a mismatched artefact).
    if documents != texts:
        raise SnapshotError(f"documents ({documents}) != texts ({texts})")
    if not (index_rows == npy_shape[0] == corpus_embed_rows):
        raise SnapshotError(
            f"index row disagreement: meta {index_rows} / npy {npy_shape[0]} / "
            f"row-aligned corpus {corpus_embed_rows} (patch .npy BEFORE generating)"
        )
    if chunks != corpus_full_rows:
        raise SnapshotError(f"chunks ({chunks}) != full corpus rows ({corpus_full_rows})")

    embed_exclusions = compute_embed_exclusions(paths.corpus_full, paths.corpus_embed)

    files = {dest: sha256_of(src) for src, dest in plan}

    return {
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "pipeline_version": pipeline_version,
        "index": {"index_name": index_name, "embedding_model": embedding_model},
        "counts": {
            "documents": documents,
            "chunks": chunks,
            "texts": texts,
            "index_rows": index_rows,
        },
        "files": files,
        "embed_exclusions": embed_exclusions,
    }


def to_bytes(snapshot: dict) -> bytes:
    """Serialize snapshot.json deterministically (fixed key order, UTF-8)."""
    return (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# =====================================================
# CLI
# =====================================================


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate snapshot.json (contract rev.4).")
    p.add_argument(
        "--index",
        type=Path,
        default=_REPO / "build" / "embeddings" / "v0.2-aug-v9-gemini",
        help="index prefix (extension-less); .npy/.meta.jsonl/.vec.json are derived",
    )
    p.add_argument("--registry-dir", type=Path, default=_REPO / "build" / "registry")
    p.add_argument("--corpus", type=Path, default=_REPO / "build" / "corpus-v9.jsonl")
    p.add_argument("--corpus-embed", type=Path, default=_REPO / "build" / "corpus-v9-embed.jsonl")
    p.add_argument("--data-dir", type=Path, default=_REPO / "data" / "v0.2")
    p.add_argument("--snapshot-id", default="2026-07")
    p.add_argument(
        "--created-at",
        required=True,
        help="snapshot date YYYY-MM-DD (operator-provided; the script cannot read the clock)",
    )
    p.add_argument("--out", type=Path, default=_REPO / "build" / "snapshot.json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    paths = SnapshotPaths(
        index_prefix=args.index,
        registry_dir=args.registry_dir,
        corpus_full=args.corpus,
        corpus_embed=args.corpus_embed,
        data_dir=args.data_dir,
    )
    snap1 = build_snapshot(paths, args.snapshot_id, args.created_at)
    snap2 = build_snapshot(paths, args.snapshot_id, args.created_at)  # determinism gate
    b1, b2 = to_bytes(snap1), to_bytes(snap2)
    if b1 != b2:
        raise SnapshotError("nondeterministic snapshot: two runs differ byte-wise")

    sys.path.insert(0, str(_REPO / "tools" / "shared" / "src"))
    from juricode_shared.safe_write import safe_write_text

    args.out.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text(args.out, b1.decode("utf-8"), newline="\n")

    print("== snapshot.json ==")
    print(f"snapshot_id     : {snap1['snapshot_id']}  created_at: {snap1['created_at']}")
    print(f"pipeline_version: {snap1['pipeline_version']}")
    print(f"index           : {snap1['index']}")
    print(f"counts          : {snap1['counts']}")
    print(f"embed_exclusions: {snap1['embed_exclusions']}")
    print(f"files ({len(snap1['files'])}):")
    for dest, digest in snap1["files"].items():
        print(f"  {dest:40s} {digest}")
    print(f"written -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

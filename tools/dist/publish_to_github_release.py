#!/usr/bin/env python3
"""publish_to_github_release.py -- freeze a snapshot as a GitHub Release audit anchor.

A Hugging Face file can be replaced in place; a GitHub Release attached to a tag is
immutable evidence. This publisher mirrors, for GitHub, the discipline
``publish_to_hf.py`` already applies to Hugging Face: **verify the local bytes against
``snapshot.json`` BEFORE publishing, and record every file's sha256.** The result is the
first immutable baseline a future change log can diff against -- if the snapshot is not
frozen now, the diff for the un-frozen period can never be reconstructed.

What is attached vs. what is anchored by hash only (maintainer adjudication):
  - **Attached**: ``snapshot.json`` + the 3 registry files
    (``registry/{documents,chunks,texts}.jsonl``). These are small and are the audit
    payload -- the manifest plus the citation registry it describes.
  - **Anchored by hash only**: the dense index and the row-aligned corpus. They are large
    and re-generatable, and are distributed on Hugging Face. Their sha256 values still go
    into the release notes, so a third party can verify those artefacts on HF as well.

Discipline:
  - ``snapshot.json``'s bytes are the anchor: this script READS it, never rewrites,
    reformats, or ``sort_keys`` it.
  - Integrity gate before anything else: every attached registry file's sha256 must equal
    the value ``snapshot.json`` records for it, or STOP (exit non-zero).
  - Default is ``--dry-run`` (prints the plan, mutates no remote). The real
    ``gh release create`` runs only with the explicit ``--publish`` flag and is the
    maintainer's action.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(_REPO / "tools" / "dist"))
from build_snapshot import file_plan_parts, sha256_of  # noqa: E402

#: The registry subset is exactly those shipped dests under ``registry/``.
_REGISTRY_PREFIX = "registry/"

#: The large artefacts live here (re-generatable, hash-anchored in the notes, not attached).
HF_DATASET_URL = "https://huggingface.co/datasets/JuriCode-JP/juricode-index"
_SOURCE_REPO_URL = "https://github.com/JuriCode-JP/JuriCode-JP"


def registry_subset(
    index_prefix: Path, registry_dir: Path, corpus_embed: Path
) -> list[tuple[Path, str]]:
    """The registry portion of the 7-file plan: (local source, snapshot-relative dest).

    Derived by FILTERING ``file_plan_parts`` (the single source of truth) to the
    ``registry/`` dests -- the paths are never hand-written here. corpus_embed is passed
    only to satisfy ``file_plan_parts``' signature; its (corpus/) entry is filtered out.
    """
    subset = [
        (src, dest)
        for src, dest in file_plan_parts(index_prefix, registry_dir, corpus_embed)
        if dest.startswith(_REGISTRY_PREFIX)
    ]
    if len(subset) != 3:
        raise ValueError(f"expected 3 registry files in the plan, got {len(subset)}: {subset}")
    return subset


def verify_registry_subset(snapshot: dict, subset: list[tuple[Path, str]]) -> dict[str, str]:
    """STOP unless every attached registry file's sha256 matches ``snapshot.json``.

    NOTE: this is intentionally NOT ``publish_to_hf.verify_local_against_snapshot``. That check
    asserts the shipped set equals ``snapshot.json['files']`` keys EXACTLY (HF ships all 7
    files), so a 3-of-7 subset would make it raise on the (deliberately) absent index/corpus
    -- which live on Hugging Face and are anchored here by hash only, not attached. This is
    the subset-aware variant: each attached dest must be a KEY in ``files`` and its local
    sha256 must match; the index/corpus keys being present-but-not-attached is expected, not
    an error.

    The ``snapshot.json`` key is the LITERAL dest string from ``file_plan_parts``
    (``"registry/documents.jsonl"`` etc., already POSIX). It is used verbatim as the
    ``files`` key -- never reconstructed from a local filesystem path (``.as_posix()`` on an
    absolute local path would yield the full path, not the key, and misfire the gate).
    """
    recorded = snapshot.get("files")
    if not isinstance(recorded, dict):
        raise ValueError("snapshot.json has no 'files' map")
    local_sha: dict[str, str] = {}
    for src, dest in subset:
        if dest not in recorded:
            raise ValueError(f"{dest} is not a key in snapshot.json['files']")
        if not src.exists():
            raise FileNotFoundError(f"attached file missing locally: {src}")
        got = sha256_of(src)
        if got != recorded[dest]:
            raise ValueError(
                f"{dest}: local sha256 {got} != snapshot.json {recorded[dest]} "
                "(regenerate snapshot.json AFTER the file's final bytes, or the wrong "
                "file is being attached)"
            )
        local_sha[dest] = got
    return local_sha


def build_notes(snapshot: dict) -> str:
    """GitHub Release notes (neutral English), driven entirely by ``snapshot.json``.

    Pure: same snapshot dict -> byte-identical string. No accuracy numbers (claims ledger),
    no internal names. The ``hash_basis`` wording is kept verbatim in step with
    ``publish_to_hf.build_readme`` so the two public surfaces agree.
    """
    sid = snapshot["snapshot_id"]
    index = snapshot["index"]
    counts = snapshot["counts"]
    files = snapshot["files"]
    excl = snapshot.get("embed_exclusions", {})
    name = index["index_name"]
    model = index["embedding_model"]
    pv = snapshot["pipeline_version"]
    documents = counts["documents"]
    chunks = counts["chunks"]
    texts = counts["texts"]
    index_rows = counts["index_rows"]
    hf_link = f"{HF_DATASET_URL}/tree/main/{sid}"

    sha_rows = "\n".join(f"| `{dest}` | `{digest}` |" for dest, digest in files.items())

    return f"""# JuriCode-JP snapshot `{sid}`

This GitHub Release is the immutable audit anchor for snapshot `{sid}`. It freezes the
provenance manifest (`snapshot.json`) and the citation registry so a future change log has
a fixed baseline to diff against, and so a third party can confirm later that the
distributed bytes were not silently replaced afterwards.

The large artefacts (the dense index and the row-aligned corpus) are distributed on
Hugging Face, not attached here; their sha256 values are recorded below so they stay
verifiable too.

## Attached to this release

| File | What it is |
|---|---|
| `snapshot.json` | The manifest: `files` maps every distributed file to its sha256, plus counts and provenance. |
| `registry/documents.jsonl` | One row per document ({documents}), with its content hash. |
| `registry/chunks.jsonl` | `chunk_id` -> document id ({chunks} chunks). |
| `registry/texts.jsonl` | The exact stored text ({texts} rows), each hashing to its `documents.jsonl` entry. |

## Provenance

- Pipeline: `{pv}`
- Index: `{name}`
- Embedding model: `{model}`
- Counts: documents {documents}, chunks {chunks}, texts {texts}, index rows {index_rows}

## sha256 of every distributed file

Recorded in `snapshot.json`. The `index/` and `corpus/` rows below live on Hugging Face;
their hashes let you verify those artefacts as well.

| File | sha256 |
|---|---|
{sha_rows}

## Chunks in the registry but not in the index

`registry/chunks.jsonl` has more rows than the index. The difference is intentional and
recorded in `snapshot.json` as `embed_exclusions`:

| Reason | Count |
|---|---|
| `rollup` | {excl.get("rollup", 0)} |
| `supplproviso_rollup` | {excl.get("supplproviso_rollup", 0)} |
| `empty_text` | {excl.get("empty_text", 0)} |
| total | {excl.get("total", 0)} |

`-rollup` chunks aggregate child chunks that ARE indexed; empty-text chunks carry no
searchable text. Nothing searchable is missing.

## What `hash_basis` means (read this before trusting a hash)

Every document in the registry carries a `hash_basis` field. **The three values do not
carry the same strength of evidence.** Do not treat them as interchangeable.

| `hash_basis` | Meaning |
|---|---|
| `egov-xml-canonical` | The text was checked against the e-Gov source XML. The hash is the one recorded in the per-law source manifest. |
| `egov-xml-derived` | Supplementary provisions (附則). Derived from the same source XML, but there is no per-article manifest anchor for them yet. |
| `juricode-stored-text` | The hash is over the text as stored here. **It is self-reported.** No external source was re-fetched to confirm it. |

This distribution is **not** "all verified". It is verified where it says it is verified.

## Comparing snapshots

Do not diff two snapshots with different `pipeline_version` values. A change in the pipeline
changes how text is chunked and hashed, so a row-by-row diff across versions measures the
pipeline, not the law.

## Distribution

The full self-contained snapshot directory (index, corpus, registry, README) is on Hugging
Face: {hf_link}

Source: {_SOURCE_REPO_URL}
"""


def _load_snapshot(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"snapshot.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _gh_ready(repo: str) -> tuple[bool, str]:
    """Is ``gh`` installed and authenticated? Non-interactive (never opens a prompt).

    ``gh auth status`` prints the token; we capture the output and use only the return
    code, so nothing secret is ever echoed.
    """
    exe = shutil.which("gh")
    if not exe:
        return False, "gh CLI not found on PATH"
    r = subprocess.run(
        [exe, "auth", "status"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return False, "gh is not authenticated (run `gh auth login`)"
    return True, "gh installed and authenticated"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="JuriCode-JP/JuriCode-JP")
    ap.add_argument("--snapshot-json", type=Path, default=_REPO / "build" / "snapshot.json")
    ap.add_argument(
        "--index",
        type=Path,
        default=_REPO / "build" / "embeddings" / "v0.2-aug-v9-gemini",
        help="index prefix (extension-less); used only to derive the file plan",
    )
    ap.add_argument("--registry-dir", type=Path, default=_REPO / "build" / "registry")
    ap.add_argument("--corpus-embed", type=Path, default=_REPO / "build" / "corpus-v9-embed.jsonl")
    ap.add_argument("--tag", default=None, help="release tag (default: snapshot-<snapshot_id>)")
    ap.add_argument(
        "--notes-out",
        type=Path,
        default=None,
        help="where to write the notes file (default: build/release-notes-<tag>.md)",
    )
    ap.add_argument(
        "--publish",
        action="store_true",
        help="actually create the release (maintainer only). Without this flag the tool is dry-run.",
    )
    args = ap.parse_args()

    snapshot = _load_snapshot(args.snapshot_json)
    snapshot_id = snapshot["snapshot_id"]
    tag = args.tag or f"snapshot-{snapshot_id}"
    title = f"JuriCode-JP snapshot {snapshot_id}"
    notes_out = args.notes_out or (_REPO / "build" / f"release-notes-{tag}.md")

    subset = registry_subset(args.index, args.registry_dir, args.corpus_embed)

    # ---- integrity gate: attached registry bytes must match snapshot.json FIRST ----
    try:
        local_sha = verify_registry_subset(snapshot, subset)
    except (ValueError, FileNotFoundError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1

    # snapshot.json is the manifest; its own sha256 is not inside `files`, so compute it
    # separately for the log (it is not part of build_notes, which is dict-pure).
    snapshot_json_sha = sha256_of(args.snapshot_json)

    # Assets = snapshot.json + the 3 registry files.
    assets = [args.snapshot_json] + [src for src, _dest in subset]

    notes = build_notes(snapshot)

    sys.path.insert(0, str(_REPO / "tools" / "shared" / "src"))
    from juricode_shared.safe_write import safe_write_text

    safe_write_text(notes_out, notes, newline="\n")

    print("=== integrity gate (attached files vs snapshot.json) ===")
    print(f"  {'snapshot.json (manifest, not in files)':46s} {snapshot_json_sha}")
    for _src, dest in subset:
        print(f"  OK  {dest:42s} {local_sha[dest]}")

    print("\n=== release plan ===")
    print(f"  tag        : {tag}")
    print(f"  title      : {title}")
    print(f"  repo       : {args.repo}")
    print(f"  notes file : {notes_out}")
    print("  assets:")
    total = 0
    for a in assets:
        size = a.stat().st_size
        total += size
        print(f"    {a.name:36s} {size:>14,d} B")
    print(f"    {'TOTAL':36s} {total:>14,d} B")

    print("\n=== release notes ===")
    print(notes)

    if not args.publish:
        print("(dry-run: nothing created. Re-run with --publish to create the release.)")
        return 0

    # ---- real mode (maintainer only): create the GitHub Release ----------------
    ready, why = _gh_ready(args.repo)
    if not ready:
        print(f"STOP: {why}", file=sys.stderr)
        return 1

    exe = shutil.which("gh")
    cmd = (
        [exe, "release", "create", tag]
        + [str(a) for a in assets]
        + ["--repo", args.repo, "--title", title, "--notes-file", str(notes_out)]
    )
    print(f"\ncreating release {tag} on {args.repo} ...", flush=True)
    # Non-interactive stdin so gh can never block on a prompt (the silent-hang path). No
    # short timeout: a large-file asset upload legitimately runs long, and a 30s cap would
    # kill a valid publish -- the DEVNULL stdin + the up-front auth check are the guard.
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, check=False)
    if r.returncode != 0:
        print(f"STOP: gh release create exited {r.returncode}", file=sys.stderr)
        return 1
    print(f"done -> https://github.com/{args.repo}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

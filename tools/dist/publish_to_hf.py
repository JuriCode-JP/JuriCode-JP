#!/usr/bin/env python3
"""publish_to_hf.py -- 索引と引用レジストリを Hugging Face (dataset) に公開する.

再実行可能な形にしてある (次の版でも同じ手順で使う)。版はリポ名ではなく
**リポ内のパス** で表す (index/<index-name>.npy, registry/<snapshot>/...)。

守ること:
    - トークンは os.environ["HF_TOKEN"] のみ。引数で受け取らない・ログに出さない。
    - **公開前に leak スキャンを通す** (scan_artifacts.py)。配布物の中身は、これまで
      一度も外向けに検査されたことがない。HF への公開は取り消せない。
    - **公開後に re-download して sha256 を照合する**。「配布物が原本と同一であることを
      機械で検証できる」というのが我々の売りである以上、それを自分自身に適用する。
      一致しなければ STOP。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def build_readme(index_name: str, snapshot: str, n_chunks: int, pipeline_version: str) -> str:
    """HF 側 README (中立英語). 精度の数値は書かない (claims ledger)."""
    return f"""---
license: mit
language:
  - ja
tags:
  - legal
  - japanese-law
  - retrieval
  - embeddings
---

# JuriCode-JP retrieval index and citation registry

Structured Japanese statutory law for retrieval, with a citation registry that lets a
consumer verify that a quoted passage is byte-identical to the source text.

## Contents

| Path | What it is |
|---|---|
| `index/{index_name}.npy` | Dense vectors, `float32`, shape `({n_chunks}, 3072)` |
| `index/{index_name}.meta.jsonl` | One row per vector, in the same order: `chunk_id`, `article_id`, `law_id`, and section metadata |
| `registry/{snapshot}/documents.jsonl` | One row per document, with its content hash |
| `registry/{snapshot}/chunks.jsonl` | `chunk_id` -> document id |
| `registry/{snapshot}/_manifest.json` | Provenance: `pipeline_version`, paired index, sha256 of inputs and outputs |

Embedding model: `gemini-embedding-001` (3072 dimensions, `RETRIEVAL_DOCUMENT` task type).
Registry `pipeline_version`: `{pipeline_version}`.

The `.npy` row at position *i* corresponds to the `.meta.jsonl` row at position *i*.

## What `hash_basis` means (read this before trusting a hash)

Every document in the registry carries a `hash_basis` field. **The three values do not
carry the same strength of evidence.** Do not treat them as interchangeable.

| `hash_basis` | Meaning |
|---|---|
| `egov-xml-canonical` | The text was checked against the e-Gov source XML. The hash is the one recorded in the per-law source manifest. |
| `egov-xml-derived` | Supplementary provisions (附則). Derived from the same source XML, but there is no per-article manifest anchor for them yet. |
| `juricode-stored-text` | The hash is over the text as stored here. **It is self-reported.** No external source was re-fetched to confirm it. |

This distribution is **not** "all verified". It is verified where it says it is verified.

## No pickle

Only `.npy` and `.jsonl` are distributed. The `.vec.pkl` file used internally is **not**
published: it holds the same vectors as the `.npy`, and unpickling executes arbitrary
code in the reader's process. A project whose value proposition is verifiability should
not ship a format that asks the consumer to trust it.

## Licensing

The structuring layer (schema, ids, chunking, this index) is MIT.
The underlying texts are not ours to relicense: statutes come from e-Gov, circulars and
tax guidance from the National Tax Agency, and rulings from the National Tax Tribunal;
each is used under its own terms. See the source repository for the per-source table.

## Comparing registries

Do not diff two registries with different `pipeline_version` values. A change in the
pipeline changes how text is chunked and hashed, so a row-by-row diff across versions
measures the pipeline, not the law.

## Integrity

The sha256 of every file here is recorded in `CHANGES.md` in the source repository. That
file is the anchor: it lets a third party confirm that what they downloaded is what was
published, and that it was not replaced afterwards.

Source: https://github.com/JuriCode-JP/JuriCode-JP
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-id", default="JuriCode-JP/juricode-index")
    ap.add_argument("--index", type=Path, required=True, help="索引 prefix (拡張子なし)")
    ap.add_argument("--registry-dir", type=Path, required=True)
    ap.add_argument("--snapshot", required=True, help="registry のスナップショット名")
    ap.add_argument("--version-id", required=True, help="commit message に入れる版 ID")
    ap.add_argument("--create-repo", action="store_true")
    ap.add_argument("--skip-scan", action="store_true", help="leak スキャンを飛ばす (非推奨)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    index_name = args.index.name
    uploads: list[tuple[Path, str]] = []
    for suf in (".npy", ".meta.jsonl"):
        p = Path(str(args.index) + suf)
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 1
        uploads.append((p, f"index/{p.name}"))
    for name in ("documents.jsonl", "chunks.jsonl", "_manifest.json"):
        p = args.registry_dir / name
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 1
        uploads.append((p, f"registry/{args.snapshot}/{name}"))

    # ---- leak スキャン (公開は取り消せない) ------------------------------------
    if not args.skip_scan:
        print("=== leak スキャン (配布物の中身) ===", flush=True)
        rc = subprocess.run(
            [sys.executable, "-X", "utf8", str(_REPO / "tools" / "dist" / "scan_artifacts.py")]
            + [str(p) for p, _ in uploads],
            check=False,
        ).returncode
        if rc != 0:
            print("STOP: leak スキャンが落ちた。公開しない。", file=sys.stderr)
            return 1

    local_sha = {dest: sha256_of(p) for p, dest in uploads}
    print("\n=== アップロード対象 ===")
    total = 0
    for p, dest in uploads:
        size = p.stat().st_size
        total += size
        print(f"  {dest:44s} {size:>14,d} B  {local_sha[dest]}")
    print(f"  {'TOTAL':44s} {total:>14,d} B")

    if args.dry_run:
        print("\n(dry-run: 何もアップロードしていない)")
        return 0

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("STOP: HF_TOKEN が環境変数に無い", file=sys.stderr)
        return 1

    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=token)
    if args.create_repo:
        api.create_repo(args.repo_id, repo_type="dataset", private=False, exist_ok=True)
        print(f"\nrepo ready: {args.repo_id} (dataset, public)")

    n_chunks = sum(1 for _ in Path(str(args.index) + ".meta.jsonl").open(encoding="utf-8"))
    import json

    pipeline_version = json.loads((args.registry_dir / "_manifest.json").read_text("utf-8"))[
        "pipeline_version"
    ]
    readme = build_readme(index_name, args.snapshot, n_chunks, pipeline_version)
    api.upload_file(
        path_or_fileobj=readme.encode("utf-8"),
        path_in_repo="README.md",
        repo_id=args.repo_id,
        repo_type="dataset",
        commit_message=f"README for {args.version_id}",
    )
    print("uploaded README.md")

    for p, dest in uploads:
        print(f"uploading {dest} ({p.stat().st_size / 1e6:.1f} MB) ...", flush=True)
        api.upload_file(
            path_or_fileobj=str(p),
            path_in_repo=dest,
            repo_id=args.repo_id,
            repo_type="dataset",
            commit_message=f"add {dest} ({args.version_id})",
        )

    # ---- 公開後の検証: re-download して sha256 を照合 ---------------------------
    print("\n=== 公開後の検証 (HF から取り直して sha256 照合) ===")
    bad = []
    for _p, dest in uploads:
        got = hf_hub_download(repo_id=args.repo_id, filename=dest, repo_type="dataset", token=token)
        h = sha256_of(Path(got))
        ok = h == local_sha[dest]
        print(f"  {'OK  ' if ok else 'FAIL'} {dest:44s} {h}")
        if not ok:
            bad.append(dest)
    if bad:
        print(f"\nSTOP: 配布物が原本と一致しない: {bad}", file=sys.stderr)
        return 1

    print(f"\ndone -> https://huggingface.co/datasets/{args.repo_id}")
    print("全ファイルの sha256 が原本と一致 (配布物の同一性を機械で確認)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

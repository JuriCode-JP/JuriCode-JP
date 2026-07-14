#!/usr/bin/env python3
"""upload_index_to_hf.py -- 埋め込み索引と引用レジストリを Hugging Face に公開する.

Why:
    索引は再生成に課金と時間がかかる (v9 = 143,749 chunk / 約 $3.4)。公開して
    再利用できる形にしておかないと、誰かが引くたびに作り直すことになる。

Warning (これは外向きの・取り消しにくい操作):
    アップロードは公開である。一度上げたものは、後で消してもキャッシュ・索引に
    残りうる。**索引の整合 assert と eval が通ってからでなければ実行しない。**
    --dry-run で、何をどこへ上げるかを先に出せる。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-id", default="JuriCode-JP/juricode-index")
    ap.add_argument("--index", required=True, help="build/embeddings/<name> (拡張子なし)")
    ap.add_argument("--registry-dir", type=Path, default=_REPO / "build" / "registry")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files: list[tuple[Path, str]] = []
    for suf in (".npy", ".meta.jsonl"):
        p = Path(str(args.index) + suf)
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 1
        files.append((p, f"index/{p.name}"))
    for name in ("documents.jsonl", "chunks.jsonl", "_manifest.json"):
        p = args.registry_dir / name
        if p.exists():
            files.append((p, f"registry/{name}"))

    print(f"repo: {args.repo_id} (dataset)")
    total = 0
    for p, dest in files:
        size = p.stat().st_size
        total += size
        print(f"  {dest:34s} {size / 1e6:9.1f} MB  sha256={sha256(p)[:16]}...")
    print(f"  total: {total / 1e6:.1f} MB")

    if args.dry_run:
        print("\n(dry-run: 何もアップロードしていない)")
        return 0

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN not set", file=sys.stderr)
        return 1

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(args.repo_id, repo_type="dataset", exist_ok=True)
    for p, dest in files:
        print(f"uploading {dest} ...", flush=True)
        api.upload_file(
            path_or_fileobj=str(p),
            path_in_repo=dest,
            repo_id=args.repo_id,
            repo_type="dataset",
        )
    print(f"\ndone -> https://huggingface.co/datasets/{args.repo_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""add_rollup_chunks.py — 各 article に rollup chunk を追加.

v0.2 の segment 分割は retrieval で「条全体」query に弱い。各 article に
「全 segment 結合 chunk」(rollup) を追加することで article-level retrieval を
回復させる。

設計:
  - 入力: build/chunks/{law}/{law}-article-{N}.chunks.jsonl
  - 各 article について:
    - 既存 chunks を paragraph_number + segment_type 順で sort
    - text を結合した rollup chunk を 1 つ追加
    - chunk_id = "{article_id}-rollup"
    - segment_type = "rollup"
  - 既存 chunk file に append

期待効果: lawqa-jp 等の「条全体を答えとする」query で R@3 +10-15pp
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


# segment_type 順 (display 順、rollup 内で意味のある並び)
SEGMENT_TYPE_ORDER = {
    "honbun": 0,
    "tadashi": 1,
    "zen_dan": 0,
    "kou_dan": 1,
    "hashira": 0,
    "kou": 1,
    "simple": 0,
    "tokusoku": 2,
    "junyou": 3,
}


def make_rollup_chunk(chunks: list[dict]) -> dict | None:
    """既存 chunks から rollup を構築. rollup が既に存在する場合は None."""
    if not chunks:
        return None

    # 既に rollup があれば skip
    for c in chunks:
        if c.get("segment_type") == "rollup" or "-rollup" in c.get("id", ""):
            return None

    # 代表 chunk (最初の) から metadata を継承
    first = chunks[0]
    article_id = first.get("article_id")
    if not article_id:
        return None

    # paragraph_number + segment_type の順で sort
    def sort_key(c):
        para = c.get("paragraph_number") or 0
        st = c.get("segment_type", "")
        st_order = SEGMENT_TYPE_ORDER.get(st, 99)
        item = c.get("item_number") or 0
        return (para, st_order, item)

    sorted_chunks = sorted(chunks, key=sort_key)

    # 各 chunk の text を改行で結合
    text_parts = []
    for c in sorted_chunks:
        t = c.get("text", "").strip()
        if t:
            text_parts.append(t)
    combined_text = "\n".join(text_parts)

    # 空 text rollup は作らない (空 chunks は retrieval ノイズ)
    if not combined_text:
        return None

    rollup = {
        "id": f"{article_id}-rollup",
        "article_id": article_id,
        "law_id": first.get("law_id"),
        "law_name_ja": first.get("law_name_ja"),
        "article_number": first.get("article_number"),
        "paragraph_number": None,  # rollup は段落横断
        "segment_type": "rollup",
        "modality": "unspecified",  # rollup は全体平均
        "text": combined_text,
    }
    if first.get("parent_section"):
        rollup["parent_section"] = first["parent_section"]

    return rollup


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.chunks_dir.exists():
        sys.exit(f"ERROR: chunks dir not found: {args.chunks_dir}")

    chunk_files = sorted(args.chunks_dir.rglob("*.chunks.jsonl"))
    # backup ディレクトリ除外
    chunk_files = [f for f in chunk_files if "backup" not in str(f).lower()]
    print(f"chunk files: {len(chunk_files)}", file=sys.stderr)

    added = 0
    skipped_existing = 0
    skipped_empty = 0

    for f in chunk_files:
        chunks: list[dict] = []
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if not chunks:
            skipped_empty += 1
            continue

        rollup = make_rollup_chunk(chunks)
        if rollup is None:
            skipped_existing += 1
            continue

        if not args.dry_run:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rollup, ensure_ascii=False) + "\n")
        added += 1

    print(f"\n=== Summary ===", file=sys.stderr)
    print(f"Rollup added:        {added}", file=sys.stderr)
    print(f"Skipped (existing):  {skipped_existing}", file=sys.stderr)
    print(f"Skipped (empty):     {skipped_empty}", file=sys.stderr)
    if args.dry_run:
        print(f"(dry-run, no files modified)", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

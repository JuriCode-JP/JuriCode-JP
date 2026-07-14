#!/usr/bin/env python3
"""add_rollup_chunks.py -- 各 article に rollup chunk を追加.

v0.2 の segment 分割は retrieval で「条全体」query に弱い。各 article に
「全 segment 結合 chunk」(rollup) を追加することで article-level retrieval を
回復させる。

設計:
  - 入力: build/chunks/{law}/{law}-article-{N}.chunks.jsonl
  - 各 article について:
    - 既存 chunks を **ファイル順 = 文書順** のまま結合した rollup chunk を 1 つ追加
    - chunk_id = "{article_id}-rollup"
    - segment_type = "rollup"
  - 既存 chunk file に append

期待効果: lawqa-jp 等の「条全体を答えとする」query で R@3 +10-15pp

Why 文書順で結合するか (旧実装のバグ):
  旧実装は segment_type に手書きの表示順 (hashira=0, kou=1, tokusoku=2 …) を割り当てて
  sort していた。この順序は文書順ではないため、柱書が tokusoku や junyou と判定された条
  (例「〜の規定にかかわらず、次に掲げる…」) では **柱書が号の後ろに送られ、rollup が
  号から始まる**。rollup は「条全体の本文」を表す chunk なので、原文の順序を壊すことは
  そのまま忠実性の欠陥 (G0-c 違反) になる。build_chunks_from_md.py が正本 md の文書順で
  chunk を書くので、ここでは並べ替えず入力順を保つ。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# tools/shared/src を sys.path に追加して juricode_shared を import 可能にする
_SHARED_SRC = Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import safe_append_jsonl_records  # noqa: E402, I001  (must follow sys.path tweak)


def make_rollup_chunk(chunks: list[dict]) -> dict | None:
    """既存 chunks から rollup を構築 (文書順を保つ). rollup が既に存在する場合は None."""
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

    # 各 chunk の text を **入力順 (= 正本 md の文書順)** のまま改行で結合。
    # 並べ替えない (module docstring の Why 参照)。
    text_parts = []
    for c in chunks:
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
    # 本文 chunk ファイルのみを対象にする。
    # Why: rglob("*.chunks.jsonl") は {law}-article-{N}.table.chunks.jsonl や
    # {law}-supplproviso.chunks.jsonl にもマッチする。旧実装はそれらにも rollup を
    # append しており、**本文 rollup と同じ id を持つ別内容の rollup** (導入文＋表の
    # パイプ行) が表ファイルに二重生成されていた (id 衝突 = retrieval 汚染)。
    # rollup は「条の本文全体」なので本文 chunk ファイルからのみ作る。
    chunk_files = [
        f
        for f in chunk_files
        if "-article-" in f.name and not f.name.endswith(".table.chunks.jsonl")
    ]
    print(f"chunk files (本文のみ): {len(chunk_files)}", file=sys.stderr)

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
            # FU-302: append mode は既存 jsonl が壊れていても気付けないため、
            # safe_append_jsonl_records で「読み直し + 全レコード検証 + 書き直し」する.
            # 既存事故 (g) 4,810 empty chunks 紛れ込み防止.
            safe_append_jsonl_records(f, [rollup])
        added += 1

    print("\n=== Summary ===", file=sys.stderr)
    print(f"Rollup added:        {added}", file=sys.stderr)
    print(f"Skipped (existing):  {skipped_existing}", file=sys.stderr)
    print(f"Skipped (empty):     {skipped_empty}", file=sys.stderr)
    if args.dry_run:
        print("(dry-run, no files modified)", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

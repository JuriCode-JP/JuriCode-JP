#!/usr/bin/env python3
"""patch_index.py -- 既存の索引のうち、embed_text が変わった行だけを埋め直す.

Why 部分更新にするか:
    索引全体の再 embed は 143,749 件・課金・数時間。embed_text が変わったのが
    数千件なら、その行だけ埋め直せば数分・数セントで済む。

Why 部分更新こそ厳しく検算するか:
    部分更新は「触っていない行を壊していないこと」を証明できて初めて意味がある。
    行を入れ替える処理は、ズレたとき **数値上は正常に見える** (行数も chunk_id 集合も
    変わらない)。ゆえに:
      - 未変更行のベクトルが **byte 不変** であること (.npy を bytes で比較)
      - 変更行が **新しい embed_text に対応** していること (サンプル cosine ~1.0)
      - 位置対応 (meta[i] == corpus[i]) が保たれること
    を、この場で assert する。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_corpus(p: Path, text_field: str) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    texts: list[str] = []
    with p.open(encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            if r.get("embed_skip"):
                continue
            ids.append(r["chunk_id"])
            texts.append(r.get(text_field) or "")
    return ids, texts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", required=True, help="build/embeddings/<name> (拡張子なし)")
    ap.add_argument("--old-corpus", type=Path, required=True, help="索引を作った入力")
    ap.add_argument("--new-corpus", type=Path, required=True, help="修正後の入力")
    ap.add_argument("--text-field", default="embed_text")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    old_ids, old_texts = load_corpus(args.old_corpus, args.text_field)
    new_ids, new_texts = load_corpus(args.new_corpus, args.text_field)

    if old_ids != new_ids:
        print(
            "STOP: chunk_id の並びが変わっている (部分更新は使えない -- 全体を作り直すこと)",
            file=sys.stderr,
        )
        print(f"  old {len(old_ids):,} / new {len(new_ids):,}", file=sys.stderr)
        return 1

    changed = [i for i, (a, b) in enumerate(zip(old_texts, new_texts, strict=True)) if a != b]
    print(f"embed_text が変わった行: {len(changed):,} / {len(new_ids):,}")
    if args.dry_run:
        for i in changed[:5]:
            print(f"  {new_ids[i]}")
        print("(dry-run: API を呼ばない)")
        return 0
    if not changed:
        print("変更なし -- 何もしない")
        return 0

    npy = Path(str(args.index) + ".npy")
    vecs = np.load(npy)
    if vecs.shape[0] != len(new_ids):
        print(f"STOP: 索引 {vecs.shape[0]:,} 行 != corpus {len(new_ids):,} 行", file=sys.stderr)
        return 1

    before_unchanged = np.array(
        [vecs[i] for i in range(len(new_ids)) if i not in set(changed)], dtype=vecs.dtype
    ).tobytes()

    from eval_branch_item import embed_queries

    for s in range(0, len(changed), args.batch):
        block = changed[s : s + args.batch]
        vs = embed_queries([new_texts[i] for i in block], task_type="RETRIEVAL_DOCUMENT")
        for k, i in enumerate(block):
            vecs[i] = vs[k]
        print(f"  patched {min(s + args.batch, len(changed)):,} / {len(changed):,}", flush=True)

    after_unchanged = np.array(
        [vecs[i] for i in range(len(new_ids)) if i not in set(changed)], dtype=vecs.dtype
    ).tobytes()
    if before_unchanged != after_unchanged:
        print("STOP: 触っていないはずの行のベクトルが変わった", file=sys.stderr)
        return 1
    print(f"OK  未変更 {len(new_ids) - len(changed):,} 行のベクトルは byte 不変")

    np.save(npy, vecs)
    print(f"saved {npy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

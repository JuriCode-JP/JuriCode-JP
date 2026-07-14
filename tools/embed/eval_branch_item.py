#!/usr/bin/env python3
"""eval_branch_item.py -- 枝番条・号を gold にした検索 eval (chunk 粒度で判定する).

Why chunk 粒度なのか (これを間違えると eval が嘘をつく):
    gold を条レベル (houjin-zei-hou-art-132) にすると、**柱書チャンクがヒットした
    だけで「引けた」と判定されてしまう**。柱書は「次に掲げる法人」としか言わない
    ので、号の本文が索引に入っていなくても条レベル gold なら合格してしまう。
    それでは「号の本文が索引に入っているか」を検証したことにならない。

    さらに retrieve.py は既定で候補プールを **article_id で dedup** する。その経路の
    まま測ると、条内のどのチャンクが当たったのかが消える。ゆえに本ランナーは
    dense 検索をチャンク粒度で直接回し、top-K の **chunk_id** で判定する。

判定 (gold_level == "chunk"):
    PASS 条件 = gold_chunk_ids が top-K に入っている。
    reject_chunk_ids (柱書など) だけが入っていて gold が無い場合は FAIL。

判定 (gold_level == "article"):
    枝番条 (132条の2 / 142条の2) は **条そのものが索引から丸ごと欠落していた** ので、
    条レベル gold が正しい。gold_chunk_ids のいずれかが top-K にあれば PASS。

引用の健全性 (expect_verbatim がある設問):
    G0-c  : gold chunk の text が親条文本文の **byte 部分列** であること
    逐語  : expect_verbatim が gold chunk の text に **逐語一致** で含まれること
    -> 「引けるが引用できない」という非対称を作らない。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]


def embed_queries(
    texts: list[str],
    model: str = "gemini-embedding-001",
    task_type: str = "RETRIEVAL_QUERY",
) -> np.ndarray:
    """テキストを 1 件ずつ embed する.

    Why task_type を引数にするか:
        検索クエリは RETRIEVAL_QUERY、索引側の文書は RETRIEVAL_DOCUMENT で埋める。
        索引の「i 行目のベクトルが本当に i 行目の文書のものか」を検算する用途
        (verify_index.py の T8) では DOCUMENT 側で埋め直さないと比較にならない。
    """
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")
    client = genai.Client(api_key=key)
    out = []
    for t in texts:
        r = client.models.embed_content(
            model=model,
            contents=t,
            config=types.EmbedContentConfig(task_type=task_type),
        )
        out.append(r.embeddings[0].values)
    return np.asarray(out, dtype=np.float32)


def article_body(article_id: str, data_dir: Path) -> str | None:
    """正本 md の `## 原文` セクション本文 (G0-c の親テキスト)."""
    import re

    abbrev, _, num = article_id.partition("-art-")
    for p in data_dir.rglob(f"{abbrev}-article-{num}.md"):
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^##\s*原文[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.DOTALL | re.MULTILINE)
        if m:
            return m.group(1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", required=True, help="build/embeddings/<name> (拡張子なし)")
    ap.add_argument("--corpus", type=Path, required=True, help="chunk の text / article_id の出所")
    ap.add_argument("--eval-set", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, default=_REPO / "data" / "v0.2")
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args()

    base = Path(args.index)
    vecs = np.asarray(np.load(Path(str(base) + ".npy"), mmap_mode="r"), dtype=np.float32)
    meta = [json.loads(ln) for ln in Path(str(base) + ".meta.jsonl").open(encoding="utf-8")]
    chunk_ids = [m["chunk_id"] for m in meta]

    # meta.jsonl は text を持たない (索引のメタは軽量) ので、text と article_id は
    # 索引の入力コーパスから引く。ここを推測で導出すると G0-c の親条文を取り違える。
    texts: dict[str, str] = {}
    article_of: dict[str, str] = {}
    with args.corpus.open(encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            texts[r["chunk_id"]] = r.get("text") or ""
            if r.get("article_id"):
                article_of[r["chunk_id"]] = r["article_id"]

    queries = [json.loads(ln) for ln in args.eval_set.open(encoding="utf-8")]
    qvecs = embed_queries([q["question"] for q in queries])

    vn = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    qn = qvecs / np.linalg.norm(qvecs, axis=1, keepdims=True)
    sims = qn @ vn.T

    n_pass = 0
    for q, srow in zip(queries, sims, strict=True):
        top = np.argsort(-srow)[: args.top_k]
        top_ids = [chunk_ids[i] for i in top]
        gold = set(q["gold_chunk_ids"])
        reject = set(q.get("reject_chunk_ids") or [])
        hit = [c for c in top_ids if c in gold]
        rank = next((i + 1 for i, c in enumerate(top_ids) if c in gold), None)
        ok = bool(hit)

        print(f"\n[{q['qid']}] {q['question'][:56]}")
        print(f"  gold_level : {q['gold_level']}")
        print(
            f"  top-{args.top_k}     : {', '.join(top_ids[:5])}{' ...' if len(top_ids) > 5 else ''}"
        )
        print(f"  gold hit   : {'YES rank=' + str(rank) if ok else 'NO'}  {hit}")
        if reject & set(top_ids):
            note = (
                "gold も入っているので可" if ok else "★ 柱書だけがヒット = 号の本文は引けていない"
            )
            print(f"  reject hit : {sorted(reject & set(top_ids))}  ({note})")

        if ok and q.get("expect_verbatim"):
            cid = hit[0]
            ctext = texts.get(cid, "")
            aid = article_of.get(cid)
            parent = article_body(aid, args.data_dir) if aid else None
            g0c = parent is not None and ctext in parent
            verbatim = q["expect_verbatim"] in ctext
            print(f"  G0-c 部分列: {'OK' if g0c else 'FAIL'}  (chunk text ⊆ 親条文本文)")
            print(f"  逐語一致   : {'OK' if verbatim else 'FAIL'}  {q['expect_verbatim'][:34]!r}")
            ok = ok and g0c and verbatim

        print(f"  => {'PASS' if ok else 'FAIL'}")
        n_pass += ok

    print(f"\n=== branch/item eval: {n_pass} / {len(queries)} PASS (top-{args.top_k}) ===")
    return 0 if n_pass == len(queries) else 1


if __name__ == "__main__":
    sys.exit(main())

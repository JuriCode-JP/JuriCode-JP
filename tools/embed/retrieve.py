#!/usr/bin/env python3
"""
JuriCode-JP Top-K Retrieval Tester
===================================

Loads the embedding artefacts produced by `embed.py` (a .npy matrix, a
.meta.jsonl sidecar, and a .vec.pkl vectorizer), encodes each query in an
eval-set JSONL with the SAME vectorizer, and reports:

  - Per-question top-K results (with the expected article highlighted)
  - Aggregate Recall@1 / Recall@3 / Recall@10 and MRR

Usage:
    python tools/embed/retrieve.py \\
        --embedded build/juricode-bq-embedded \\
        --eval-set data/eval-set/*.jsonl \\
        --top-k 10 \\
        --show-per-query
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np


def _load_artefacts(prefix: Path):
    """Load .npy + .meta.jsonl + .vec.pkl for a given output prefix."""
    npy_path = prefix.with_suffix(".npy")
    meta_path = prefix.with_suffix(".meta.jsonl")
    vec_path = prefix.with_suffix(".vec.pkl")

    if not all(p.exists() for p in (npy_path, meta_path, vec_path)):
        missing = [str(p) for p in (npy_path, meta_path, vec_path) if not p.exists()]
        raise FileNotFoundError(f"Missing artefact(s): {missing}")

    matrix = np.load(npy_path)

    records: list[dict] = []
    with meta_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    with vec_path.open("rb") as fh:
        bundle = pickle.load(fh)  # noqa: S301
    vectorizer = bundle["vectorizer"]

    return matrix, records, vectorizer


def _load_queries(eval_set_paths: list[Path]) -> list[dict]:
    out: list[dict] = []
    for p in eval_set_paths:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    return out


def _cosine_similarity_batch(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    qn = float(np.linalg.norm(query_vec))
    if qn == 0:
        return np.zeros(matrix.shape[0], dtype=np.float32)
    q = (query_vec / qn).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1.0
    normed = matrix / norms[:, None]
    return (normed @ q).astype(np.float32)


def _rank_of_first_match(ranked_ids: list[str], expected: set[str]) -> int | None:
    for i, aid in enumerate(ranked_ids, start=1):
        if aid in expected:
            return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Top-K retrieval test on JuriCode-JP.")
    ap.add_argument(
        "--embedded",
        type=Path,
        required=True,
        help="Output prefix used by embed.py (e.g. build/juricode-bq-embedded)",
    )
    ap.add_argument("--eval-set", type=Path, nargs="+", required=True)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--show-per-query", action="store_true")
    args = ap.parse_args()

    try:
        matrix, records, vectorizer = _load_artefacts(args.embedded)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"Corpus: {len(records):,} record(s), embedding dim {matrix.shape[1]:,}",
        file=sys.stderr,
    )

    queries = _load_queries(args.eval_set)
    print(f"Queries: {len(queries):,}", file=sys.stderr)
    print("", file=sys.stderr)

    article_ids = [r.get("article_id") for r in records]
    law_name_ja = [r.get("law_name_ja") for r in records]
    article_number = [r.get("article_number") for r in records]

    ranks: list[int | None] = []
    recall_1 = 0
    recall_3 = 0
    recall_10 = 0

    for q in queries:
        question = q["question"]
        expected = set(q["expected_article_ids"])

        qmatrix = vectorizer.transform([question]).astype(np.float32).toarray()
        query_vec = qmatrix[0]

        sims = _cosine_similarity_batch(query_vec, matrix)
        top_idx = np.argsort(-sims)[: args.top_k]
        top_ids = [article_ids[i] for i in top_idx]

        rank = _rank_of_first_match(top_ids, expected)
        ranks.append(rank)

        if rank is not None:
            if rank <= 1:
                recall_1 += 1
            if rank <= 3:
                recall_3 += 1
            if rank <= 10:
                recall_10 += 1

        if args.show_per_query:
            print(f"=== {q['id']}: {question}", file=sys.stderr)
            print(f"   expected: {sorted(expected)}", file=sys.stderr)
            print(f"   first match rank: {rank}", file=sys.stderr)
            for i, idx in enumerate(top_idx[:5], 1):
                aid = article_ids[idx]
                score = float(sims[idx])
                lawname = law_name_ja[idx] or ""
                artnum = article_number[idx] or ""
                marker = " ✅" if aid in expected else ""
                print(
                    f"   [{i}] {aid:48s} {score:.3f}  {lawname} 第{artnum}条{marker}",
                    file=sys.stderr,
                )
            print("", file=sys.stderr)

    n = len(queries)
    if n == 0:
        print("ERROR: no queries loaded.", file=sys.stderr)
        return 1
    mrr = sum((1.0 / r) if r is not None else 0.0 for r in ranks) / n

    print("=== Aggregate metrics ===", file=sys.stderr)
    print(f"  N (queries)  : {n}", file=sys.stderr)
    print(f"  Recall@1     : {recall_1}/{n} = {recall_1 / n:.1%}", file=sys.stderr)
    print(f"  Recall@3     : {recall_3}/{n} = {recall_3 / n:.1%}", file=sys.stderr)
    print(f"  Recall@10    : {recall_10}/{n} = {recall_10 / n:.1%}", file=sys.stderr)
    print(f"  MRR          : {mrr:.3f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

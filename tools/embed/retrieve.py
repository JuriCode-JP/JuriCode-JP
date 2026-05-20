#!/usr/bin/env python3
"""JuriCode-JP Top-K Retrieval Tester.

Loads embedding artefacts produced by embed.py (.npy + .meta.jsonl + .vec.pkl),
encodes each query in eval-set JSONL using the SAME provider that built the
corpus, and reports Recall@1 / Recall@3 / Recall@10 + MRR.

Provider is detected from the .vec.pkl bundle so users do not pass --provider.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np


def _load_artefacts(prefix):
    npy_path = prefix.with_suffix(".npy")
    meta_path = prefix.with_suffix(".meta.jsonl")
    vec_path = prefix.with_suffix(".vec.pkl")
    missing = [str(p) for p in (npy_path, meta_path, vec_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing artefact(s): {missing}")

    matrix = np.load(npy_path)
    records = []
    with meta_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    with vec_path.open("rb") as fh:
        state = pickle.load(fh)  # noqa: S301 — local artefact
    return matrix, records, state


def _load_queries(eval_set_paths):
    out = []
    for p in eval_set_paths:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    return out


def _encode_queries(questions, state):
    provider = state.get("provider")
    if provider == "tfidf":
        v = state["vectorizer"]
        return v.transform(questions).astype(np.float32).toarray()

    if provider == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("ERROR: openai package not installed. Run: pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("ERROR: OPENAI_API_KEY environment variable not set")
        client = OpenAI(api_key=api_key)
        model = state["model"]
        resp = client.embeddings.create(model=model, input=questions)
        return np.asarray([item.embedding for item in resp.data], dtype=np.float32)

    sys.exit(f"ERROR: unsupported provider in artefacts: {provider!r}")


def _cosine_topk(query_matrix, corpus_matrix, top_k):
    qn = np.linalg.norm(query_matrix, axis=1, keepdims=True)
    qn[qn == 0] = 1.0
    qnorm = query_matrix / qn

    cn = np.linalg.norm(corpus_matrix, axis=1, keepdims=True)
    cn[cn == 0] = 1.0
    cnorm = corpus_matrix / cn

    sims = qnorm @ cnorm.T  # (Q, N)
    top_idx = np.argsort(-sims, axis=1)[:, :top_k]
    return sims, top_idx


def _rank_of_first_match(ranked_ids, expected):
    for i, aid in enumerate(ranked_ids, start=1):
        if aid in expected:
            return i
    return None


def main():
    ap = argparse.ArgumentParser(description="Top-K retrieval test on JuriCode-JP.")
    ap.add_argument("--embedded", type=Path, required=True)
    ap.add_argument("--eval-set", type=Path, nargs="+", required=True)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--show-per-query", action="store_true")
    args = ap.parse_args()

    try:
        matrix, records, state = _load_artefacts(args.embedded)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"Corpus: {len(records):,} record(s), dim {matrix.shape[1]:,}, "
        f"provider={state.get('provider')} model={state.get('model')}",
        file=sys.stderr,
    )

    queries = _load_queries(args.eval_set)
    print(f"Queries: {len(queries):,}\n", file=sys.stderr)

    questions = [q["question"] for q in queries]
    query_matrix = _encode_queries(questions, state)

    sims, top_idx = _cosine_topk(query_matrix, matrix, args.top_k)

    article_ids = [r.get("article_id") for r in records]
    law_name_ja = [r.get("law_name_ja") for r in records]
    article_number = [r.get("article_number") for r in records]

    ranks = []
    recall_1 = recall_3 = recall_10 = 0

    for qi, q in enumerate(queries):
        question = q["question"]
        expected = set(q["expected_article_ids"])
        idx_row = top_idx[qi]
        top_ids = [article_ids[i] for i in idx_row]

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
            for i, idx in enumerate(idx_row[:5], 1):
                aid = article_ids[idx]
                score = float(sims[qi, idx])
                lawname = law_name_ja[idx] or ""
                artnum = article_number[idx] or ""
                marker = " OK" if aid in expected else ""
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

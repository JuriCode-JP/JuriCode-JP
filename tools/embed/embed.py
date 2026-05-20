#!/usr/bin/env python3
"""JuriCode-JP Embedding Generator (TF-IDF baseline, sidecar .npy + .meta.jsonl + .vec.pkl)."""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

_META_FIELDS = (
    "article_id",
    "law_id",
    "law_name_ja",
    "article_number",
    "chunk_id",
    "phase_category",
    "hen_name_ja",
    "shou_name_ja",
)


def _read_records(path, limit):
    records = []
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARN line {i}: {e}", file=sys.stderr)
            if limit is not None and len(records) >= limit:
                break
    return records


def _tfidf(records, text_field, max_features):
    corpus = [(r.get(text_field) or "") for r in records]
    v = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 3),
        max_features=max_features,
        min_df=2,
    )
    sparse = v.fit_transform(corpus)
    return sparse.astype(np.float32), v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True, help="prefix for .npy/.meta.jsonl/.vec.pkl")
    ap.add_argument("--provider", choices=["tfidf"], default="tfidf")
    ap.add_argument("--text-field", default="text")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-features", type=int, default=10000)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    records = _read_records(args.input, args.limit)
    if not records:
        print("ERROR: no records read", file=sys.stderr)
        return 1
    print(f"Loaded {len(records):,} records", file=sys.stderr)

    sparse, vectorizer = _tfidf(records, args.text_field, args.max_features)
    model = f"tfidf-char-2to3gram-d{sparse.shape[1]}"
    print(f"Embeddings: shape={sparse.shape}, model={model}", file=sys.stderr)

    dense = sparse.toarray()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    npy = args.output.with_suffix(".npy")
    meta = args.output.with_suffix(".meta.jsonl")
    vec = args.output.with_suffix(".vec.pkl")

    np.save(npy, dense)
    print(f"Saved .npy:  {npy} ({dense.nbytes / 1024 / 1024:.1f} MB)", file=sys.stderr)

    with meta.open("w", encoding="utf-8") as fh:
        for r in records:
            m = {k: r.get(k) for k in _META_FIELDS}
            m["embedding_model"] = model
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"Saved meta:  {meta}", file=sys.stderr)

    with vec.open("wb") as fh:
        pickle.dump({"provider": args.provider, "vectorizer": vectorizer}, fh)
    print(f"Saved vec:   {vec}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

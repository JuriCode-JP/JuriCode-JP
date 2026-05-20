#!/usr/bin/env python3
"""JuriCode-JP Embedding Generator.

Pluggable provider design:
  --provider tfidf   : sklearn TF-IDF char n-gram baseline (offline, no key)
  --provider openai  : OpenAI text-embedding-3-small/large (needs OPENAI_API_KEY)
  --provider gemini  : Google Gemini embedding (needs GEMINI_API_KEY or GOOGLE_API_KEY)

Outputs:
  <output>.npy        — float32 (N, D) numpy matrix
  <output>.meta.jsonl — per-record metadata (article_id, law_name, etc.)
  <output>.vec.pkl    — provider state needed for retrieve.py to encode queries
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np

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


# ---------- Provider: TF-IDF ----------

def _tfidf_embed(records, text_field, max_features):
    from sklearn.feature_extraction.text import TfidfVectorizer

    corpus = [(r.get(text_field) or "") for r in records]
    v = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 3),
        max_features=max_features,
        min_df=2,
    )
    sparse = v.fit_transform(corpus)
    dense = sparse.astype(np.float32).toarray()
    model_name = f"tfidf-char-2to3gram-d{dense.shape[1]}"
    state = {"provider": "tfidf", "model": model_name, "vectorizer": v}
    return dense, model_name, state


# ---------- Provider: OpenAI ----------

def _openai_embed(records, text_field, model, batch_size, max_retries):
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("ERROR: openai package not installed. Run: pip install openai")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("ERROR: OPENAI_API_KEY environment variable not set")

    client = OpenAI(api_key=api_key)
    corpus = [(r.get(text_field) or "") for r in records]
    n = len(corpus)

    vectors = []
    print(f"Encoding {n:,} records via OpenAI {model} (batch={batch_size})", file=sys.stderr)
    start = time.time()

    for batch_start in range(0, n, batch_size):
        batch = corpus[batch_start : batch_start + batch_size]
        batch = [t if t else " " for t in batch]

        for attempt in range(1, max_retries + 1):
            try:
                resp = client.embeddings.create(model=model, input=batch)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == max_retries:
                    print(f"ERROR: batch {batch_start} failed after {max_retries} retries: {e}", file=sys.stderr)
                    raise
                wait = 2 ** attempt
                print(f"WARN: batch {batch_start} attempt {attempt} failed: {e}; retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)

        for item in resp.data:
            vectors.append(item.embedding)

        done = batch_start + len(batch)
        if done % (batch_size * 10) == 0 or done == n:
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (n - done) / rate if rate > 0 else 0
            print(f"  progress: {done:,}/{n:,}  ({100*done/n:.0f}%)  rate={rate:.1f}/s  ETA={eta:.0f}s", file=sys.stderr)

    dense = np.asarray(vectors, dtype=np.float32)
    state = {"provider": "openai", "model": model}
    return dense, model, state


# ---------- Provider: Gemini ----------

def _gemini_embed(records, text_field, model, batch_size, max_retries, sleep_sec):
    """Encode via Google Gemini embedding API with throttling for free tier.

    Free tier: 100 RPM. With sleep_sec=0.7 we cap ourselves at ~85 RPM.
    Model names:
      gemini-embedding-001            (new, default, 768/1536/3072 dim)
      models/text-embedding-004       (legacy, 768 dim, separate quota)
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        sys.exit("ERROR: google-genai package not installed. Run: pip install google-genai")

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable not set")

    client = genai.Client(api_key=api_key)
    corpus = [(r.get(text_field) or "") for r in records]
    n = len(corpus)

    vectors = []
    print(f"Encoding {n:,} records via Gemini {model} (batch={batch_size}, sleep={sleep_sec}s)", file=sys.stderr)
    start = time.time()

    for batch_start in range(0, n, batch_size):
        batch = corpus[batch_start : batch_start + batch_size]
        batch = [t if t else " " for t in batch]

        for attempt in range(1, max_retries + 1):
            try:
                resp = client.models.embed_content(
                    model=model,
                    contents=batch,
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
                )
                break
            except Exception as e:  # noqa: BLE001
                err_str = str(e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                    wait = 30 if attempt < max_retries else 60
                    print(f"WARN: batch {batch_start} attempt {attempt} hit rate limit; sleeping {wait}s", file=sys.stderr)
                else:
                    if attempt == max_retries:
                        print(f"ERROR: batch {batch_start} failed after {max_retries} retries: {e}", file=sys.stderr)
                        raise
                    wait = 2 ** attempt
                    print(f"WARN: batch {batch_start} attempt {attempt} failed: {e}; retrying in {wait}s", file=sys.stderr)
                if attempt == max_retries:
                    print(f"ERROR: batch {batch_start} exhausted retries", file=sys.stderr)
                    raise
                time.sleep(wait)

        for emb in resp.embeddings:
            vectors.append(emb.values)

        done = batch_start + len(batch)
        if done % (batch_size * 5) == 0 or done == n:
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (n - done) / rate if rate > 0 else 0
            print(f"  progress: {done:,}/{n:,}  ({100*done/n:.0f}%)  rate={rate:.1f}/s  ETA={eta:.0f}s", file=sys.stderr)

        if sleep_sec > 0 and done < n:
            time.sleep(sleep_sec)

    dense = np.asarray(vectors, dtype=np.float32)
    state = {"provider": "gemini", "model": model}
    return dense, model, state


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="Generate embeddings for JuriCode-JP NDJSON.")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--provider", choices=["tfidf", "openai", "gemini"], default="tfidf")
    ap.add_argument("--text-field", default="text")
    ap.add_argument("--limit", type=int, default=None)

    ap.add_argument("--max-features", type=int, default=10000, help="(tfidf only)")

    ap.add_argument("--openai-model", default="text-embedding-3-small")
    ap.add_argument("--openai-batch-size", type=int, default=100)
    ap.add_argument("--openai-max-retries", type=int, default=5)

    ap.add_argument("--gemini-model", default="gemini-embedding-001")
    ap.add_argument(
        "--gemini-batch-size",
        type=int,
        default=100,
        help="Gemini batch size (free tier: 100 is safe; check current quotas).",
    )
    ap.add_argument("--gemini-max-retries", type=int, default=5)
    ap.add_argument(
        "--gemini-sleep-between-batches",
        type=float,
        default=0.7,
        help="(gemini only) Sleep seconds between batches to respect free-tier RPM (default: 0.7 ≈ 85 RPM).",
    )

    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    records = _read_records(args.input, args.limit)
    if not records:
        print("ERROR: no records read", file=sys.stderr)
        return 1
    print(f"Loaded {len(records):,} records", file=sys.stderr)

    if args.provider == "tfidf":
        dense, model_name, state = _tfidf_embed(records, args.text_field, args.max_features)
    elif args.provider == "openai":
        dense, model_name, state = _openai_embed(
            records, args.text_field, args.openai_model,
            args.openai_batch_size, args.openai_max_retries,
        )
    elif args.provider == "gemini":
        dense, model_name, state = _gemini_embed(
            records, args.text_field, args.gemini_model,
            args.gemini_batch_size, args.gemini_max_retries,
            args.gemini_sleep_between_batches,
        )
    else:
        return 1

    print(f"Embeddings: shape={dense.shape}, model={model_name}", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    npy = args.output.with_suffix(".npy")
    meta = args.output.with_suffix(".meta.jsonl")
    vec = args.output.with_suffix(".vec.pkl")

    np.save(npy, dense)
    print(f"Saved .npy:  {npy} ({dense.nbytes / 1024 / 1024:.1f} MB)", file=sys.stderr)

    with meta.open("w", encoding="utf-8") as fh:
        for r in records:
            m = {k: r.get(k) for k in _META_FIELDS}
            m["embedding_model"] = model_name
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"Saved meta:  {meta}", file=sys.stderr)

    with vec.open("wb") as fh:
        pickle.dump(state, fh)
    print(f"Saved vec:   {vec}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""JuriCode-JP Embedding Generator.

Pluggable provider design:
  --provider tfidf   : sklearn TF-IDF char n-gram baseline (offline, no key)
  --provider openai  : OpenAI text-embedding-3-small/large (needs OPENAI_API_KEY)
  --provider gemini  : Google Gemini embedding (needs GEMINI_API_KEY or GOOGLE_API_KEY)

Outputs:
  <output>.npy        : float32 (N, D) numpy matrix
  <output>.meta.jsonl : per-record metadata (article_id, law_name, etc.)
  <output>.vec.pkl    : provider state needed for retrieve.py to encode queries

Robustness (A-1/A-2/A-3):
  - Index-assert: dense.shape[0] must equal len(records); per-batch count also verified.
  - Resume: existing .meta.jsonl / .npy are loaded; already-processed records skipped.
  - Atomic save: writes to .tmp files then os.replace() -- crash-safe.
  - Checkpoint: Gemini provider saves every --checkpoint-every records (default 1000).
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

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


def _read_records(path: Path, limit: int | None) -> list[dict]:
    records: list[dict] = []
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


# ============================================================
# Robustness helpers (A-1 / A-2 / A-3)
# ============================================================


def _record_resume_key(r: dict) -> str:
    """Unique resume key: chunk_id preferred, fallback to article_id."""
    return str(r.get("chunk_id") or r.get("article_id") or "")


def _assert_batch_count(expected: int, got: int, batch_start: int) -> None:
    """Raise ValueError if batch response count != input count (A-1)."""
    if got != expected:
        raise ValueError(
            f"Index integrity error at batch_start={batch_start}: "
            f"sent {expected} texts, received {got} embeddings"
        )


def _check_index_integrity(dense: np.ndarray, n_records: int) -> None:  # noqa: F821
    """Raise ValueError if dense row count != n_records (A-1)."""
    if dense.shape[0] != n_records:
        raise ValueError(
            f"Index integrity error: dense has {dense.shape[0]} rows but expected {n_records}"
        )


def _load_resume_state(meta_path: Path, npy_path: Path) -> tuple[list[dict], np.ndarray | None]:  # noqa: F821
    """Load existing meta records and embeddings for resume (A-2).

    Returns (existing_records, existing_dense) or ([], None) if no prior state.
    Raises ValueError if .npy row count != .meta.jsonl line count.
    """
    import numpy as np

    if not meta_path.exists() or not npy_path.exists():
        return [], None
    existing_records: list[dict] = []
    with meta_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                existing_records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if not existing_records:
        return [], None
    existing_dense = np.load(npy_path)
    if existing_dense.shape[0] != len(existing_records):
        raise ValueError(
            f"Resume integrity error: .npy has {existing_dense.shape[0]} rows but "
            f".meta.jsonl has {len(existing_records)} entries. "
            "Delete both files and re-run."
        )
    print(
        f"Resume: loaded {len(existing_records):,} existing records from {meta_path.name}",
        file=sys.stderr,
    )
    return existing_records, existing_dense


def _save_atomic(
    npy: Path,
    meta: Path,
    vec: Path,
    dense: np.ndarray,  # noqa: F821
    records: list[dict],
    model_name: str,
    state: dict,
) -> None:
    """Save all 3 output files atomically via .tmp → os.replace() (A-3)."""
    import numpy as np

    npy_tmp = npy.with_suffix(".tmp.npy")
    meta_tmp = meta.parent / (meta.name + ".tmp")
    vec_tmp = vec.parent / (vec.name + ".tmp")
    try:
        np.save(npy_tmp, dense)
        with meta_tmp.open("w", encoding="utf-8") as fh:
            for r in records:
                m = {k: r.get(k) for k in _META_FIELDS}
                # Preserve existing embedding_model on resumed records.
                m["embedding_model"] = r.get("embedding_model") or model_name
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")
        with vec_tmp.open("wb") as fh:
            pickle.dump(state, fh)
        os.replace(npy_tmp, npy)
        os.replace(meta_tmp, meta)
        os.replace(vec_tmp, vec)
    except Exception:
        for tmp in (npy_tmp, meta_tmp, vec_tmp):
            if tmp.exists():
                tmp.unlink()
        raise


# ---------- Provider: TF-IDF ----------


def _tfidf_embed(records: list[dict], text_field: str, max_features: int) -> tuple:
    import numpy as np
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


def _openai_embed(
    records: list[dict],
    text_field: str,
    model: str,
    batch_size: int,
    max_retries: int,
) -> tuple:
    import numpy as np

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

    vectors: list = []
    print(f"Encoding {n:,} records via OpenAI {model} (batch={batch_size})", file=sys.stderr)
    start = time.time()

    for batch_start in range(0, n, batch_size):
        batch = corpus[batch_start : batch_start + batch_size]
        batch = [t if t else " " for t in batch]

        for attempt in range(1, max_retries + 1):
            try:
                resp = client.embeddings.create(model=model, input=batch)
                break
            except Exception as e:
                if attempt == max_retries:
                    print(
                        f"ERROR: batch {batch_start} failed after {max_retries} retries: {e}",
                        file=sys.stderr,
                    )
                    raise
                wait = 2**attempt
                print(
                    f"WARN: batch {batch_start} attempt {attempt} failed: {e}; retrying in {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)

        # Per-batch integrity check (A-1)
        _assert_batch_count(len(batch), len(resp.data), batch_start)
        for item in resp.data:
            vectors.append(item.embedding)

        done = batch_start + len(batch)
        if done % (batch_size * 10) == 0 or done == n:
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (n - done) / rate if rate > 0 else 0
            print(
                f"  progress: {done:,}/{n:,}  ({100 * done / n:.0f}%)  "
                f"rate={rate:.1f}/s  ETA={eta:.0f}s",
                file=sys.stderr,
            )

    dense = np.asarray(vectors, dtype=np.float32)
    state = {"provider": "openai", "model": model}
    return dense, model, state


# ---------- Provider: Gemini ----------


def _gemini_embed(
    records: list[dict],
    text_field: str,
    model: str,
    batch_size: int,
    max_retries: int,
    sleep_sec: float,
    checkpoint_fn=None,
    checkpoint_every: int = 0,
) -> tuple:
    """Encode via Google Gemini embedding API with throttling for free tier.

    Free tier: 100 RPM. With sleep_sec=0.7 we cap ourselves at ~85 RPM.
    Model names:
      gemini-embedding-001            (new, default, 768/1536/3072 dim)
      models/text-embedding-004       (legacy, 768 dim, separate quota)
    """
    import numpy as np

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
    state = {"provider": "gemini", "model": model}

    vectors: list = []
    print(
        f"Encoding {n:,} records via Gemini {model} (batch={batch_size}, sleep={sleep_sec}s)",
        file=sys.stderr,
    )
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
            except Exception as e:
                err_str = str(e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                    wait = 30 if attempt < max_retries else 60
                    print(
                        f"WARN: batch {batch_start} attempt {attempt} hit rate limit; "
                        f"sleeping {wait}s",
                        file=sys.stderr,
                    )
                else:
                    if attempt == max_retries:
                        print(
                            f"ERROR: batch {batch_start} failed after {max_retries} retries: {e}",
                            file=sys.stderr,
                        )
                        raise
                    wait = 2**attempt
                    print(
                        f"WARN: batch {batch_start} attempt {attempt} failed: {e}; "
                        f"retrying in {wait}s",
                        file=sys.stderr,
                    )
                if attempt == max_retries:
                    print(f"ERROR: batch {batch_start} exhausted retries", file=sys.stderr)
                    raise
                time.sleep(wait)

        # Per-batch integrity check (A-1)
        _assert_batch_count(len(batch), len(resp.embeddings), batch_start)
        for emb in resp.embeddings:
            vectors.append(emb.values)

        done = len(vectors)
        if done % (batch_size * 5) == 0 or done == n:
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (n - done) / rate if rate > 0 else 0
            print(
                f"  progress: {done:,}/{n:,}  ({100 * done / n:.0f}%)  "
                f"rate={rate:.1f}/s  ETA={eta:.0f}s",
                file=sys.stderr,
            )

        # Checkpoint (A-3): save partial results atomically every N records
        if checkpoint_fn and checkpoint_every > 0 and done % checkpoint_every == 0:
            partial = np.asarray(vectors, dtype=np.float32)
            checkpoint_fn(partial, records[:done], state)

        if sleep_sec > 0 and done < n:
            time.sleep(sleep_sec)

    dense = np.asarray(vectors, dtype=np.float32)
    return dense, model, state


# ---------- CLI ----------


def main() -> int:
    import numpy as np

    ap = argparse.ArgumentParser(description="Generate embeddings for JuriCode-JP NDJSON.")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--provider", choices=["tfidf", "openai", "gemini"], default="tfidf")
    ap.add_argument("--text-field", default="text")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--checkpoint-every",
        type=int,
        default=1000,
        help="(gemini/openai) Save checkpoint every N records (0 = disabled).",
    )

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
        help="(gemini only) Sleep seconds between batches to respect free-tier RPM.",
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

    # Build output paths (must be done before resume check)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # NOTE: with_suffix() breaks on dot-containing names like "v0.2-gemini-17967",
    # so we use string concatenation.
    npy = args.output.parent / (args.output.name + ".npy")
    meta = args.output.parent / (args.output.name + ".meta.jsonl")
    vec = args.output.parent / (args.output.name + ".vec.pkl")

    # Resume: skip already-processed records (A-2)
    existing_records, existing_dense = _load_resume_state(meta, npy)
    if existing_records:
        processed_keys = {_record_resume_key(r) for r in existing_records}
        new_records = [r for r in records if _record_resume_key(r) not in processed_keys]
        print(
            f"Resume: {len(existing_records):,} already embedded, {len(new_records):,} remaining",
            file=sys.stderr,
        )
        if not new_records:
            print("All records already embedded. Done.", file=sys.stderr)
            return 0
    else:
        new_records = records

    if args.provider == "tfidf":
        new_dense, model_name, state = _tfidf_embed(new_records, args.text_field, args.max_features)
    elif args.provider == "openai":
        new_dense, model_name, state = _openai_embed(
            new_records,
            args.text_field,
            args.openai_model,
            args.openai_batch_size,
            args.openai_max_retries,
        )
    elif args.provider == "gemini":
        model_name = args.gemini_model

        def _checkpoint_fn(
            partial_new_dense: np.ndarray,
            partial_new_records: list[dict],
            cp_state: dict,
        ) -> None:
            if existing_dense is not None:
                combined = np.concatenate([existing_dense, partial_new_dense], axis=0)
                combined_recs = existing_records + list(partial_new_records)
            else:
                combined = partial_new_dense
                combined_recs = list(partial_new_records)
            _save_atomic(npy, meta, vec, combined, combined_recs, model_name, cp_state)
            print(
                f"  Checkpoint: {combined.shape[0]:,} records saved to {npy.name}",
                file=sys.stderr,
            )

        new_dense, model_name, state = _gemini_embed(
            new_records,
            args.text_field,
            model_name,
            args.gemini_batch_size,
            args.gemini_max_retries,
            args.gemini_sleep_between_batches,
            checkpoint_fn=_checkpoint_fn,
            checkpoint_every=args.checkpoint_every,
        )
    else:
        return 1

    # Index integrity assert (A-1): must match before saving
    _check_index_integrity(new_dense, len(new_records))

    # Combine with existing embeddings from resume
    if existing_dense is not None and len(existing_records) > 0:
        combined_dense = np.concatenate([existing_dense, new_dense], axis=0)
        combined_records = existing_records + new_records
    else:
        combined_dense = new_dense
        combined_records = new_records

    # Final sanity assert
    assert combined_dense.shape[0] == len(combined_records)

    print(
        f"Embeddings: shape={combined_dense.shape}, model={model_name}",
        file=sys.stderr,
    )

    # Atomic save (A-3)
    _save_atomic(npy, meta, vec, combined_dense, combined_records, model_name, state)

    print(
        f"Saved .npy:  {npy} ({combined_dense.nbytes / 1024 / 1024:.1f} MB)",
        file=sys.stderr,
    )
    print(f"Saved meta:  {meta}", file=sys.stderr)
    print(f"Saved vec:   {vec}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

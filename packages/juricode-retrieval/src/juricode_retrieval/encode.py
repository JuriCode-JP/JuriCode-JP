"""Query embedding for dense retrieval.

Single source of truth for `_encode_queries`, moved verbatim from
tools/embed/retrieve.py. The openai / gemini provider clients and numpy are
imported lazily inside the function, so neither this module nor its consumers
pay for a provider they do not use.
"""

from __future__ import annotations

import os
import sys


def _encode_queries(questions, state):
    import numpy as np  # lazy import (FU-506)

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

    if provider == "gemini":
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            sys.exit("ERROR: google-genai package not installed. Run: pip install google-genai")
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            sys.exit("ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable not set")
        client = genai.Client(api_key=api_key)
        model = state["model"]
        BATCH_SIZE = 100
        MAX_RETRIES = 5
        all_embeddings = []
        import time as _time

        for batch_start in range(0, len(questions), BATCH_SIZE):
            batch = questions[batch_start : batch_start + BATCH_SIZE]
            last_err = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = client.models.embed_content(
                        model=model,
                        contents=batch,
                        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
                    )
                    all_embeddings.extend(emb.values for emb in resp.embeddings)
                    break
                except Exception as e:
                    last_err = e
                    if attempt < MAX_RETRIES:
                        # 429 RESOURCE_EXHAUSTED: wait at least 65s for quota reset
                        is_429 = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                        wait = 65.0 if is_429 else 1.5**attempt
                        print(
                            f"  [gemini retry {attempt}/{MAX_RETRIES}] {type(e).__name__}: waiting {wait:.1f}s",
                            file=sys.stderr,
                        )
                        _time.sleep(wait)
                    else:
                        print(
                            f"  [gemini FAILED after {MAX_RETRIES} retries] {last_err}",
                            file=sys.stderr,
                        )
                        raise
        return np.asarray(all_embeddings, dtype=np.float32)

    sys.exit(f"ERROR: unsupported provider in artefacts: {provider!r}")

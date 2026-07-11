"""Unit tests for retrieve.py article_id dedup (A3-D).

Covers the dedup rule that is now ON by default: keep the top-scoring chunk per article_id,
preserve rank order, fall back to directive_id -> chunk_id for non-article records (so distinct
tsutatsu/taxanswer chunks are not collapsed onto a single None bucket), and behave sanely on
degenerate (empty / single) candidate rows.

numpy is imported lazily inside retrieve.py (it is not a declared/CI dependency). The dedup KEY
logic (RetrievalPipeline._dedup_keys) is pure-Python and runs everywhere; the array-shaping
dedup_by_article() needs numpy, so those cases use pytest.importorskip and skip when numpy is
absent (mirrors the numpy-only sibling test_retrieve.py being excluded from the CI allow-list).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import retrieve as R  # noqa: E402  (numpy-free at import time)

# ---- pure-Python: dedup KEY fallback (the new A3-D logic) ----


def test_pipeline_dedup_key_fallback():
    records = [
        {"article_id": "A", "chunk_id": "c0"},
        {"article_id": None, "directive_id": "d1", "chunk_id": "c1"},
        {"article_id": None, "directive_id": None, "chunk_id": "c2"},
    ]
    p = R.RetrievalPipeline({"provider": "tfidf"}, records)
    assert p._dedup_keys == ["A", "d1", "c2"]


def test_pipeline_distinct_nonarticle_keys_not_collapsed():
    # Two article_id=None records with distinct chunk_ids must get DISTINCT dedup keys,
    # so their sub-chunks are not merged onto a single None bucket.
    records = [
        {"article_id": None, "chunk_id": "c0"},
        {"article_id": None, "chunk_id": "c1"},
        {"article_id": "A", "chunk_id": "c2"},
    ]
    p = R.RetrievalPipeline({"provider": "tfidf"}, records)
    assert p._dedup_keys == ["c0", "c1", "A"]
    assert len(set(p._dedup_keys)) == 3


# ---- numpy-backed: dedup_by_article array behaviour (skips when numpy absent) ----


def test_dedup_keeps_top_scoring_chunk_per_article():
    np = pytest.importorskip("numpy")
    article_ids = ["A", "A", "B", "A", "C"]
    out = R.dedup_by_article(np.array([[0, 1, 2, 3, 4]]), article_ids, 3)
    assert list(out[0]) == [0, 2, 4]  # first of A, then B, then C


def test_dedup_order_preserved():
    np = pytest.importorskip("numpy")
    article_ids = ["B", "A", "A", "C"]
    out = R.dedup_by_article(np.array([[0, 1, 2, 3]]), article_ids, 4)
    assert list(out[0]) == [0, 1, 3, -1]  # B, A, C, pad


def test_no_dedup_keeps_duplicates_contrast():
    np = pytest.importorskip("numpy")
    article_ids = ["A", "A", "B"]
    top = np.array([[0, 1, 2]])
    assert list(R.dedup_by_article(top, article_ids, 3)[0]) == [0, 2, -1]  # dedup drops dup A
    assert list(top[0][:3]) == [0, 1, 2]  # raw (no-dedup) keeps it


def test_dedup_distinct_nonarticle_not_collapsed_end_to_end():
    np = pytest.importorskip("numpy")
    records = [
        {"article_id": None, "chunk_id": "c0"},
        {"article_id": None, "chunk_id": "c1"},
        {"article_id": "A", "chunk_id": "c2"},
    ]
    p = R.RetrievalPipeline({"provider": "tfidf"}, records)
    out = p.dedup_by_article(np.array([[0, 1, 2]]), 3)
    assert list(out[0]) == [0, 1, 2]  # all distinct keys -> none collapsed


def test_dedup_degenerate_single_and_empty():
    np = pytest.importorskip("numpy")
    out = R.dedup_by_article(np.array([[0]]), ["A"], 3)
    assert list(out[0]) == [0, -1, -1]
    out2 = R.dedup_by_article(np.array([[-1, -1]]), ["A"], 2)
    assert list(out2[0]) == [-1, -1]

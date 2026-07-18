"""Unit tests for the dense-retrieval primitives.

The primitives compute on numpy arrays, and numpy is not a CI dev dependency
(it is imported lazily in the package), so the numpy-backed cases use
pytest.importorskip and skip when numpy is absent -- mirroring the sibling
tools/embed/tests numpy-only tests. The identity of the re-imported objects is
asserted separately in tools/embed/tests/test_retrieve_reexports.py (numpy-free).
"""

from __future__ import annotations

import json

import pytest

from juricode_retrieval import _cosine_topk, _encode_queries, _load_artefacts, dedup_by_article


def test_load_artefacts_reads_matrix_records_state(tmp_path):
    np = pytest.importorskip("numpy")
    prefix = tmp_path / "toy-index"
    np.save(prefix.parent / (prefix.name + ".npy"), np.array([[1.0, 0.0], [0.0, 1.0]]))
    (prefix.parent / (prefix.name + ".meta.jsonl")).write_text(
        json.dumps({"article_id": "A"}) + "\n" + json.dumps({"article_id": "B"}) + "\n",
        encoding="utf-8",
    )
    (prefix.parent / (prefix.name + ".vec.json")).write_text(
        json.dumps({"provider": "gemini", "model": "toy"}), encoding="utf-8"
    )

    matrix, records, state = _load_artefacts(prefix)
    assert matrix.shape == (2, 2)
    assert [r["article_id"] for r in records] == ["A", "B"]
    assert state == {"provider": "gemini", "model": "toy"}


def test_load_artefacts_missing_fails_loud(tmp_path):
    pytest.importorskip("numpy")
    with pytest.raises(FileNotFoundError):
        _load_artefacts(tmp_path / "does-not-exist")


def test_dedup_by_article_known_input():
    np = pytest.importorskip("numpy")
    article_ids = ["A", "A", "B", "A", "C"]
    out = dedup_by_article(np.array([[0, 1, 2, 3, 4]]), article_ids, 3)
    assert list(out[0]) == [0, 2, 4]  # first of A, then B, then C


def test_cosine_topk_known_vectors():
    np = pytest.importorskip("numpy")
    query = np.array([[1.0, 0.0]])
    corpus = np.array([[0.0, 1.0], [1.0, 0.0], [0.9, 0.1]])
    _sims, top_idx = _cosine_topk(query, corpus, 2)
    assert list(top_idx[0]) == [1, 2]  # exact match, then the near-parallel row


def test_encode_queries_unsupported_provider_exits():
    # Provider detection only: no API call, no client import. The catch-all
    # branch exits on an unknown provider.
    pytest.importorskip("numpy")
    with pytest.raises(SystemExit):
        _encode_queries(["q"], {"provider": "no-such-provider"})

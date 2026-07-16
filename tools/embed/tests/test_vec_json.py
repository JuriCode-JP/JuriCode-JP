"""Tests for the .vec.json index sidecar (portable {provider, model}).

Why: the distributed index must not ship a pickle (unpickling runs arbitrary
code in the consumer). embed.py writes .vec.json for API providers alongside
.vec.pkl; retrieve.py prefers .vec.json and falls back to .vec.pkl. These lock
the write side and read side together so a future index cannot silently
regress to pickle-only.

numpy is not installed in CI (not in .[dev]); the artefact I/O needs it, so the
cases use ``pytest.importorskip`` and skip in CI, run locally (正本パターン:
test_retrieve_dedup.py).
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import embed as E  # noqa: E402
import retrieve as R  # noqa: E402


def _paths(tmp_path: Path):
    base = tmp_path / "idx"
    return (
        Path(str(base) + ".npy"),
        Path(str(base) + ".meta.jsonl"),
        Path(str(base) + ".vec.pkl"),
        Path(str(base) + ".vec.json"),
        base,
    )


def _save(tmp_path: Path, state: dict):
    """Write a 2x4 dummy index via the production _save_atomic."""
    np = pytest.importorskip("numpy")
    npy, meta, vec, vecjson, base = _paths(tmp_path)
    dense = np.zeros((2, 4), dtype=np.float32)
    records = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    E._save_atomic(npy, meta, vec, dense, records, state["model"], state)
    return npy, meta, vec, vecjson, base


GEMINI = {"provider": "gemini", "model": "gemini-embedding-001"}


def test_save_atomic_writes_vec_json_for_api_provider(tmp_path):
    _npy, _meta, vec, vecjson, _base = _save(tmp_path, dict(GEMINI))
    assert vec.exists() and vecjson.exists()
    assert json.loads(vecjson.read_text(encoding="utf-8")) == GEMINI


def test_save_atomic_skips_vec_json_for_tfidf(tmp_path):
    # tfidf state carries the fitted vectorizer (not portable) -> pkl only.
    state = {"provider": "tfidf", "model": "tfidf-x", "vectorizer": [1, 2, 3]}
    _npy, _meta, vec, vecjson, _base = _save(tmp_path, state)
    assert vec.exists() and not vecjson.exists()


def test_load_artefacts_prefers_vec_json_over_pkl(tmp_path):
    _npy, _meta, vec, _vecjson, base = _save(tmp_path, dict(GEMINI))
    # Make the two disagree so we can tell which was read; .vec.json must win.
    vec.write_bytes(pickle.dumps({"provider": "gemini", "model": "PKL-SHOULD-LOSE"}))
    _matrix, _records, state = R._load_artefacts(base)
    assert state == GEMINI


def test_load_artefacts_falls_back_to_pkl(tmp_path):
    _npy, _meta, _vec, vecjson, base = _save(tmp_path, dict(GEMINI))
    vecjson.unlink()  # only .vec.pkl remains (existing local builds)
    _matrix, _records, state = R._load_artefacts(base)
    assert state == GEMINI


def test_load_artefacts_json_only_works(tmp_path):
    # A distributed snapshot ships only .vec.json (no pickle).
    _npy, _meta, vec, _vecjson, base = _save(tmp_path, dict(GEMINI))
    vec.unlink()
    _matrix, _records, state = R._load_artefacts(base)
    assert state == GEMINI


def test_load_artefacts_missing_both_raises(tmp_path):
    _npy, _meta, vec, vecjson, base = _save(tmp_path, dict(GEMINI))
    vec.unlink()
    vecjson.unlink()
    with pytest.raises(FileNotFoundError):
        R._load_artefacts(base)


def test_roundtrip_write_then_read(tmp_path):
    """embed writes -> retrieve reads back the same {provider, model}."""
    _npy, _meta, _vec, _vecjson, base = _save(tmp_path, dict(GEMINI))
    _matrix, records, state = R._load_artefacts(base)
    assert state == GEMINI
    assert [r["chunk_id"] for r in records] == ["a", "b"]

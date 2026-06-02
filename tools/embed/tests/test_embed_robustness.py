"""tests/test_embed_robustness.py -- embed.py 堅牢化の単体テスト (Phase A).

T7: 1件欠落を注入 → index-assert が発火して保存されず例外停止
T8: 途中中断 → 再実行で件数一致・重複 0
T9: .tmp → replace でクラッシュ時に本番無傷

API 課金なし。sklearn tfidf を使用。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# embed.py を import 可能にする (parent dir = tools/embed/)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from embed import (  # noqa: E402
    _assert_batch_count,
    _check_index_integrity,
    _load_resume_state,
    _record_resume_key,
    _save_atomic,
)

# ============================================================
# T7: index-assert が発火して保存されず例外停止
# ============================================================


def test_t7_batch_count_mismatch_raises():
    """Per-batch: sent 5 texts, received 4 → ValueError (not silent skip)."""
    with pytest.raises(ValueError, match="Index integrity error"):
        _assert_batch_count(expected=5, got=4, batch_start=0)


def test_t7_batch_count_ok_no_raise():
    _assert_batch_count(expected=3, got=3, batch_start=0)


def test_t7_index_integrity_mismatch_raises():
    """dense.shape[0] != n_records → ValueError."""
    dense = np.zeros((10, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="Index integrity error"):
        _check_index_integrity(dense, 11)


def test_t7_index_integrity_ok_no_raise():
    dense = np.zeros((5, 4), dtype=np.float32)
    _check_index_integrity(dense, 5)


# ============================================================
# T8: resume — 途中中断 → 再実行で件数一致・重複 0
# ============================================================


def _make_records(n: int) -> list[dict]:
    return [
        {
            "chunk_id": f"chunk-{i}",
            "article_id": f"art-{i}",
            "text": f"テスト法令 第{i}条",
            "law_id": "TEST",
            "law_name_ja": "テスト法",
            "article_number": str(i),
            "phase_category": "phase1",
            "hen_name_ja": None,
            "shou_name_ja": None,
        }
        for i in range(n)
    ]


def test_t8_resume_skip_already_processed(tmp_path: Path):
    """After saving 3 records, loading resume state returns 3 records with correct dense."""
    records = _make_records(3)
    dense = np.random.rand(3, 4).astype(np.float32)
    npy = tmp_path / "test.npy"
    meta = tmp_path / "test.meta.jsonl"
    vec = tmp_path / "test.vec.pkl"

    state = {"provider": "tfidf", "model": "test-model"}
    _save_atomic(npy, meta, vec, dense, records, "test-model", state)

    loaded_records, loaded_dense = _load_resume_state(meta, npy)

    assert len(loaded_records) == 3
    assert loaded_dense is not None
    assert loaded_dense.shape == (3, 4)
    np.testing.assert_array_almost_equal(loaded_dense, dense)


def test_t8_resume_keys_no_duplicates(tmp_path: Path):
    """Processing 5 total where 3 are already done → 2 new, no duplicates."""
    all_records = _make_records(5)
    existing_3 = all_records[:3]
    dense_3 = np.random.rand(3, 4).astype(np.float32)

    npy = tmp_path / "test.npy"
    meta = tmp_path / "test.meta.jsonl"
    vec = tmp_path / "test.vec.pkl"
    state = {"provider": "tfidf", "model": "test-model"}
    _save_atomic(npy, meta, vec, dense_3, existing_3, "test-model", state)

    loaded_records, _ = _load_resume_state(meta, npy)
    processed_keys = {_record_resume_key(r) for r in loaded_records}

    new_records = [r for r in all_records if _record_resume_key(r) not in processed_keys]
    assert len(new_records) == 2

    # Simulate merging: total 5, no duplicates
    all_chunk_ids = [r["chunk_id"] for r in loaded_records + new_records]
    assert len(all_chunk_ids) == len(set(all_chunk_ids))


def test_t8_resume_no_prior_state(tmp_path: Path):
    """When .npy and .meta.jsonl do not exist, resume returns empty."""
    npy = tmp_path / "nonexistent.npy"
    meta = tmp_path / "nonexistent.meta.jsonl"
    loaded_records, loaded_dense = _load_resume_state(meta, npy)
    assert loaded_records == []
    assert loaded_dense is None


def test_t8_resume_count_mismatch_raises(tmp_path: Path):
    """If .npy row count != .meta.jsonl line count, raise ValueError (corrupted state)."""
    records = _make_records(3)
    dense = np.zeros((3, 4), dtype=np.float32)
    npy = tmp_path / "test.npy"
    meta = tmp_path / "test.meta.jsonl"
    vec = tmp_path / "test.vec.pkl"
    state = {"provider": "tfidf", "model": "m"}
    _save_atomic(npy, meta, vec, dense, records, "m", state)

    # Corrupt: replace .npy with wrong shape (5 rows instead of 3)
    wrong = np.zeros((5, 4), dtype=np.float32)
    np.save(npy, wrong)

    with pytest.raises(ValueError, match="Resume integrity error"):
        _load_resume_state(meta, npy)


# ============================================================
# T9: .tmp → replace でクラッシュ時に本番無傷
# ============================================================


def test_t9_tmp_file_removed_on_exception(tmp_path: Path):
    """If an error occurs after .tmp creation, .tmp files are cleaned up."""
    records = _make_records(2)
    dense = np.zeros((2, 4), dtype=np.float32)
    state = {"provider": "tfidf", "model": "m"}

    npy = tmp_path / "test.npy"
    meta = tmp_path / "test.meta.jsonl"
    vec = tmp_path / "test.vec.pkl"

    # Make state un-picklable by patching pickle.dump to raise
    import pickle as pk_module
    import unittest.mock as mock

    with mock.patch.object(pk_module, "dump", side_effect=RuntimeError("sim")):
        with pytest.raises(RuntimeError, match="sim"):
            _save_atomic(npy, meta, vec, dense, records, "m", state)

    # Original files must not exist (nothing was replaced)
    assert not npy.exists()
    assert not meta.exists()
    assert not vec.exists()
    # .tmp files must be cleaned up
    assert not (tmp_path / "test.tmp.npy").exists()
    assert not (tmp_path / "test.meta.jsonl.tmp").exists()
    assert not (tmp_path / "test.vec.pkl.tmp").exists()


def test_t9_atomic_save_writes_correct_content(tmp_path: Path):
    """Normal atomic save produces correct .npy, .meta.jsonl, .vec.pkl."""
    records = _make_records(4)
    dense = np.random.rand(4, 8).astype(np.float32)
    state = {"provider": "tfidf", "model": "tfidf-test"}

    npy = tmp_path / "out.npy"
    meta = tmp_path / "out.meta.jsonl"
    vec = tmp_path / "out.vec.pkl"

    _save_atomic(npy, meta, vec, dense, records, "tfidf-test", state)

    loaded = np.load(npy)
    np.testing.assert_array_almost_equal(loaded, dense)

    meta_records = []
    with meta.open(encoding="utf-8") as fh:
        for line in fh:
            meta_records.append(json.loads(line.strip()))
    assert len(meta_records) == 4
    assert meta_records[0]["chunk_id"] == "chunk-0"
    assert meta_records[0]["embedding_model"] == "tfidf-test"

    import pickle

    with vec.open("rb") as fh:
        loaded_state = pickle.load(fh)
    assert loaded_state["provider"] == "tfidf"


# ============================================================
# record_resume_key fallback
# ============================================================


def test_record_resume_key_uses_chunk_id():
    r = {"chunk_id": "c-1", "article_id": "a-1"}
    assert _record_resume_key(r) == "c-1"


def test_record_resume_key_falls_back_to_article_id():
    r = {"article_id": "a-1"}
    assert _record_resume_key(r) == "a-1"


def test_record_resume_key_empty_fallback():
    r = {}
    assert _record_resume_key(r) == ""

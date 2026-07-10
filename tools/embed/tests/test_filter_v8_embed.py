"""tests/test_filter_v8_embed.py -- A2 embed 事前フィルタの hermetic 単体テスト."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import filter_v8_embed as F  # noqa: E402


def test_filter_excludes_skip_and_empty():
    records = [
        {"chunk_id": "a", "text": "本文A", "embed_skip": False},
        {"chunk_id": "b", "text": "本文B"},  # embed_skip 不在 = 対象
        {"chunk_id": "c", "text": "z", "embed_skip": True},  # rollup skip
        {"chunk_id": "d", "text": "   "},  # 空白のみ = 除外
        {"chunk_id": "e", "text": ""},  # 空 = 除外
    ]
    kept, report = F.filter_embed_rows(records)
    assert [r["chunk_id"] for r in kept] == ["a", "b"]
    assert report["n_embed_target"] == 2
    assert report["skipped_embed_skip"] == 1
    assert report["excluded_empty_text"] == 2
    assert set(report["excluded_empty_ids"]) == {"d", "e"}


def test_filter_raises_on_duplicate_chunk_id():
    records = [
        {"chunk_id": "dup", "text": "x"},
        {"chunk_id": "dup", "text": "y"},
    ]
    with pytest.raises(ValueError, match="not unique"):
        F.filter_embed_rows(records)

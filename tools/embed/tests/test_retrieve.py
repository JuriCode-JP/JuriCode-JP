"""Tests for tools/embed/retrieve.py の純関数 (FU-407 + FU-425, 柱1-A/1-B).

torch / sentence_transformers 非依存の純関数のみをテスト (sandbox 実行可)。
実モデル推論を伴う R@3 測定は Windows (柱1-B ablation)。

Coverage:
  - dedup_by_article: 重複除去 / padding / 無効 idx skip (FU-407, 既知事故 f)
  - rrf_combine_per_query: 両側 / 片側 / padding / 負 index skip (B7) / 同率安定ソート (B8)
  - RetrievalPipeline.select_rerank_candidates: hybrid->top_idx_wide (B1) / truncation (B2) /
    hybrid_off->dense (B3) / 矩形不変条件 (B9)
  - dedup モードの枯渇防止 (B4)
  - RetrievalPipeline.aggregate_metrics: R@1/3/10, MRR
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# retrieve.py を import 可能にする (parent dir = tools/embed/)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retrieve import (  # noqa: E402
    RetrievalPipeline,
    dedup_by_article,
    rrf_combine_per_query,
)

# ============================================================
# dedup_by_article (FU-407, 既知事故 f)
# ============================================================


def test_dedup_keeps_top_rank_representative():
    article_ids = ["A", "A", "B", "C", "C", "D"]
    top_idx_wide = np.array([[0, 1, 2, 3, 4, 5]], dtype=np.int64)
    out = dedup_by_article(top_idx_wide, article_ids, k=3)
    assert out.tolist() == [[0, 2, 3]]


def test_dedup_pads_when_fewer_unique_than_k():
    article_ids = ["A", "A", "A"]
    top_idx_wide = np.array([[0, 1, 2]], dtype=np.int64)
    out = dedup_by_article(top_idx_wide, article_ids, k=3)
    assert out.tolist() == [[0, -1, -1]]


def test_dedup_skips_invalid_index():
    article_ids = ["A", "B", "C"]
    top_idx_wide = np.array([[-1, 0, -1, 1]], dtype=np.int64)
    out = dedup_by_article(top_idx_wide, article_ids, k=2)
    assert out.tolist() == [[0, 1]]


# ============================================================
# B4: dedup モードの枯渇防止 (2-1)
# RRF 上位が 1 記事のチャンクで偏っても、ユニーク記事を k 件集める
# ============================================================


def test_b4_dedup_gathers_unique_articles_no_starvation():
    # idx0-4 がすべて記事 A、5=B、6=C。1記事偏りでも k=3 で A/B/C を集める
    article_ids = ["A", "A", "A", "A", "A", "B", "C"]
    top_idx_wide = np.array([[0, 1, 2, 3, 4, 5, 6]], dtype=np.int64)
    out = dedup_by_article(top_idx_wide, article_ids, k=3)
    # A の代表(0) + B(5) + C(6) -> 1 件に潰れない
    assert out.tolist() == [[0, 5, 6]]


# ============================================================
# rrf_combine_per_query (両側 / 片側 / padding / 負 index / 同率)
# ============================================================


def test_rrf_both_hit_shared_doc_ranks_top():
    dense = np.array([[5, 1, 2]], dtype=np.int64)
    bm25 = np.array([[5, 3, 4]], dtype=np.int64)
    out = rrf_combine_per_query(dense, bm25, top_k=5, k_rrf=60)
    assert out[0, 0] == 5


def test_rrf_dense_only_no_zero_division():
    dense = np.array([[10, 11, 12]], dtype=np.int64)
    bm25 = np.array([[20, 21, 22]], dtype=np.int64)
    out = rrf_combine_per_query(dense, bm25, top_k=6, k_rrf=60)
    row = {int(x) for x in out[0] if x >= 0}
    assert {10, 11, 12}.issubset(row)


def test_rrf_bm25_only_symmetry():
    dense = np.array([[1, 2, 3]], dtype=np.int64)
    bm25 = np.array([[100, 101, 102]], dtype=np.int64)
    out = rrf_combine_per_query(dense, bm25, top_k=6, k_rrf=60)
    row = {int(x) for x in out[0] if x >= 0}
    assert {1, 2, 3, 100, 101, 102}.issubset(row)


def test_rrf_pads_when_fewer_than_top_k():
    dense = np.array([[1, 2]], dtype=np.int64)
    bm25 = np.array([[1, 2]], dtype=np.int64)
    out = rrf_combine_per_query(dense, bm25, top_k=5, k_rrf=60)
    row = out[0].tolist()
    assert set(row[:2]) == {1, 2}
    assert row[2:] == [-1, -1, -1]


def test_b7_one_side_all_padding_skips_negative_index():
    # bm25 側が全て -1 (padding = 実質 0 件)。-1 を候補に混入させず dense のみで構成
    dense = np.array([[10, 11, 12]], dtype=np.int64)
    bm25 = np.array([[-1, -1, -1]], dtype=np.int64)
    out = rrf_combine_per_query(dense, bm25, top_k=5, k_rrf=60)
    row = out[0].tolist()
    # 正の候補は 10,11,12 のみ。-1 は trailing pad だけで、候補として混入しない
    assert row[:3] == [10, 11, 12]
    assert row[3:] == [-1, -1]


def test_b8_tie_break_is_index_ascending():
    # doc3 と doc7 が同率 (1/61 + 1/62)。同率は index 昇順 -> 3 が先
    dense = np.array([[7, 3]], dtype=np.int64)
    bm25 = np.array([[3, 7]], dtype=np.int64)
    out = rrf_combine_per_query(dense, bm25, top_k=2, k_rrf=60)
    assert out[0].tolist() == [3, 7]


def test_b9_rrf_output_is_rectangular_with_padding():
    # 2 クエリで有効件数が異なっても (N, top_k) 矩形を維持し -1 でパディング
    dense = np.array([[1, 2, 3], [9, -1, -1]], dtype=np.int64)
    bm25 = np.array([[1, 2, 3], [9, -1, -1]], dtype=np.int64)
    out = rrf_combine_per_query(dense, bm25, top_k=4, k_rrf=60)
    assert out.shape == (2, 4)
    assert out[1].tolist() == [9, -1, -1, -1]  # q1 は 1 件のみ + padding


# ============================================================
# select_rerank_candidates (FU-425 柱1-B)
# ============================================================


def test_b1_select_uses_top_idx_wide_when_hybrid_on():
    pipe = RetrievalPipeline(state={}, records=[])
    dense_top_idx = np.arange(50, dtype=np.int64).reshape(1, 50)
    top_idx_wide = (np.arange(50, dtype=np.int64) + 1000).reshape(1, 50)
    cand = pipe.select_rerank_candidates(
        dense_top_idx, top_idx_wide, hybrid_on=True, n_candidates=30, top_k=10
    )
    # 柱1-B: hybrid on なら hybrid 後集合 (top_idx_wide) を candidate に
    assert cand.shape == (1, 30)
    assert cand[0].tolist() == list(range(1000, 1030))
    # dense は使われない
    assert 0 not in cand[0].tolist()


def test_b3_select_uses_dense_when_hybrid_off():
    pipe = RetrievalPipeline(state={}, records=[])
    dense_top_idx = np.arange(50, dtype=np.int64).reshape(1, 50)
    top_idx_wide = (np.arange(50, dtype=np.int64) + 1000).reshape(1, 50)
    cand = pipe.select_rerank_candidates(
        dense_top_idx, top_idx_wide, hybrid_on=False, n_candidates=30, top_k=10
    )
    # hybrid off は従来どおり dense top-N (柱1-A と不変)
    assert cand.shape == (1, 30)
    assert cand[0].tolist() == list(range(30))


def test_b2_select_truncates_to_max_k():
    pipe = RetrievalPipeline(state={}, records=[])
    dense_top_idx = np.arange(50, dtype=np.int64).reshape(1, 50)
    top_idx_wide = np.arange(50, dtype=np.int64).reshape(1, 50)
    cand = pipe.select_rerank_candidates(
        dense_top_idx, top_idx_wide, hybrid_on=False, n_candidates=5, top_k=20
    )
    assert cand.shape == (1, 20)  # max(n_candidates, top_k) = 20


def test_b2_select_safe_when_available_less_than_k():
    # top_idx_wide の列数 (20) が要求 k (30) 未満でも IndexError なし、列数に従う
    pipe = RetrievalPipeline(state={}, records=[])
    dense_top_idx = np.arange(20, dtype=np.int64).reshape(1, 20)
    top_idx_wide = np.arange(20, dtype=np.int64).reshape(1, 20)
    cand = pipe.select_rerank_candidates(
        dense_top_idx, top_idx_wide, hybrid_on=True, n_candidates=30, top_k=10
    )
    assert cand.shape == (1, 20)


def test_b9_select_rectangular_multi_query():
    pipe = RetrievalPipeline(state={}, records=[])
    dense_top_idx = np.arange(100, dtype=np.int64).reshape(2, 50)
    top_idx_wide = np.arange(100, dtype=np.int64).reshape(2, 50)
    cand = pipe.select_rerank_candidates(
        dense_top_idx, top_idx_wide, hybrid_on=True, n_candidates=30, top_k=10
    )
    assert cand.shape == (2, 30)  # 全クエリ共通の列数 (矩形)


# ============================================================
# aggregate_metrics (純関数)
# ============================================================


def test_aggregate_metrics_recall_and_mrr():
    article_ids = ["A", "B", "C", "D"]
    pipe = RetrievalPipeline(state={}, records=[{"article_id": a} for a in article_ids])
    top_idx = np.array([[0, 1, 2, 3], [0, 1, 2, 3]], dtype=np.int64)
    expected = [{"B"}, {"A"}]
    m = pipe.aggregate_metrics(top_idx, expected)
    assert m["n"] == 2
    assert m["recall_1"] == 1
    assert m["recall_3"] == 2
    assert m["recall_5"] == 2
    assert m["recall_10"] == 2
    assert m["recall_20"] == 2
    assert abs(m["mrr"] - 0.75) < 1e-9  # (1/2 + 1/1) / 2
    assert m["ranks"] == [2, 1]


def test_aggregate_metrics_directive_fallback_rank1():
    # tsutatsu: article_id=None, directive_id が照合キー。rank=1 になること。
    records = [
        {"article_id": None, "directive_id": "hojin-kihon-tsutatsu-9-2-9", "chunk_id": "c-001"},
        {"article_id": "art-001", "directive_id": None, "chunk_id": "c-002"},
    ]
    pipe = RetrievalPipeline(state={}, records=records)
    top_idx = np.array([[0, 1]], dtype=np.int64)
    expected = [{"hojin-kihon-tsutatsu-9-2-9"}]
    m = pipe.aggregate_metrics(top_idx, expected)
    assert m["recall_1"] == 1
    assert m["ranks"] == [1]


def test_aggregate_metrics_taxanswer_chunk_id_fallback():
    # taxanswer: article_id=None, directive_id=None, chunk_id が照合キー。
    records = [
        {"article_id": "art-x", "directive_id": None, "chunk_id": "c-other"},
        {"article_id": None, "directive_id": None, "chunk_id": "hojin-taxanswer-5200"},
    ]
    pipe = RetrievalPipeline(state={}, records=records)
    top_idx = np.array([[0, 1]], dtype=np.int64)
    expected = [{"hojin-taxanswer-5200"}]
    m = pipe.aggregate_metrics(top_idx, expected)
    assert m["recall_1"] == 0
    assert m["recall_3"] == 1
    assert m["ranks"] == [2]


def test_aggregate_metrics_mixed_article_and_directive():
    # article クエリと directive クエリが混在しても両方正しく集計されること。
    records = [
        {"article_id": "art-A", "directive_id": None, "chunk_id": "c-A"},
        {"article_id": None, "directive_id": "hojin-kihon-tsutatsu-9-2-9", "chunk_id": "c-B"},
        {"article_id": "art-C", "directive_id": None, "chunk_id": "c-C"},
    ]
    pipe = RetrievalPipeline(state={}, records=records)
    top_idx = np.array(
        [[0, 1, 2], [1, 0, 2]],
        dtype=np.int64,
    )
    expected = [{"art-A"}, {"hojin-kihon-tsutatsu-9-2-9"}]
    m = pipe.aggregate_metrics(top_idx, expected)
    assert m["recall_1"] == 2  # 両クエリとも rank=1
    assert m["ranks"] == [1, 1]


def test_aggregate_metrics_article_id_none_does_not_match_wrong_directive():
    # article_id=None の行が、異なる directive_id を持つ別クエリの expected に誤ってマッチしない。
    records = [
        {"article_id": None, "directive_id": "hojin-kihon-tsutatsu-9-2-10", "chunk_id": "c-X"},
    ]
    pipe = RetrievalPipeline(state={}, records=records)
    top_idx = np.array([[0]], dtype=np.int64)
    expected = [{"hojin-kihon-tsutatsu-9-2-9"}]  # 違う directive
    m = pipe.aggregate_metrics(top_idx, expected)
    assert m["recall_1"] == 0
    assert m["ranks"] == [None]

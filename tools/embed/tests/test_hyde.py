"""Tests for tools/embed/hyde.py (柱1-D HyDE module).

google-genai / torch 非依存の純関数のみをテスト (sandbox 実行可)。実 LLM 生成・実
embed を伴う ablation は m5。test_retrieve.py と同様 tools/embed/tests は CI pytest
対象外 (ローカル + m5 実行)。

Coverage (Rev.3 査読 Bug5/8/9 直撃):
  - rrf_fuse / min_max_fuse: スケール差があっても両パスが反映される (生スコア加算で
    広レンジパスが他方を抹殺しないこと・Bug5)
  - load/resolve cache: ID キー照合で順序入替でも正しく引く / 欠落で fail-loud (Bug9)
  - build_hyde_cache: 同一 query は1度だけ生成・既存は再生成しない (Bug8)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# hyde.py を import 可能にする (parent dir = tools/embed/)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hyde import (  # noqa: E402
    HydeCacheMiss,
    HydeRecord,
    build_hyde_cache,
    compute_query_hash,
    load_hyde_cache,
    min_max_fuse,
    resolve_hypothetical_docs,
    rrf_fuse,
    save_hyde_cache,
)

# ============================================================
# Late Fusion: スケール差でも両パス反映 (Bug5)
# ============================================================


def test_rrf_fuse_is_scale_independent():
    # path A: 巨大レンジのスコアを持つ (生加算なら A が支配)。
    # path B: 微小レンジだが B の top 候補 (idx=9) は A の候補に含まれない。
    # RRF はランクベースなので B の top も上位に残る。
    top_a = np.array([[0, 1, 2]], dtype=np.int64)
    top_b = np.array([[9, 8, 7]], dtype=np.int64)
    out = rrf_fuse([top_a, top_b], top_k=4)
    # B の top (9) と A の top (0) が共に rank1 で最上位に並ぶ。
    assert 0 in out[0].tolist()
    assert 9 in out[0].tolist()
    # 上位2件は両パスの rank1 (0 と 9)。
    assert set(out[0].tolist()[:2]) == {0, 9}


def test_rrf_fuse_skips_padding_and_is_deterministic():
    top_a = np.array([[0, -1, -1]], dtype=np.int64)
    top_b = np.array([[1, 0, -1]], dtype=np.int64)
    out = rrf_fuse([top_a, top_b], top_k=3)
    # idx 0 は A(rank1)+B(rank2) で最高スコア。-1 は寄与しない。
    assert out[0].tolist()[0] == 0
    assert -1 not in out[0].tolist()[:2]


def test_min_max_fuse_reflects_both_paths_despite_scale():
    # path A: 生スコアが桁違いに大きい (10..30)。candidate 0,1,2。
    # path B: 生スコアが微小 (0.01..0.03)。candidate 3 が B の top。
    # 生スコア加算なら B 候補は完全に埋もれる。Min-Max なら B の top(3) が
    # 正規化後 1.0 となり、A の中位(1: 正規化0.5)を上回って上位に出る。
    top_a = np.array([[0, 1, 2]], dtype=np.int64)
    score_a = np.array([[30.0, 20.0, 10.0]])
    top_b = np.array([[3, 4, 5]], dtype=np.int64)
    score_b = np.array([[0.03, 0.02, 0.01]])
    out = min_max_fuse([top_a, top_b], [score_a, score_b], top_k=6).tolist()[0]
    # A の top(0)=1.0 と B の top(3)=1.0 が同点首位 (idx 昇順 tie-break → 0,3)。
    assert set(out[:2]) == {0, 3}
    # B の top(3) は A の中位(1: 0.5) より上位 = サイレント抹殺されていない。
    assert out.index(3) < out.index(1)


def test_min_max_fuse_handles_degenerate_path():
    # 全候補同値のパス (denom=0) は寄与 0。例外を出さず決定的に返す。
    top_a = np.array([[0, 1]], dtype=np.int64)
    score_a = np.array([[5.0, 5.0]])  # 全同値
    top_b = np.array([[2, 3]], dtype=np.int64)
    score_b = np.array([[1.0, 0.0]])
    out = min_max_fuse([top_a, top_b], [score_a, score_b], top_k=4).tolist()[0]
    # B の top(2)=1.0 が首位。degenerate A は寄与0だが候補としては残る。
    assert out[0] == 2
    assert set(out) >= {0, 1, 2, 3}


# ============================================================
# 仮想文キャッシュ: ID キー照合 / fail-loud (Bug9)
# ============================================================


def test_resolve_uses_id_key_not_index_order():
    q1, q2 = "正当防衛とは", "相続放棄の期限"
    cache = {
        compute_query_hash(q1): HydeRecord(compute_query_hash(q1), q1, "DOC-1"),
        compute_query_hash(q2): HydeRecord(compute_query_hash(q2), q2, "DOC-2"),
    }
    # 生成時と逆順で引いても、各クエリは自分の仮想文を掴む (index 非依存)。
    docs = resolve_hypothetical_docs([q2, q1], cache)
    assert docs == ["DOC-2", "DOC-1"]


def test_resolve_fails_loud_on_missing_key():
    cache = {
        compute_query_hash("ある質問"): HydeRecord(compute_query_hash("ある質問"), "ある質問", "D")
    }
    with pytest.raises(HydeCacheMiss):
        resolve_hypothetical_docs(["別の未生成クエリ"], cache)


def test_build_cache_generates_once_per_unique_query():
    calls: list[str] = []

    def fake_generate(q: str) -> str:
        calls.append(q)
        return f"DOC[{q}]"

    queries = ["A", "B", "A"]  # A は重複
    cache = build_hyde_cache(queries, generate_fn=fake_generate)
    assert calls == ["A", "B"]  # 重複 A は1度だけ生成
    assert len(cache) == 2
    docs = resolve_hypothetical_docs(queries, cache)
    assert docs == ["DOC[A]", "DOC[B]", "DOC[A]"]


def test_build_cache_does_not_regenerate_existing():
    existing = {compute_query_hash("A"): HydeRecord(compute_query_hash("A"), "A", "OLD")}

    def boom(q: str) -> str:  # 既存キーで呼ばれたら失敗
        raise AssertionError(f"should not regenerate {q!r}")

    cache = build_hyde_cache(["A"], generate_fn=boom, existing=existing)
    assert cache[compute_query_hash("A")].hypothetical_doc == "OLD"


def test_cache_roundtrip_jsonl(tmp_path):
    q1, q2 = "質問1", "質問2"
    cache = {
        compute_query_hash(q1): HydeRecord(compute_query_hash(q1), q1, "仮想文1"),
        compute_query_hash(q2): HydeRecord(compute_query_hash(q2), q2, "仮想文2"),
    }
    path = tmp_path / "hyde-cache.jsonl"
    save_hyde_cache(path, cache)
    loaded = load_hyde_cache(path)
    assert loaded == cache


def test_load_missing_cache_returns_empty(tmp_path):
    assert load_hyde_cache(tmp_path / "nope.jsonl") == {}


def test_load_duplicate_key_fails_loud(tmp_path):
    path = tmp_path / "dup.jsonl"
    h = compute_query_hash("q")
    path.write_text(
        f'{{"query_hash": "{h}", "query": "q", "hypothetical_doc": "A"}}\n'
        f'{{"query_hash": "{h}", "query": "q", "hypothetical_doc": "B"}}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate query_hash"):
        load_hyde_cache(path)

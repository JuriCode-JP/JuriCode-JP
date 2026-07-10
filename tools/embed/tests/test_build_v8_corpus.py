"""tests/test_build_v8_corpus.py -- Track A / A1 v8 merge の hermetic 単体テスト.

the locked design rulings (K-1/S-1/C-1/A-1/D-1) の機械実装を合成データで固定する。実 gemini token API は
注入した fake で置換 (sandbox 実行可)。build() は flatten_chunk/build_law_to_phase を stub 化。
"""

from __future__ import annotations

import json
import sys
import types
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_v8_corpus as V  # noqa: E402

# ---- A-1 layer/corpus_group ----


def test_v8_layer_group_a1():
    assert V.v8_layer_group("sochi-hou", "simple", is_kfs=False) == ("statute", "sochi")
    assert V.v8_layer_group("sochi-hou-shikkourei", "simple", is_kfs=False) == (
        "enforcement",
        "sochi",
    )
    assert V.v8_layer_group("sochi-hou-shikoukisoku", "kou", is_kfs=False) == (
        "enforcement",
        "sochi",
    )
    assert V.v8_layer_group("kinsho-hou", "simple", is_kfs=False) == ("statute", "statute")
    assert V.v8_layer_group("houjin-zei-hou-shikkourei", "simple", is_kfs=False) == (
        "enforcement",
        "enforcement",
    )
    assert V.v8_layer_group("hojin-taxanswer", "taxanswer", is_kfs=False) == (
        "taxanswer",
        "taxanswer",
    )
    assert V.v8_layer_group("hojin-kihon-tsutatsu", "tsutatsu", is_kfs=False) == (
        "tsutatsu",
        "tsutatsu",
    )
    assert V.v8_layer_group("kfs-hojin", None, is_kfs=True) == ("ruling", "ruling")


# ---- K-1 KFS mapping ----


def test_kfs_to_v8_maps_and_keeps_meta():
    rec = {
        "case_id": "ntt-1",
        "case_name_ja": "事例名",
        "summary_ja": "要旨",
        "saiketsu_ref": "No.4-14",
        "decision_date": "1972-05-12",
        "issue_code": "0204040000",
    }
    flat = V.kfs_to_v8(rec)
    assert flat["text"] == "事例名\n要旨"
    assert flat["text_raw"] == "事例名\n要旨"
    assert flat["layer"] == "ruling" and flat["corpus_group"] == "ruling"
    assert flat["chunk_id"] == "ntt-1" and flat["chunk_id_orig"] == "ntt-1"
    assert flat["saiketsu_ref"] == "No.4-14" and flat["issue_code"] == "0204040000"
    assert flat["embed_skip"] is False


def test_kfs_to_v8_excludes_empty():
    assert V.kfs_to_v8({"case_id": "x", "case_name_ja": "", "summary_ja": "  "}) is None


# ---- C-1 context_prefix (single layer) ----


def test_context_prefix_kou_gets_paragraph_hashira():
    chunks = [
        {"segment_type": "hashira", "article_id": "a-1", "paragraph_number": 3, "text": "柱書本文"},
        {"segment_type": "kou", "article_id": "a-1", "paragraph_number": 3, "text": "号本文"},
    ]
    hmap = V.build_hashira_map(chunks)
    assert V.context_prefix_for(chunks[1], hmap) == "柱書本文"
    # 非号は空
    assert V.context_prefix_for(chunks[0], hmap) == ""


def test_context_prefix_empty_when_no_hashira():
    chunks = [{"segment_type": "kou", "article_id": "a-2", "paragraph_number": 1, "text": "号"}]
    hmap = V.build_hashira_map(chunks)
    assert V.context_prefix_for(chunks[0], hmap) == ""


# ---- S-1 sub-chunking ----


def test_char_slices_overlap_are_verbatim_substrings():
    text = "".join(str(i % 10) for i in range(1000))
    slices = V.char_slices_with_overlap(text, 4, 0.1)
    assert len(slices) >= 4
    for s in slices:
        assert s in text  # 連続部分文字列 = 文字 rewrite なし
    # 先頭・末尾を被覆
    assert slices[0].startswith(text[0])
    assert text[-1] in slices[-1]


def test_plan_subchunks_single_when_small():
    assert V.plan_subchunks("短い本文", lambda t: 999999) == ["短い本文"]


def test_plan_subchunks_single_when_tokens_under_max():
    text = "x" * (V.CHAR_TOKEN_PREFILTER + 500)
    assert V.plan_subchunks(text, lambda t: 100) == [text]  # token<=MAX -> 分割しない


def test_plan_subchunks_splits_when_tokens_over_max():
    text = "x" * (V.CHAR_TOKEN_PREFILTER + 500)
    slices = V.plan_subchunks(text, lambda t: V.TARGET_TOKENS * 3)  # -> n=3
    assert len(slices) >= 3
    assert all(s in text for s in slices)


# ---- D-1 id uniqueize ----


def test_uniqueize_id():
    seen = Counter()
    assert V.uniqueize_id("a", seen) == "a"
    assert V.uniqueize_id("a", seen) == "a#2"
    assert V.uniqueize_id("a", seen) == "a#3"
    assert V.uniqueize_id("b", seen) == "b"


# ---- build() integration (stubbed reuse) ----


def _stub_bv():
    """flatten_chunk / build_law_to_phase の最小 stub (実 data/v0.2 非依存)."""
    mod = types.SimpleNamespace()

    def flatten_chunk(chunk, phase, augment, cap):
        return {
            "chunk_id": chunk["id"],
            "segment_type": chunk.get("segment_type"),
            "article_id": chunk.get("article_id"),
            "paragraph_number": chunk.get("paragraph_number"),
            "law_name_ja": chunk.get("law_name_ja"),
            "article_number": chunk.get("article_number"),
            "phase_category": phase,
            "text": chunk.get("text") or "",
            "text_raw": chunk.get("text") or "",
        }

    mod.flatten_chunk = flatten_chunk
    mod.build_law_to_phase = lambda data_dir: {}
    return mod


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def test_build_integration(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "_load_bv02", _stub_bv)
    chunks = tmp_path / "build" / "chunks"
    # 通常法令: hashira + kou (collision で同 id 2回) + rollup
    _write(
        chunks / "chihou-zei-hou" / "chihou-zei-hou-article-1.chunks.jsonl",
        [
            {
                "id": "c-art-1-p1-hashira",
                "article_id": "c-art-1",
                "paragraph_number": 1,
                "segment_type": "hashira",
                "text": "項柱書",
            },
            {
                "id": "c-art-1-p1-kou-1",
                "article_id": "c-art-1",
                "paragraph_number": 1,
                "segment_type": "kou",
                "text": "号A",
            },
            {
                "id": "c-art-1-p1-kou-1",
                "article_id": "c-art-1",
                "paragraph_number": 1,
                "segment_type": "kou",
                "text": "号B(衝突)",
            },
            {
                "id": "c-art-1-rollup",
                "article_id": "c-art-1",
                "segment_type": "rollup",
                "text": "z" * 100,
            },
        ],
    )
    # sochi 本法 (A-1: statute + sochi)
    _write(
        chunks / "sochi-hou" / "sochi-hou-article-1.chunks.jsonl",
        [
            {
                "id": "s-art-1-p1",
                "article_id": "s-art-1",
                "paragraph_number": 1,
                "segment_type": "simple",
                "text": "租特法本文",
            }
        ],
    )
    # KFS
    _write(
        chunks / "kfs-hojin" / "kfs-x.saiketsu.jsonl",
        [{"case_id": "ntt-1", "case_name_ja": "名", "summary_ja": "要旨"}],
    )

    out = tmp_path / "corpus-v8.jsonl"
    monkeypatch.setattr(V, "_REPO", tmp_path)
    summary = V.build(chunks, tmp_path / "data", out, token_count_fn=lambda t: 0)

    recs = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    ids = [r["chunk_id"] for r in recs]
    assert len(ids) == len(set(ids))  # D-1: 全ユニーク
    assert "c-art-1-p1-kou-1" in ids and "c-art-1-p1-kou-1#2" in ids  # 衝突 uniqueized
    # layer/corpus_group 欠落0
    assert all("layer" in r and "corpus_group" in r for r in recs)
    # A-1: sochi 本法
    s = next(r for r in recs if r["chunk_id"] == "s-art-1-p1")
    assert s["layer"] == "statute" and s["corpus_group"] == "sochi"
    # C-1: kou に項柱書
    kou = next(r for r in recs if r["chunk_id"] == "c-art-1-p1-kou-1")
    assert kou["context_prefix"] == "項柱書"
    # S-1: rollup embed_skip
    roll = next(r for r in recs if r["chunk_id"] == "c-art-1-rollup")
    assert roll["embed_skip"] is True
    # KFS
    kfs = next(r for r in recs if r["chunk_id"] == "ntt-1")
    assert kfs["text"] == "名\n要旨" and kfs["layer"] == "ruling"
    assert summary["kfs_records"] == 1
    assert summary["id_collisions_uniqueized"] == 1

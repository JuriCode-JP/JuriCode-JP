"""Tests for build_snapshot.py (snapshot.json generator, contract rev.4).

Fully hermetic: every fixture is written under tmp_path, and the ``.npy`` header
is hand-authored so the suite needs no numpy (it therefore RUNS in CI, unlike the
numpy-gated index tests). The tests lock the contract shape (REQUIRED / INDEX
keys / counts), the structural cross-checks, the reverse exclusion gate, and
byte determinism.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_snapshot as B  # noqa: E402

# --------------------------------------------------------------------------- #
# fixture builders
# --------------------------------------------------------------------------- #


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def _make_npy(path: Path, rows: int, cols: int = 2) -> None:
    """Write a valid (all-zeros) v1 .npy so read_npy_shape can parse the header."""
    header = f"{{'descr': '<f4', 'fortran_order': False, 'shape': ({rows}, {cols}), }}"
    total = 6 + 2 + 2 + len(header) + 1  # magic + version + uint16 hlen + header + \n
    header = header + " " * ((64 - total % 64) % 64) + "\n"
    with path.open("wb") as f:
        f.write(b"\x93NUMPY")
        f.write(bytes([1, 0]))
        f.write(struct.pack("<H", len(header)))
        f.write(header.encode("latin1"))
        f.write(b"\x00" * (rows * cols * 4))


#: gap partition of the fixture below: c3=rollup, c4=supplproviso_rollup,
#: c5=empty-text; c1/c2/c6 are embedded.
FIXTURE_EXCLUSIONS = {"rollup": 1, "supplproviso_rollup": 1, "empty_text": 1, "total": 3}


def _make_tree(tmp_path: Path) -> B.SnapshotPaths:
    """A minimal but internally-consistent snapshot source tree."""
    reg = tmp_path / "registry"
    _write_jsonl(reg / "documents.jsonl", [{"juri_id": "a"}, {"juri_id": "b"}])
    _write_jsonl(reg / "texts.jsonl", [{"juri_id": "a"}, {"juri_id": "b"}])  # == documents
    # chunks == full corpus rows (6)
    _write_jsonl(reg / "chunks.jsonl", [{"chunk_id": f"c{i}"} for i in range(1, 7)])

    corpus_full = tmp_path / "corpus-v9.jsonl"
    _write_jsonl(
        corpus_full,
        [
            {"chunk_id": "c1", "segment_type": "paragraph", "text": "x"},
            {"chunk_id": "c2", "segment_type": "paragraph", "text": "y"},
            {"chunk_id": "c3", "segment_type": "rollup", "text": "roll"},
            {"chunk_id": "c4", "segment_type": "supplproviso_rollup", "text": "sr"},
            {"chunk_id": "c5", "segment_type": "paragraph", "text": "   "},  # empty
            {"chunk_id": "c6", "segment_type": "paragraph", "text": "z"},
        ],
    )
    corpus_embed = tmp_path / "corpus-v9-embed.jsonl"  # row-aligned (3 embedded)
    _write_jsonl(
        corpus_embed,
        [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c6"}],
    )

    idx = tmp_path / "embeddings" / "idx-gemini"
    idx.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        Path(str(idx) + ".meta.jsonl"),
        [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c6"}],  # == corpus_embed
    )
    Path(str(idx) + ".vec.json").write_text(
        json.dumps({"provider": "gemini", "model": "gemini-embedding-001"}), encoding="utf-8"
    )
    _make_npy(Path(str(idx) + ".npy"), rows=3)  # == index_rows

    data_dir = tmp_path / "data"
    man = data_dir / "law1"
    man.mkdir(parents=True, exist_ok=True)
    (man / "_source-manifest.json").write_text(
        json.dumps({"parser_version": "pv@1.0", "articles": []}), encoding="utf-8"
    )

    return B.SnapshotPaths(
        index_prefix=idx,
        registry_dir=reg,
        corpus_full=corpus_full,
        corpus_embed=corpus_embed,
        data_dir=data_dir,
    )


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "EXPECTED_EMBED_EXCLUSIONS", FIXTURE_EXCLUSIONS)
    return _make_tree(tmp_path)


# --------------------------------------------------------------------------- #
# pure readers
# --------------------------------------------------------------------------- #


def test_read_npy_shape(tmp_path):
    p = tmp_path / "a.npy"
    _make_npy(p, rows=143749, cols=3072)
    assert B.read_npy_shape(p) == (143749, 3072)


def test_read_npy_shape_rejects_non_npy(tmp_path):
    p = tmp_path / "a.npy"
    p.write_bytes(b"not an npy file")
    with pytest.raises(B.SnapshotError):
        B.read_npy_shape(p)


def test_read_embedding_model_gemini(tmp_path):
    p = tmp_path / "i.vec.json"
    p.write_text(json.dumps({"provider": "gemini", "model": "m1"}), encoding="utf-8")
    assert B.read_embedding_model(p) == "m1"


def test_read_embedding_model_rejects_tfidf(tmp_path):
    p = tmp_path / "i.vec.json"
    p.write_text(json.dumps({"provider": "tfidf", "model": "t"}), encoding="utf-8")
    with pytest.raises(B.SnapshotError):
        B.read_embedding_model(p)


def test_read_embedding_model_missing_file(tmp_path):
    with pytest.raises(B.SnapshotError):
        B.read_embedding_model(tmp_path / "nope.vec.json")


def test_read_pipeline_version_single(tmp_path):
    for name in ("l1", "l2"):
        d = tmp_path / name
        d.mkdir()
        (d / "_source-manifest.json").write_text(
            json.dumps({"parser_version": "pv@1"}), encoding="utf-8"
        )
    assert B.read_pipeline_version(tmp_path) == "pv@1"


def test_read_pipeline_version_multi_valued_raises(tmp_path):
    for name, pv in (("l1", "pv@1"), ("l2", "pv@2")):
        d = tmp_path / name
        d.mkdir()
        (d / "_source-manifest.json").write_text(
            json.dumps({"parser_version": pv}), encoding="utf-8"
        )
    with pytest.raises(B.SnapshotError, match="not single-valued"):
        B.read_pipeline_version(tmp_path)


# --------------------------------------------------------------------------- #
# exclusion gate
# --------------------------------------------------------------------------- #


def test_compute_embed_exclusions_split(tree, monkeypatch):
    got = B.compute_embed_exclusions(tree.corpus_full, tree.corpus_embed)
    assert got == FIXTURE_EXCLUSIONS


def test_compute_embed_exclusions_body_hole_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "EXPECTED_EMBED_EXCLUSIONS", {"total": 0})
    full = tmp_path / "full.jsonl"
    _write_jsonl(
        full,
        [
            {"chunk_id": "c1", "segment_type": "paragraph", "text": "kept"},
            # body chunk missing from the index, non-empty, not a rollup -> STOP
            {"chunk_id": "c2", "segment_type": "paragraph", "text": "dropped body"},
        ],
    )
    embed = tmp_path / "embed.jsonl"
    _write_jsonl(embed, [{"chunk_id": "c1"}])
    with pytest.raises(B.SnapshotError, match="body chunk"):
        B.compute_embed_exclusions(full, embed)


def test_compute_embed_exclusions_drift_stops(tree, monkeypatch):
    monkeypatch.setattr(B, "EXPECTED_EMBED_EXCLUSIONS", {"rollup": 999, "total": 3})
    with pytest.raises(B.SnapshotError, match="drift"):
        B.compute_embed_exclusions(tree.corpus_full, tree.corpus_embed)


# --------------------------------------------------------------------------- #
# manifest assembly
# --------------------------------------------------------------------------- #


def test_build_snapshot_contract_shape(tree):
    snap = B.build_snapshot(tree, "2026-07", "2026-07-16")
    # REQUIRED keys present
    for k in ("snapshot_id", "pipeline_version", "index", "counts", "files"):
        assert k in snap
    # index is EXACTLY {index_name, embedding_model}
    assert set(snap["index"]) == {"index_name", "embedding_model"}
    assert snap["index"] == {"index_name": "idx-gemini", "embedding_model": "gemini-embedding-001"}
    assert snap["snapshot_id"] == "2026-07"
    assert snap["created_at"] == "2026-07-16"
    assert snap["pipeline_version"] == "pv@1.0"
    assert snap["counts"] == {"documents": 2, "chunks": 6, "texts": 2, "index_rows": 3}
    assert snap["embed_exclusions"] == FIXTURE_EXCLUSIONS


def test_build_snapshot_files_are_7_and_hashed(tree):
    snap = B.build_snapshot(tree, "2026-07", "2026-07-16")
    assert set(snap["files"]) == {
        "registry/documents.jsonl",
        "registry/chunks.jsonl",
        "registry/texts.jsonl",
        "corpus/row-aligned-corpus.jsonl",
        "index/idx-gemini.meta.jsonl",
        "index/idx-gemini.vec.json",
        "index/idx-gemini.npy",
    }
    # no pickle in the distribution
    assert not any(d.endswith(".vec.pkl") for d in snap["files"])
    # each value is a real sha256 of the source file
    for src, dest in B.file_plan(tree):
        assert snap["files"][dest] == B.sha256_of(src)


def test_build_snapshot_deterministic(tree):
    a = B.to_bytes(B.build_snapshot(tree, "2026-07", "2026-07-16"))
    b = B.to_bytes(B.build_snapshot(tree, "2026-07", "2026-07-16"))
    assert a == b


def test_build_snapshot_bad_created_at(tree):
    with pytest.raises(B.SnapshotError, match="created_at"):
        B.build_snapshot(tree, "2026-07", "July 16")


def test_build_snapshot_npy_meta_mismatch_stops(tree):
    # Rewrite the .npy with a different row count than meta.jsonl (3).
    _make_npy(Path(str(tree.index_prefix) + ".npy"), rows=99)
    with pytest.raises(B.SnapshotError, match="index row disagreement"):
        B.build_snapshot(tree, "2026-07", "2026-07-16")


def test_build_snapshot_missing_file_stops(tree):
    Path(str(tree.index_prefix) + ".npy").unlink()
    with pytest.raises(B.SnapshotError, match="missing shipped file"):
        B.build_snapshot(tree, "2026-07", "2026-07-16")

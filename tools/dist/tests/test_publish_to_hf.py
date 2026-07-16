"""Tests for publish_to_hf.py (flat self-contained snapshot distribution).

Hermetic: only the pure logic is exercised (integrity gate, repo layout, README).
The huggingface_hub upload/download is imported inside ``main`` and never touched
here, so importing the module needs no network and no hf dependency.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_snapshot as B  # noqa: E402
import publish_to_hf as P  # noqa: E402


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _tree(tmp_path: Path):
    """Minimal shippable tree + a matching snapshot dict."""
    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "documents.jsonl").write_text("a\n", encoding="utf-8")
    (reg / "chunks.jsonl").write_text("c\n", encoding="utf-8")
    (reg / "texts.jsonl").write_text("t\n", encoding="utf-8")
    corpus_embed = tmp_path / "corpus-v9-embed.jsonl"
    corpus_embed.write_text("e\n", encoding="utf-8")
    idx = tmp_path / "emb" / "idx-gemini"
    idx.parent.mkdir()
    Path(str(idx) + ".meta.jsonl").write_text("m\n", encoding="utf-8")
    Path(str(idx) + ".vec.json").write_text(
        '{"provider":"gemini","model":"gemini-embedding-001"}', encoding="utf-8"
    )
    Path(str(idx) + ".npy").write_bytes(b"\x93NUMPY\x01\x00fake")

    plan = B.file_plan_parts(idx, reg, corpus_embed)
    files = {dest: _sha(src) for src, dest in plan}
    snapshot = {
        "snapshot_id": "2026-07",
        "created_at": "2026-07-16",
        "pipeline_version": "pv@0.2.0",
        "index": {"index_name": "idx-gemini", "embedding_model": "gemini-embedding-001"},
        "counts": {"documents": 1, "chunks": 1, "texts": 1, "index_rows": 1},
        "files": files,
        "embed_exclusions": {"rollup": 1, "supplproviso_rollup": 1, "empty_text": 1, "total": 3},
    }
    return snapshot, plan, idx, reg, corpus_embed


# --------------------------------------------------------------------------- #
# integrity gate
# --------------------------------------------------------------------------- #


def test_verify_local_ok(tmp_path):
    snap, plan, *_ = _tree(tmp_path)
    local = P.verify_local_against_snapshot(snap, plan)
    assert set(local) == set(snap["files"])
    assert local == snap["files"]


def test_verify_local_detects_tampered_file(tmp_path):
    snap, plan, _idx, reg, _ce = _tree(tmp_path)
    (reg / "texts.jsonl").write_text("TAMPERED\n", encoding="utf-8")
    with pytest.raises(ValueError, match="local sha256"):
        P.verify_local_against_snapshot(snap, plan)


def test_verify_local_detects_missing_file(tmp_path):
    snap, plan, idx, _reg, _ce = _tree(tmp_path)
    Path(str(idx) + ".npy").unlink()
    with pytest.raises(FileNotFoundError):
        P.verify_local_against_snapshot(snap, plan)


def test_verify_local_detects_file_set_mismatch(tmp_path):
    snap, plan, *_ = _tree(tmp_path)
    snap["files"].pop("registry/texts.jsonl")  # snapshot claims fewer files
    with pytest.raises(ValueError, match="file set disagrees"):
        P.verify_local_against_snapshot(snap, plan)


# --------------------------------------------------------------------------- #
# repo layout
# --------------------------------------------------------------------------- #


def test_distribution_layout_is_flat_and_self_contained(tmp_path):
    snap, plan, *_ = _tree(tmp_path)
    snapshot_json = tmp_path / "snapshot.json"
    snapshot_json.write_text("{}", encoding="utf-8")
    layout = P.distribution_layout("2026-07", plan, snapshot_json)

    # snapshot.json is first, and every repo path lives under <snapshot_id>/
    assert layout[0][1] == "2026-07/snapshot.json"
    assert all(repo.startswith("2026-07/") for _src, repo in layout)
    repo_paths = {repo for _src, repo in layout}
    assert "2026-07/registry/texts.jsonl" in repo_paths
    assert "2026-07/corpus/row-aligned-corpus.jsonl" in repo_paths
    assert "2026-07/index/idx-gemini.vec.json" in repo_paths
    # no pickle, no abolished manifest
    assert not any(".vec.pkl" in repo for _src, repo in layout)
    assert not any("_manifest.json" in repo for _src, repo in layout)
    # snapshot.json + 7 shipped files
    assert len(layout) == 8


# --------------------------------------------------------------------------- #
# README
# --------------------------------------------------------------------------- #


def test_build_readme_reflects_rev4(tmp_path):
    snap, *_ = _tree(tmp_path)
    readme = P.build_readme(snap)
    for must in (
        "snapshot.json",
        "registry/texts.jsonl",
        "corpus/row-aligned-corpus.jsonl",
        "idx-gemini.vec.json",
        "No pickle",
        "gemini-embedding-001",
        "pv@0.2.0",
    ):
        assert must in readme, must
    # the abolished manifest must not be advertised
    assert "_manifest.json" not in readme

"""Tests for publish_to_github_release.py (GitHub Release audit anchor).

Hermetic: only the pure logic is exercised (the subset integrity gate, the registry
subset derivation, and the deterministic notes builder). ``gh`` is invoked only inside
``main``/``_gh_ready`` via subprocess and is never touched here, so importing the module
needs no network and no gh binary.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_snapshot as B  # noqa: E402
import publish_to_github_release as G  # noqa: E402


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _tree(tmp_path: Path):
    """Minimal shippable tree + a matching snapshot dict (all 7 files hashed)."""
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
    return snapshot, idx, reg, corpus_embed


# --------------------------------------------------------------------------- #
# registry subset derivation
# --------------------------------------------------------------------------- #


def test_registry_subset_is_the_three_registry_files(tmp_path):
    _snap, idx, reg, ce = _tree(tmp_path)
    subset = G.registry_subset(idx, reg, ce)
    dests = {dest for _src, dest in subset}
    assert dests == {
        "registry/documents.jsonl",
        "registry/chunks.jsonl",
        "registry/texts.jsonl",
    }
    # the subset is a strict subset of the full 7-file plan (index/corpus excluded)
    full = {dest for _src, dest in B.file_plan_parts(idx, reg, ce)}
    assert dests < full
    assert "corpus/row-aligned-corpus.jsonl" not in dests
    assert not any(dest.startswith("index/") for dest in dests)


# --------------------------------------------------------------------------- #
# subset integrity gate
# --------------------------------------------------------------------------- #


def test_verify_registry_subset_ok(tmp_path):
    snap, idx, reg, ce = _tree(tmp_path)
    subset = G.registry_subset(idx, reg, ce)
    local = G.verify_registry_subset(snap, subset)
    assert set(local) == {dest for _src, dest in subset}


def test_verify_registry_subset_rejects_tampered_file(tmp_path):
    snap, idx, reg, ce = _tree(tmp_path)
    subset = G.registry_subset(idx, reg, ce)
    (reg / "texts.jsonl").write_text("TAMPERED\n", encoding="utf-8")
    with pytest.raises(ValueError, match="local sha256"):
        G.verify_registry_subset(snap, subset)


def test_verify_registry_subset_rejects_short_file(tmp_path):
    snap, idx, reg, ce = _tree(tmp_path)
    subset = G.registry_subset(idx, reg, ce)
    (reg / "documents.jsonl").write_text("", encoding="utf-8")  # truncated
    with pytest.raises(ValueError, match="local sha256"):
        G.verify_registry_subset(snap, subset)


def test_verify_registry_subset_rejects_missing_file(tmp_path):
    snap, idx, reg, ce = _tree(tmp_path)
    subset = G.registry_subset(idx, reg, ce)
    (reg / "chunks.jsonl").unlink()
    with pytest.raises(FileNotFoundError):
        G.verify_registry_subset(snap, subset)


def test_verify_registry_subset_rejects_dest_absent_from_snapshot(tmp_path):
    snap, idx, reg, ce = _tree(tmp_path)
    subset = G.registry_subset(idx, reg, ce)
    snap["files"].pop("registry/texts.jsonl")
    with pytest.raises(ValueError, match="not a key in snapshot.json"):
        G.verify_registry_subset(snap, subset)


# --------------------------------------------------------------------------- #
# notes builder (pure, deterministic)
# --------------------------------------------------------------------------- #


def test_build_notes_is_deterministic(tmp_path):
    snap, *_ = _tree(tmp_path)
    # Compare the in-memory strings/bytes of two calls -- never round-trip through a
    # text-mode file, which would reintroduce the CRLF/LF newline asymmetry on Windows.
    a = G.build_notes(snap)
    b = G.build_notes(snap)
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


def test_build_notes_reflects_snapshot(tmp_path):
    snap, *_ = _tree(tmp_path)
    notes = G.build_notes(snap)
    # every distributed file's sha256 (all 7) is present, plus provenance
    for dest, digest in snap["files"].items():
        assert dest in notes, dest
        assert digest in notes, digest
    for must in (
        "snapshot.json",
        "pv@0.2.0",
        "gemini-embedding-001",
        "hash_basis",
        "pipeline_version",
        str(G.HF_DATASET_URL),
    ):
        assert must in notes, must
    # a public surface: no internal names, no abolished manifest advertised
    assert "_manifest.json" not in notes


def test_build_notes_ends_with_newline(tmp_path):
    # safe_write_text asserts a trailing newline; the builder must satisfy it.
    snap, *_ = _tree(tmp_path)
    assert G.build_notes(snap).endswith("\n")

"""Import-level smoke for the retrieval service surface (numpy-free).

Importing juricode_retrieval must not require numpy (the primitives and the service load it
lazily inside methods), and the moved service symbols must be exported from the package root.
"""

from __future__ import annotations

import juricode_retrieval as jr


def test_service_surface_is_exported():
    for name in (
        "RetrievalService",
        "EXPECTED_DIM",
        "build_dedup_keys",
        "filter_row_by_layers",
        "fold_taxanswer_chunk_id",
        "_load_corpus",
    ):
        assert hasattr(jr, name), f"{name} missing from juricode_retrieval"
        assert name in jr.__all__, f"{name} missing from __all__"
    assert jr.EXPECTED_DIM == 3072


def test_pure_helpers_run_without_numpy():
    # These three helpers are numpy-free; exercise them so the package surface is not merely
    # importable but callable in a numpy-absent environment.
    assert jr.fold_taxanswer_chunk_id("x-taxanswer-2011-sub2", "taxanswer") == "x-taxanswer-2011"
    assert jr.fold_taxanswer_chunk_id("law-a-art-1-p2", "statute") == "law-a-art-1-p2"
    base = ["a1", "c2"]
    assert jr.build_dedup_keys(base, ["c1", "c2"], ["statute", "statute"], fold=False) == base
    assert jr.filter_row_by_layers(
        [0, 1, 2], ["statute", "taxanswer", "tsutatsu"], ["taxanswer"]
    ) == [1]

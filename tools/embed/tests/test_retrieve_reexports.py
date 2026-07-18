"""The four dense primitives are re-imported from juricode-retrieval, so every
retrieve.py caller runs the identical function objects. This is the merge
condition's byte-invariance proof, stronger than an output-hash comparison: it
holds before any run, independent of the embedding API. numpy is not needed --
identity is a property of the bound objects, checked without calling them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import juricode_retrieval as JR  # noqa: E402
import retrieve as R  # noqa: E402


def test_dense_primitives_are_the_same_objects():
    assert R._load_artefacts is JR._load_artefacts
    assert R._encode_queries is JR._encode_queries
    assert R.dedup_by_article is JR.dedup_by_article
    assert R._cosine_topk is JR._cosine_topk

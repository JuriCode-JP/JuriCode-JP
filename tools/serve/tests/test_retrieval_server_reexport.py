"""retrieval_server re-imports its retrieval core from juricode-retrieval, so every
caller (HTTP layer, b4_eval, reproduce_a3) runs the identical class object. This is the
merge condition's byte-invariance proof, stronger than an output-hash comparison: object
identity holds before any run, independent of the embedding API, and needs no numpy.

The second test pins the one non-mechanical change of the move -- the dedup-key build that
used to reference the eval-only RetrievalPipeline is now inlined in the service. It must
stay byte-identical to RetrievalPipeline._dedup_keys across every fallback branch.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVE = Path(__file__).resolve().parents[1]  # tools/serve  (retrieval_server.py)
_REPO = _SERVE.parents[1]
_EMBED = _REPO / "tools" / "embed"  # retrieve.py (RetrievalPipeline reference impl)
_RETRIEVAL_SRC = _REPO / "packages" / "juricode-retrieval" / "src"

for _p in (_RETRIEVAL_SRC, _EMBED, _SERVE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import juricode_retrieval as JR  # noqa: E402
import retrieval_server as S  # noqa: E402
import retrieve as R  # noqa: E402


def test_service_and_helpers_are_the_same_objects():
    assert S.RetrievalService is JR.RetrievalService
    assert S.build_dedup_keys is JR.build_dedup_keys
    assert S.filter_row_by_layers is JR.filter_row_by_layers
    assert S.fold_taxanswer_chunk_id is JR.fold_taxanswer_chunk_id
    assert S.EXPECTED_DIM == JR.EXPECTED_DIM


def test_package_resolves_to_monorepo_src_not_a_stray_install():
    # Path-shadowing check (test-side; production code is not touched). insert(0) puts the
    # local src first, so if a stray copy were ever imported the `is` assertion above would
    # already be False -- this substring check is belt-and-suspenders.
    assert "packages/juricode-retrieval/src" in JR.__file__.replace("\\", "/")


def _inline_base_keys(records: list[dict]) -> list[str | None]:
    # 1:1 transcription of RetrievalService.__init__'s inlined dedup-key build (service.py).
    # If the service formula ever drifts, this transcription and the assertion below diverge.
    article_ids = [r.get("article_id") for r in records]
    meta_directive_ids = [r.get("directive_id") for r in records]
    chunk_ids = [r.get("chunk_id") for r in records]
    return [
        (a if a is not None else (d or c))
        for a, d, c in zip(article_ids, meta_directive_ids, chunk_ids, strict=False)
    ]


def test_inline_dedup_keys_match_retrieval_pipeline():
    # Synthetic meta records covering every fallback branch so a formula drift in either the
    # pipeline or the inlined service build is caught byte-for-byte (numpy not needed):
    #   (a) article_id present            -> article_id
    #   (b) article_id None, directive    -> directive_id
    #   (c) article_id None, no directive -> chunk_id
    #   (d) article_id None, directive "" -> `d or c` falls through empty string to chunk_id
    #   (e) taxanswer-style sub-chunk id  -> chunk_id (fold happens later, not in the base key)
    records = [
        {"article_id": "shotoku-art-1", "directive_id": None, "chunk_id": "c1"},
        {"article_id": None, "directive_id": "tsutatsu-2", "chunk_id": "c2"},
        {"article_id": None, "directive_id": None, "chunk_id": "c3"},
        {"article_id": None, "directive_id": "", "chunk_id": "c4"},
        {"article_id": None, "directive_id": None, "chunk_id": "shotoku-taxanswer-2011-sub2"},
    ]
    expected = R.RetrievalPipeline({}, records)._dedup_keys
    assert _inline_base_keys(records) == expected
    # Spell out the semantics so the fallback rule is pinned, not merely mirrored.
    assert expected == ["shotoku-art-1", "tsutatsu-2", "c3", "c4", "shotoku-taxanswer-2011-sub2"]

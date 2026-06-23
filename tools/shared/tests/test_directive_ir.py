"""test_directive_ir.py -- DirectiveChunk Pydantic モデルの単体 + 敵対テスト (FU-514 D-2).

出力保持リファクタの型ガード。disjoint Union (linked / unlinked) が
構造的に排他であること、dump で null 混入が起きないこと、将来 unlinked が
流入しても smart-parse が誤爆しないこと (Bug30) を pin する。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from juricode_shared.ir import (
    DirectiveChunk,
    DirectiveLinkedArticleRef,
    DirectiveUnlinkedArticleRef,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL = {
    "directive_id": "hojin-kihon-tsutatsu-9-2-9",
    "directive_number": "9-2-9",
    "law_abbrev": "hojin-kihon-tsutatsu",
    "text": "法第34条...に規定する経済的な利益とは...",
    "source_url": "https://www.nta.go.jp/law/tsutatsu/kihon/hojin/09/09_02_02.htm",
}

_LINKED = {
    "raw": "法第34条第4項",
    "law_abbrev": "houjin-zei-hou",
    "article_number": "34",
    "article_id": "houjin-zei-hou-art-34",
}

_UNLINKED = {
    "raw": "措法第42条",
    "law_abbrev": "sochi-hou",
    "article_number": "42",
    "unlinked_reason": "corpus_unregistered",
}


# ---------------------------------------------------------------------------
# DirectiveChunk: basic construction
# ---------------------------------------------------------------------------


def test_directive_chunk_minimal() -> None:
    chunk = DirectiveChunk(**_MINIMAL)
    assert chunk.directive_id == "hojin-kihon-tsutatsu-9-2-9"
    assert chunk.directive_number == "9-2-9"
    assert chunk.title == ""  # default
    assert chunk.amendment_note == ""  # default
    assert chunk.license == "public-domain-13-2"  # default
    assert chunk.related_articles == []


def test_directive_chunk_text_required() -> None:
    payload = {k: v for k, v in _MINIMAL.items() if k != "text"}
    with pytest.raises(ValidationError):
        DirectiveChunk(**payload)


def test_directive_chunk_extra_field_raises() -> None:
    with pytest.raises(ValidationError):
        DirectiveChunk(**_MINIMAL, unknown_field="x")


def test_directive_chunk_wrong_type_raises() -> None:
    with pytest.raises(ValidationError):
        DirectiveChunk(**{**_MINIMAL, "directive_number": 929})  # int, not str


def test_directive_chunk_is_frozen() -> None:
    chunk = DirectiveChunk(**_MINIMAL)
    with pytest.raises(ValidationError):
        chunk.title = "mutated"  # frozen=True


# ---------------------------------------------------------------------------
# Sub-models: linked / unlinked refs
# ---------------------------------------------------------------------------


def test_linked_ref_valid() -> None:
    ref = DirectiveLinkedArticleRef(**_LINKED)
    assert ref.article_id == "houjin-zei-hou-art-34"


def test_linked_ref_rejects_unlinked_reason() -> None:
    """linked サブモデルは unlinked_reason を extra として弾く (判別子)."""
    with pytest.raises(ValidationError):
        DirectiveLinkedArticleRef(**{**_LINKED, "unlinked_reason": "x"})


def test_unlinked_ref_valid() -> None:
    ref = DirectiveUnlinkedArticleRef(**_UNLINKED)
    assert ref.unlinked_reason == "corpus_unregistered"


def test_unlinked_ref_rejects_article_id() -> None:
    """unlinked サブモデルは article_id を extra として弾く (判別子)."""
    with pytest.raises(ValidationError):
        DirectiveUnlinkedArticleRef(**{**_UNLINKED, "article_id": "x"})


# ---------------------------------------------------------------------------
# Adversarial: disjoint Union discrimination (Bug30 ガード)
# ---------------------------------------------------------------------------


def test_linked_dict_resolves_to_linked_in_union() -> None:
    chunk = DirectiveChunk(**_MINIMAL, related_articles=[_LINKED])
    assert len(chunk.related_articles) == 1
    assert isinstance(chunk.related_articles[0], DirectiveLinkedArticleRef)


def test_unlinked_dict_resolves_to_unlinked_in_union() -> None:
    """現データ unlinked 0 件の生存バイアスに対するガード: unlinked dict は
    Linked に適合せず必ず Unlinked に振り分けられる."""
    chunk = DirectiveChunk(**_MINIMAL, related_articles=[_UNLINKED])
    assert len(chunk.related_articles) == 1
    assert isinstance(chunk.related_articles[0], DirectiveUnlinkedArticleRef)


def test_mixed_refs_resolve_independently() -> None:
    chunk = DirectiveChunk(**_MINIMAL, related_articles=[_LINKED, _UNLINKED])
    assert isinstance(chunk.related_articles[0], DirectiveLinkedArticleRef)
    assert isinstance(chunk.related_articles[1], DirectiveUnlinkedArticleRef)


def test_ref_with_both_discriminators_raises() -> None:
    """article_id と unlinked_reason の両方を持つ ref はどちらの形にも適合せず弾く."""
    bad = {**_LINKED, "unlinked_reason": "corpus_unregistered"}
    with pytest.raises(ValidationError):
        DirectiveChunk(**_MINIMAL, related_articles=[bad])


def test_ref_with_neither_discriminator_raises() -> None:
    """article_id も unlinked_reason も無い ref はどちらの形にも適合せず弾く."""
    bad = {"raw": "x", "law_abbrev": "y", "article_number": "1"}
    with pytest.raises(ValidationError):
        DirectiveChunk(**_MINIMAL, related_articles=[bad])


# ---------------------------------------------------------------------------
# Dump fidelity: null 混入ゼロ (出力保持の核)
# ---------------------------------------------------------------------------


def test_linked_ref_dump_has_no_null_injection() -> None:
    """linked ref の dump は自分の 4 キーのみ (unlinked_reason:null が混入しない)."""
    chunk = DirectiveChunk(**_MINIMAL, related_articles=[_LINKED])
    dumped = chunk.model_dump(mode="json")["related_articles"][0]
    assert dumped == _LINKED  # キー集合・値とも完全一致


def test_unlinked_ref_dump_has_no_null_injection() -> None:
    """unlinked ref の dump は自分の 4 キーのみ (article_id:null が混入しない)."""
    chunk = DirectiveChunk(**_MINIMAL, related_articles=[_UNLINKED])
    dumped = chunk.model_dump(mode="json")["related_articles"][0]
    assert dumped == _UNLINKED


# ---------------------------------------------------------------------------
# model_dump: 意味フィールドのみ (配管はモデル外)
# ---------------------------------------------------------------------------


def test_model_dump_excludes_pipeline_fields() -> None:
    chunk = DirectiveChunk(**_MINIMAL)
    d = chunk.model_dump(mode="json")
    expected = {
        "directive_id",
        "directive_number",
        "law_abbrev",
        "title",
        "text",
        "amendment_note",
        "related_articles",
        "source_url",
        "license",
    }
    assert set(d.keys()) == expected
    pipeline = {"id", "law_name_ja", "law_name_ja_display", "segment_type", "article_id"}
    assert pipeline.isdisjoint(set(d.keys())), (
        f"配管フィールドがモデルに混入: {pipeline & set(d.keys())}"
    )

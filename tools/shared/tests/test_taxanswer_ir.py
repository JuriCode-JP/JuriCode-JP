"""test_taxanswer_ir.py -- TaxAnswerChunk Pydantic モデルの単体テスト (Step 1).

R39: 一機能一コミット / 各 commit で退行確認.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from juricode_shared.ir import (
    TaxAnswerArticleRef,
    TaxAnswerChunk,
    TaxAnswerDirectiveRef,
    TaxAnswerUnlinkedRef,
)


# ---------------------------------------------------------------------------
# Helper: minimal valid TaxAnswerChunk kwargs
# ---------------------------------------------------------------------------

_MINIMAL = {
    "id": "hojin-taxanswer-5200",
    "code": "5200",
    "title": "役員の範囲",
    "body": "役員とは次の者をいいます。",
    "source_url": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5200.htm",
}


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------


def test_taxanswer_chunk_minimal() -> None:
    chunk = TaxAnswerChunk(**_MINIMAL)
    assert chunk.id == "hojin-taxanswer-5200"
    assert chunk.code == "5200"
    assert chunk.license == "cc-by-jp-nta"
    assert chunk.attribution == "国税庁タックスアンサー"
    assert chunk.source_format == "nta-html"


def test_taxanswer_chunk_version_date_present() -> None:
    chunk = TaxAnswerChunk(**_MINIMAL, version_date="2025-04-01")
    assert chunk.version_date == "2025-04-01"


def test_taxanswer_chunk_version_date_none() -> None:
    """version_date が None でも ValidationError にならない (R23・パース不能は None 許容)."""
    chunk = TaxAnswerChunk(**_MINIMAL, version_date=None)
    assert chunk.version_date is None


def test_taxanswer_chunk_license_required() -> None:
    """license フィールドはデフォルト 'cc-by-jp-nta' が必ず設定される."""
    chunk = TaxAnswerChunk(**_MINIMAL)
    assert chunk.license == "cc-by-jp-nta"


def test_taxanswer_chunk_wrong_type_raises() -> None:
    """code に int を渡すと ValidationError (extra=forbid 確認)."""
    with pytest.raises(ValidationError):
        TaxAnswerChunk(**{**_MINIMAL, "code": 5200})  # int, not str


def test_taxanswer_chunk_extra_field_raises() -> None:
    """extra='forbid' で未定義フィールドを渡すと ValidationError."""
    with pytest.raises(ValidationError):
        TaxAnswerChunk(**_MINIMAL, unknown_field="x")


# ---------------------------------------------------------------------------
# Sub-models: TaxAnswerArticleRef
# ---------------------------------------------------------------------------


def test_article_ref_valid() -> None:
    ref = TaxAnswerArticleRef(
        raw="法法2",
        law_abbrev="houjin-zei-hou",
        article_number="2",
        article_id="houjin-zei-hou-art-2",
    )
    assert ref.article_id == "houjin-zei-hou-art-2"


def test_article_ref_extra_field_raises() -> None:
    with pytest.raises(ValidationError):
        TaxAnswerArticleRef(
            raw="法法2",
            law_abbrev="houjin-zei-hou",
            article_number="2",
            article_id="houjin-zei-hou-art-2",
            extra_key="x",
        )


# ---------------------------------------------------------------------------
# Sub-models: TaxAnswerDirectiveRef
# ---------------------------------------------------------------------------


def test_directive_ref_valid() -> None:
    ref = TaxAnswerDirectiveRef(
        raw="法基通9-2-9",
        directive_number="9-2-9",
        law_abbrev="hojin-kihon-tsutatsu",
        directive_id="hojin-kihon-tsutatsu-9-2-9",
    )
    assert ref.directive_id == "hojin-kihon-tsutatsu-9-2-9"


# ---------------------------------------------------------------------------
# Sub-models: TaxAnswerUnlinkedRef
# ---------------------------------------------------------------------------


def test_unlinked_ref_valid() -> None:
    ref = TaxAnswerUnlinkedRef(raw="法基通9-2-1", reason="tsutatsu_not_in_corpus")
    assert ref.reason == "tsutatsu_not_in_corpus"


# ---------------------------------------------------------------------------
# Full chunk with related lists
# ---------------------------------------------------------------------------


def test_taxanswer_chunk_with_related() -> None:
    chunk = TaxAnswerChunk(
        **_MINIMAL,
        version_date="2025-04-01",
        related_articles=[
            TaxAnswerArticleRef(
                raw="法法2",
                law_abbrev="houjin-zei-hou",
                article_number="2",
                article_id="houjin-zei-hou-art-2",
            )
        ],
        related_directives=[
            TaxAnswerDirectiveRef(
                raw="法基通9-2-9",
                directive_number="9-2-9",
                law_abbrev="hojin-kihon-tsutatsu",
                directive_id="hojin-kihon-tsutatsu-9-2-9",
            )
        ],
        unlinked_refs=[TaxAnswerUnlinkedRef(raw="法基通9-2-1", reason="tsutatsu_not_in_corpus")],
        related_qa=["5210", "5211"],
        kikon_raw="法法2、法基通9-2-1",
    )
    assert len(chunk.related_articles) == 1
    assert len(chunk.related_directives) == 1
    assert len(chunk.unlinked_refs) == 1
    assert chunk.related_qa == ["5210", "5211"]


# ---------------------------------------------------------------------------
# model_dump produces expected keys (19 意味フィールドのサブセット確認)
# ---------------------------------------------------------------------------


def test_model_dump_keys() -> None:
    """model_dump が意味フィールドのキーを正しく返すこと."""
    chunk = TaxAnswerChunk(**_MINIMAL)
    d = chunk.model_dump(mode="json")
    expected_keys = {
        "id",
        "code",
        "title",
        "body",
        "version_date",
        "related_articles",
        "related_directives",
        "unlinked_refs",
        "related_qa",
        "kikon_raw",
        "source_url",
        "source_format",
        "license",
        "attribution",
    }
    assert expected_keys.issubset(set(d.keys())), f"Missing keys: {expected_keys - set(d.keys())}"
    # 配管フィールドはモデルに含まれない
    pipeline_fields = {"segment_type", "article_id", "law_name_ja", "law_name_ja_display", "text"}
    assert pipeline_fields.isdisjoint(set(d.keys())), (
        f"Pipeline fields must not be in model_dump: {pipeline_fields & set(d.keys())}"
    )

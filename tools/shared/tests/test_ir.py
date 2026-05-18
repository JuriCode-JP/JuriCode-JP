"""IR Pydantic モデルのテスト."""

from datetime import date

import pytest
from pydantic import ValidationError

from juricode_shared.ir import (
    CaseReference,
    EnglishParagraph,
    EnglishTranslation,
    Item,
    JuriCodeArticle,
    Paragraph,
    ParentSection,
    Relevance,
    TranslationStatus,
)


# ---- 基本モデル ----


def test_paragraph_basic() -> None:
    p = Paragraph(number=1, text="本文")
    assert p.number == 1
    assert p.text == "本文"
    assert p.has_proviso is False
    assert p.items == []


def test_paragraph_with_items() -> None:
    p = Paragraph(
        number=1,
        text="次に掲げる行為は",
        items=[Item(number=1, text="一の行為"), Item(number=2, text="二の行為")],
    )
    assert len(p.items) == 2


def test_paragraph_rejects_zero_number() -> None:
    with pytest.raises(ValidationError):
        Paragraph(number=0, text="本文")


def test_translation_status_enum() -> None:
    assert TranslationStatus.OFFICIAL == "official"
    assert TranslationStatus.DRAFT == "draft"


def test_relevance_enum() -> None:
    assert Relevance.HIGH == "high"


# ---- CaseReference ----


def test_case_reference_basic() -> None:
    ref = CaseReference(
        case_id="scj-pb1-1969-12-04-keishu-23-12-1573",
        court="最高裁判所第一小法廷",
        court_en="Supreme Court of Japan, First Petty Bench",
        decision_date=date(1969, 12, 4),
        citation="刑集23巻12号1573頁",
        url="https://www.courts.go.jp/app/hanrei_jp/detail2?id=...",
        relevance=Relevance.HIGH,
    )
    assert ref.case_id == "scj-pb1-1969-12-04-keishu-23-12-1573"
    assert ref.relevance == Relevance.HIGH


def test_case_reference_invalid_id_pattern() -> None:
    with pytest.raises(ValidationError):
        CaseReference(
            case_id="INVALID_ID",
            court="最高裁",
            court_en="Supreme Court",
            decision_date=date(1969, 12, 4),
            citation="刑集23巻12号1573頁",
            url="https://example.com",
            relevance=Relevance.HIGH,
        )


# ---- JuriCodeArticle (最上位) ----


def _build_minimal_article(**overrides) -> JuriCodeArticle:
    """最小限の有効な JuriCodeArticle を構築."""
    defaults = dict(
        law_id="140AC0000000045",
        law_name_ja="刑法",
        law_name_en="Penal Code",
        article_number="36",
        article_id="keihou-art-36",
        version_date=date(2007, 6, 12),
        translation_status=TranslationStatus.NONE,
        source_url="https://laws.e-gov.go.jp/law/140AC0000000045",
        last_verified=date(2026, 5, 18),
    )
    defaults.update(overrides)
    return JuriCodeArticle(**defaults)


def test_juricode_article_minimal() -> None:
    article = _build_minimal_article()
    assert article.article_id == "keihou-art-36"
    assert article.license == "MIT"


def test_juricode_article_id_must_match_number() -> None:
    with pytest.raises(ValidationError, match="article_id"):
        _build_minimal_article(article_number="36", article_id="keihou-art-99")


def test_juricode_article_last_verified_must_be_after_version() -> None:
    with pytest.raises(ValidationError, match="last_verified"):
        _build_minimal_article(
            version_date=date(2026, 5, 18),
            last_verified=date(2025, 1, 1),  # before version_date
        )


def test_juricode_article_paragraphs_sequential() -> None:
    """項番号は連番でなければならない."""
    with pytest.raises(ValidationError, match="paragraphs\\[1\\]"):
        _build_minimal_article(
            paragraphs=[
                Paragraph(number=1, text="一項"),
                Paragraph(number=3, text="三項 (連番でない)"),
            ]
        )


def test_juricode_article_paragraphs_ok_when_sequential() -> None:
    article = _build_minimal_article(
        paragraphs=[
            Paragraph(number=1, text="一項"),
            Paragraph(number=2, text="二項"),
        ]
    )
    assert len(article.paragraphs) == 2


def test_juricode_article_duplicate_case_id_rejected() -> None:
    case = CaseReference(
        case_id="scj-1969-12-04-keishu-23-12-1573",
        court="最高裁",
        court_en="Supreme Court",
        decision_date=date(1969, 12, 4),
        citation="刑集23巻12号1573頁",
        url="https://example.com",
        relevance=Relevance.HIGH,
    )
    with pytest.raises(ValidationError, match="Duplicate case_id"):
        _build_minimal_article(cases=[case, case])


def test_juricode_article_branch_article_number() -> None:
    """枝番付き条 (36 条の 2) も扱える."""
    article = _build_minimal_article(
        article_number="36-2",
        article_id="keihou-art-36-2",
    )
    assert article.article_number == "36-2"


def test_juricode_article_full_example() -> None:
    """刑法 36 条相当の完全例."""
    article = JuriCodeArticle(
        law_id="140AC0000000045",
        law_name_ja="刑法",
        law_name_en="Penal Code",
        article_number="36",
        article_id="keihou-art-36",
        version_date=date(2007, 6, 12),
        article_caption="(正当防衛)",
        article_title="第三十六条",
        parent_section=ParentSection(
            hen=1,
            hen_name_ja="第一編 総則",
            hen_name_en="Part I General Provisions",
            shou=7,
            shou_name_ja="第七章 犯罪の不成立及び刑の減免",
            shou_name_en="Chapter VII Non-Establishment of Crime and Reduction or Remission of Punishment",
        ),
        paragraphs=[
            Paragraph(number=1, text="急迫不正の侵害に対して..."),
            Paragraph(number=2, text="防衛の程度を超えた行為は..."),
        ],
        translation_status=TranslationStatus.OFFICIAL,
        machine_translated=False,
        english_translation=EnglishTranslation(
            paragraphs=[
                EnglishParagraph(number=1, text="An act unavoidably performed..."),
                EnglishParagraph(number=2, text="An act exceeding the limits..."),
            ],
            source="Japanese Law Translation Database, Ministry of Justice",
        ),
        cases=[
            CaseReference(
                case_id="scj-pb1-1969-12-04-keishu-23-12-1573",
                court="最高裁判所第一小法廷",
                court_en="Supreme Court of Japan, First Petty Bench",
                decision_date=date(1969, 12, 4),
                citation="刑集23巻12号1573頁",
                url="https://www.courts.go.jp/app/hanrei_jp/detail2?id=...",
                relevance=Relevance.HIGH,
                relevant_paragraph=1,
            ),
        ],
        amendments=[],
        source_url="https://laws.e-gov.go.jp/law/140AC0000000045",
        last_verified=date(2026, 5, 18),
        tags=["phase1-police", "刑事法", "正当防衛", "違法性阻却事由"],
    )
    assert article.article_id == "keihou-art-36"
    assert len(article.paragraphs) == 2
    assert len(article.cases) == 1
    assert article.cases[0].relevance == Relevance.HIGH
    # シリアライズして round-trip
    dumped = article.model_dump_json()
    restored = JuriCodeArticle.model_validate_json(dumped)
    assert restored == article


def test_juricode_article_rejects_extra_field() -> None:
    """extra='forbid' なので未知フィールドは拒否."""
    with pytest.raises(ValidationError):
        JuriCodeArticle(
            law_id="140AC0000000045",
            law_name_ja="刑法",
            law_name_en="Penal Code",
            article_number="36",
            article_id="keihou-art-36",
            version_date=date(2007, 6, 12),
            translation_status=TranslationStatus.NONE,
            source_url="https://example.com",
            last_verified=date(2026, 5, 18),
            unknown_field="should be rejected",
        )


# ---- 2026-05-18 追加 integrity rule (P0-2) ----


def test_relevant_paragraph_must_exist() -> None:
    """ir-spec.md §5.2: cases[].relevant_paragraph は実在する項番号."""
    case_invalid = CaseReference(
        case_id="scj-1969-12-04-keishu-23-12-1573",
        court="最高裁",
        court_en="Supreme Court",
        decision_date=date(1969, 12, 4),
        citation="刑集23巻12号1573頁",
        url="https://example.com",
        relevance=Relevance.HIGH,
        relevant_paragraph=99,  # paragraphs は 2 つしかない
    )
    with pytest.raises(ValidationError, match="relevant_paragraph=99"):
        _build_minimal_article(
            paragraphs=[
                Paragraph(number=1, text="一項"),
                Paragraph(number=2, text="二項"),
            ],
            cases=[case_invalid],
        )


def test_relevant_paragraph_none_is_ok() -> None:
    """relevant_paragraph が None ならチェックスキップ."""
    case_ok = CaseReference(
        case_id="scj-1969-12-04-keishu-23-12-1573",
        court="最高裁",
        court_en="Supreme Court",
        decision_date=date(1969, 12, 4),
        citation="刑集23巻12号1573頁",
        url="https://example.com",
        relevance=Relevance.HIGH,
        relevant_paragraph=None,
    )
    article = _build_minimal_article(
        paragraphs=[Paragraph(number=1, text="一項")],
        cases=[case_ok],
    )
    assert len(article.cases) == 1


def test_english_translation_with_none_status_rejected() -> None:
    """ir-spec.md §5.2: english_translation 存在時に translation_status=NONE は不整合."""
    et = EnglishTranslation(
        paragraphs=[EnglishParagraph(number=1, text="An act unavoidably...")],
        source="Test",
    )
    with pytest.raises(ValidationError, match="translation_status is 'none'"):
        _build_minimal_article(
            translation_status=TranslationStatus.NONE,
            english_translation=et,
        )


def test_english_translation_with_draft_status_ok() -> None:
    """english_translation あり + status=DRAFT は OK."""
    et = EnglishTranslation(
        paragraphs=[EnglishParagraph(number=1, text="An act unavoidably...")],
    )
    article = _build_minimal_article(
        translation_status=TranslationStatus.DRAFT,
        english_translation=et,
    )
    assert article.english_translation is not None


def test_english_translation_none_with_status_none_ok() -> None:
    ""

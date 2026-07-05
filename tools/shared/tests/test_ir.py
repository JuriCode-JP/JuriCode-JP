"""IR Pydantic モデルのテスト."""

from datetime import date

import pytest
from pydantic import ValidationError

from juricode_shared.ir import (
    AppealRelation,
    EnglishParagraph,
    EnglishTranslation,
    Item,
    JuriCodeArticle,
    Paragraph,
    ParentSection,
    PrecedentReference,
    Relevance,
    RulingReference,
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


# ---- CaseReference (discriminated union: precedent / ruling) ----


def _precedent(**overrides) -> PrecedentReference:
    """最小限の有効な PrecedentReference を構築."""
    defaults = dict(
        case_type="precedent",
        case_id="scj-pb1-1969-12-04-keishu-23-12-1573",
        court="最高裁判所第一小法廷",
        court_en="Supreme Court of Japan, First Petty Bench",
        decision_date=date(1969, 12, 4),
        citation="刑集23巻12号1573頁",
        url="https://www.courts.go.jp/app/hanrei_jp/detail2?id=...",
        relevance=Relevance.HIGH,
        source_license="public-domain",
        summary_source="self_summary_draft",
    )
    defaults.update(overrides)
    return PrecedentReference(**defaults)


def _ruling(**overrides) -> RulingReference:
    """最小限の有効な RulingReference を構築 (court/citation を持たない)."""
    defaults = dict(
        case_type="ruling",
        case_id="ntt-2020-06-24-r2-1-hojin",
        decision_date=date(2020, 6, 24),
        url="https://www.kfs.go.jp/service/JP/...",
        relevance=Relevance.MEDIUM,
        source_license="other",
        summary_source="none",
    )
    defaults.update(overrides)
    return RulingReference(**defaults)


def test_precedent_reference_basic() -> None:
    ref = _precedent()
    assert ref.case_type == "precedent"
    assert ref.case_id == "scj-pb1-1969-12-04-keishu-23-12-1573"
    assert ref.relevance == Relevance.HIGH
    assert ref.appeal_relation == []  # 予約フィールドは既定で空


def test_ruling_reference_basic_no_court() -> None:
    """裁決 (ruling) は court/citation なしで valid (裁決に裁判所・掲載誌は存在しない)."""
    ref = _ruling(saiketsu_ref="令2第1号", issue_code="H-01", tax_item="法人税")
    assert ref.case_type == "ruling"
    assert ref.case_id.startswith("ntt-")
    assert ref.saiketsu_ref == "令2第1号"


def test_case_reference_invalid_id_pattern() -> None:
    """基底パターン (CASE_ID_PATTERN) に合致しない case_id は拒否."""
    with pytest.raises(ValidationError):
        _precedent(case_id="INVALID_ID")


def test_precedent_missing_citation_rejected() -> None:
    """precedent は citation 必須 (欠落で reject)."""
    with pytest.raises(ValidationError):
        PrecedentReference(
            case_type="precedent",
            case_id="scj-2020-06-24-x",
            court="最高裁",
            court_en="SCJ",
            decision_date=date(2020, 6, 24),
            url="https://example.com",
            relevance=Relevance.HIGH,
            source_license="public-domain",
            summary_source="self_summary_draft",
        )


def test_ruling_with_court_rejected_extra_forbid() -> None:
    """ruling に court を入れると extra='forbid' で reject (種別と形状の不整合を弾く)."""
    with pytest.raises(ValidationError):
        _ruling(court="最高裁")


def test_precedent_with_ntt_prefix_rejected() -> None:
    """prefix と case_type の整合 (P0-1): precedent に ntt- prefix は reject."""
    with pytest.raises(ValidationError, match="court prefix"):
        _precedent(case_id="ntt-2020-06-24-x")


def test_ruling_with_court_prefix_rejected() -> None:
    """prefix と case_type の整合 (P0-1): ruling に scj- prefix は reject."""
    with pytest.raises(ValidationError, match="ntt-"):
        _ruling(case_id="scj-2020-06-24-x")


def test_case_union_discriminates_by_case_type() -> None:
    """JuriCodeArticle.cases は case_type で precedent/ruling を判別 (discriminated union)."""
    article = _build_minimal_article(
        paragraphs=[Paragraph(number=1, text="一項")],
        cases=[
            _precedent(relevant_paragraph=1),
            _ruling(case_id="ntt-2020-06-24-r2-1-hojin", relevant_paragraph=1),
        ],
    )
    assert isinstance(article.cases[0], PrecedentReference)
    assert isinstance(article.cases[1], RulingReference)
    # round-trip (dict discriminator で復元)
    restored = JuriCodeArticle.model_validate_json(article.model_dump_json())
    assert isinstance(restored.cases[0], PrecedentReference)
    assert isinstance(restored.cases[1], RulingReference)


def test_appeal_relation_shape() -> None:
    """AppealRelation は relation の向き + case_id を持ち extra を禁止する."""
    ar = AppealRelation(relation="appealed_from", case_id="scj-2000-01-01-x")
    assert ar.relation == "appealed_from"
    with pytest.raises(ValidationError):
        AppealRelation(relation="sideways", case_id="scj-2000-01-01-x")


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
    case = _precedent(case_id="scj-1969-12-04-keishu-23-12-1573")
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
            _precedent(relevant_paragraph=1),
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
    case_invalid = _precedent(
        case_id="scj-1969-12-04-keishu-23-12-1573",
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
    case_ok = _precedent(
        case_id="scj-1969-12-04-keishu-23-12-1573",
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

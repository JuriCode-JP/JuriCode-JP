"""JuriCode IR (中間表現) - Pydantic v2 モデル.

docs/ir-spec.md および docs/format-spec.md の仕様を Pydantic v2 で実体化.
すべての tools/ サブパッケージで共通利用される.

1 つの JuriCodeArticle インスタンス = 1 つの条文 = 1 つの Markdown ファイル.

設計判断 (2026-05-18):
- `Paragraph.text` は default="" (空文字).
  本文は YAML frontmatter ではなく Markdown body の `### 第N条` セクションに格納されるため.
  tools/parse/ で body を読んで text を埋める設計.
- `ParentSection` は番号 (hen: int) と名前 (hen_name_ja, hen_name_en) を分離.
- `source_format` に `e-gov-html` を追加 (既存サンプル整合).
- 2026-05-18 P0-2 で 3 件の integrity rule を追加:
  - english_translation 存在時の translation_status チェック
  - cases[].relevant_paragraph の paragraph 存在チェック
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from juricode_shared.enums import Relevance, TranslationStatus
from juricode_shared.ids import (
    ARTICLE_ID_PATTERN,
    ARTICLE_NUMBER_PATTERN,
    CASE_ID_PATTERN,
)


class Item(BaseModel):
    """号 (項内の列挙)."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., ge=1, description="号番号 (1 始まり)")
    text: str = Field("", description="号の本文 (frontmatter では空、body から埋める)")


class Penalty(BaseModel):
    """刑罰の構造化情報 (Segment 単位で付随).

    主に刑事法で「○年以下の拘禁刑」「○万円以下の罰金」等を構造化するため.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        ...,
        description="刑種: kinkokei (拘禁刑) / bakkin (罰金) / karyou (科料) / shukei (主刑) / 等",
    )
    max_years: int | None = Field(None, description="最長刑期 (年)")
    min_years: int | None = Field(None, description="最短刑期 (年)")
    max_amount: int | None = Field(None, description="最高額 (円)")
    min_amount: int | None = Field(None, description="最低額 (円)")


class Segment(BaseModel):
    """v0.2 セグメント (項を更に細かく分解した単位: 本文/ただし書/柱書/号/前段/後段/特則/準用 等).

    `tools/parse/v0.2/segment_parser.py` の `Segment` dataclass と 1:1 対応する Pydantic モデル.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="セグメントの一意 ID")
    type: str = Field(
        ...,
        description="simple | honbun | tadashi | zen_dan | kou_dan | hashira | kou | tokusoku | junyou",
    )
    text: str = Field(..., description="セグメントの本文")
    modality: str = Field("unspecified", description="モダリティ (義務 / 禁止 / 許可 等)")
    item_number: int | None = Field(None, description="号番号 (type=kou のとき)")
    override_flag: bool = Field(False, description="読み替え / みなす規定か")
    override_target: list[str] = Field(default_factory=list, description="読み替え対象の参照")
    applies_provisions: list[str] = Field(default_factory=list, description="準用先の規定")
    references: list[str] = Field(default_factory=list, description="参照する条文 ID")
    depends_on: str | None = Field(None, description="依存する別 segment ID")
    condition: str | None = Field(
        None, description="この segment が発動する条件 (e.g. '請託を受けたとき')"
    )
    penalty: Penalty | None = Field(None, description="付随する刑罰の構造化情報")


class Paragraph(BaseModel):
    """項."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., ge=1, description="項番号 (1 始まり)")
    text: str = Field("", description="項の本文 (frontmatter では空、body から埋める)")
    has_proviso: bool = Field(False, description="但書を含むか")
    has_items: bool = Field(False, description="各号 (列挙) を含むか")
    is_added_by_amendment: bool = Field(False, description="改正で追加された項か")
    items: list[Item] = Field(default_factory=list, description="号 (列挙) があれば一覧")
    segments: list[Segment] = Field(
        default_factory=list,
        description="v0.2 セグメント分解 (空 list の場合は未分解、または分解不要な項)",
    )


class ParentSection(BaseModel):
    """親階層 (編・章・節・款・目)."""

    model_config = ConfigDict(extra="forbid")

    hen: int | None = Field(None, description="編番号")
    hen_name_ja: str | None = Field(None, description="編名 (日本語)")
    hen_name_en: str | None = Field(None, description="編名 (英語)")
    shou: int | None = Field(None, description="章番号")
    shou_name_ja: str | None = Field(None, description="章名 (日本語)")
    shou_name_en: str | None = Field(None, description="章名 (英語)")
    setsu: int | None = Field(None, description="節番号")
    setsu_name_ja: str | None = Field(None, description="節名 (日本語)")
    setsu_name_en: str | None = Field(None, description="節名 (英語)")
    kan: int | None = Field(None, description="款番号")
    kan_name_ja: str | None = Field(None, description="款名 (日本語)")
    kan_name_en: str | None = Field(None, description="款名 (英語)")
    moku: int | None = Field(None, description="目番号")
    moku_name_ja: str | None = Field(None, description="目名 (日本語)")
    moku_name_en: str | None = Field(None, description="目名 (英語)")


class EnglishItem(BaseModel):
    """英訳の号."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., ge=1)
    text: str


class EnglishParagraph(BaseModel):
    """英訳の項."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., ge=1)
    text: str
    items: list[EnglishItem] = Field(default_factory=list)


class EnglishTranslation(BaseModel):
    """英訳本文."""

    model_config = ConfigDict(extra="forbid")

    paragraphs: list[EnglishParagraph] = Field(..., description="項単位の英訳")
    source: str | None = Field(None, description="英訳の出典")
    source_url: str | None = Field(None, description="出典 URL")


class CaseReference(BaseModel):
    """判例リンク."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., pattern=CASE_ID_PATTERN.pattern, description="判例の一意 ID")
    court: str = Field(..., description="裁判所 (日本語)")
    court_en: str = Field(..., description="裁判所 (英語)")
    decision_date: date = Field(..., description="判決日")
    citation: str = Field(..., description="掲載誌・巻号")
    case_name_ja: str | None = Field(None, description="事件名 (日本語)")
    case_name_en: str | None = Field(None, description="事件名 (英語)")
    url: str = Field(..., description="裁判所 Web の permalink")
    relevance: Relevance = Field(..., description="この条文との関連度")
    relevant_paragraph: int | None = Field(None, ge=1, description="関連する項番号 (任意)")
    summary_ja: str | None = Field(None, description="判例要旨 (日本語)")
    summary_en: str | None = Field(None, description="判例要旨 (英語)")
    tags: list[str] = Field(default_factory=list, description="判例タグ (任意)")


class Amendment(BaseModel):
    """この条文の改正履歴 (1 件)."""

    model_config = ConfigDict(extra="forbid")

    effective_date: date = Field(..., description="改正の施行日")
    law_num: str = Field(..., description="改正法の法令番号")
    law_name: str | None = Field(None, description="改正法の名称")
    description: str | None = Field(None, description="改正の概要")
    source_url: str | None = Field(None, description="改正情報の出典 URL")


SourceFormat = Literal["e-gov-xml", "e-gov-html", "manual", "import-lawtext"]


class JuriCodeArticle(BaseModel):
    """1 つの条文を表す中間表現. 最上位エンティティ."""

    model_config = ConfigDict(extra="forbid")

    law_id: str = Field(..., description="e-Gov 法令ID")
    law_name_ja: str = Field(..., description="法令名 (日本語)")
    law_name_en: str = Field(..., description="法令名 (英語)")
    article_number: str = Field(..., pattern=ARTICLE_NUMBER_PATTERN.pattern, description="条番号")
    article_id: str = Field(..., pattern=ARTICLE_ID_PATTERN.pattern, description="条文 ID")
    version_date: date = Field(..., description="現行条文の施行日")

    article_caption: str | None = Field(None, description="条見出し")
    article_title: str | None = Field(None, description="条のタイトル")
    parent_section: ParentSection | None = Field(None, description="編・章・節の親階層")
    paragraphs: list[Paragraph] = Field(default_factory=list)

    translation_status: TranslationStatus = Field(..., description="英訳の出所")
    machine_translated: bool = Field(False)
    english_translation: EnglishTranslation | None = Field(None)

    cases: list[CaseReference] = Field(default_factory=list)
    amendments: list[Amendment] = Field(default_factory=list)
    amendments_summary: str | None = Field(
        None, description="改正履歴の自由記述サマリ (paragraph 単位でない総括コメント用)"
    )

    source_url: str = Field(..., description="e-Gov 法令API の参照 URL")
    source_format: SourceFormat = Field("e-gov-xml")
    last_verified: date = Field(..., description="原典との突合日")
    license: str = Field("MIT")

    tags: list[str] = Field(default_factory=list)
    notes: str | None = Field(None)

    @field_validator("article_id")
    @classmethod
    def article_id_matches_number(cls, v: str, info: Any) -> str:
        data = info.data if hasattr(info, "data") else {}
        if "article_number" in data:
            num = data["article_number"]
            if not v.endswith(f"-art-{num}"):
                raise ValueError(
                    f"article_id ({v}) must end with '-art-{num}' to match article_number={num}"
                )
        return v

    @field_validator("last_verified")
    @classmethod
    def last_verified_after_version_date(cls, v: date, info: Any) -> date:
        data = info.data if hasattr(info, "data") else {}
        if "version_date" in data and v < data["version_date"]:
            raise ValueError(
                f"last_verified ({v}) must be on or after version_date ({data['version_date']})"
            )
        return v

    @field_validator("paragraphs")
    @classmethod
    def paragraphs_numbered_sequentially(cls, v: list[Paragraph]) -> list[Paragraph]:
        for i, p in enumerate(v, start=1):
            if p.number != i:
                raise ValueError(f"paragraphs[{i - 1}].number == {p.number}, expected {i}.")
        return v

    @field_validator("cases")
    @classmethod
    def cases_have_unique_ids(cls, v: list[CaseReference]) -> list[CaseReference]:
        seen = set()
        for c in v:
            if c.case_id in seen:
                raise ValueError(f"Duplicate case_id: {c.case_id}")
            seen.add(c.case_id)
        return v

    @field_validator("cases")
    @classmethod
    def cases_relevant_paragraph_exists(
        cls, v: list[CaseReference], info: Any
    ) -> list[CaseReference]:
        data = info.data if hasattr(info, "data") else {}
        paragraphs = data.get("paragraphs", []) or []
        if not paragraphs:
            return v
        para_nums = {p.number for p in paragraphs}
        for c in v:
            if c.relevant_paragraph is not None and c.relevant_paragraph not in para_nums:
                raise ValueError(
                    f"case_id={c.case_id}: relevant_paragraph={c.relevant_paragraph} "
                    f"does not match any paragraph number (available: {sorted(para_nums)})"
                )
        return v

    @field_validator("english_translation")
    @classmethod
    def english_translation_implies_status(cls, v, info: Any):
        if v is None:
            return v
        data = info.data if hasattr(info, "data") else {}
        status = data.get("translation_status")
        if status == TranslationStatus.NONE:
            raise ValueError(
                "english_translation is set but translation_status is 'none'. "
                "Set translation_status to 'official', 'community', or 'draft'."
            )
        return v

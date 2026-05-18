# JuriCode IR(中間表現)仕様

**バージョン**: v0.1 (2026-05-18 初版)
**位置づけ**: `tools/parse/` の出力 = `tools/transform/`, `tools/translate/`, `tools/render/` の共通入出力型
**実装場所**: `tools/shared/src/juricode_shared/ir.py`
**関連文書**: [architecture.md](./architecture.md)(全体設計)、[format-spec.md](./format-spec.md)(最終 YAML+Markdown 仕様)

---

## 1. 概要

JuriCode IR は、e-Gov XML(`Law` ja-law-parser モデル)と最終出力(YAML frontmatter + Markdown)の中間に位置する **Pydantic ベースの構造化データ型**。

### 1.1 なぜ IR が必要か

| 要件 | IR がない場合 | IR がある場合 |
|---|---|---|
| ステージ間の型安全性 | 各ステージで dict や独自型を扱う、型不整合の温床 | Pydantic の型チェックで保証 |
| 法令単位 vs 条文単位の境界 | 各ツールが独自に分割 | `tools/transform/` で 1 回だけ条文単位に分割 |
| 英訳・判例の付加 | XML を直接いじる or 後付け | IR の `english_translation`, `cases` フィールドに統合 |
| テスト容易性 | XML 文字列を作成必要 | Pydantic オブジェクトを直接インスタンス化 |
| 将来の出力形式拡張 | YAML+MD 専用ロジック | IR から JSON-LD、Schema.org Legislation 等への変換が可能 |

### 1.2 IR のスコープ

- **単位**: 1 つの `JuriCodeArticle` インスタンス = 1 つの条文(1 ファイルに対応)
- **言語**: 日本語原文 + 英訳(任意)を併記
- **メタデータ**: e-Gov 法令ID、施行日、出典 URL、判例リンク、改正履歴 を含む

---

## 2. データモデル全体図

```
JuriCodeArticle
├── 基本メタデータ(law_id, law_name_ja, law_name_en, article_number, article_id, ...)
├── 本文構造
│   ├── article_caption: str | None        # "(正当防衛)"
│   ├── article_title: str | None          # "第三十六条"
│   ├── parent_section: ParentSection | None  # 編・章・節情報
│   └── paragraphs: list[Paragraph]
│       ├── number: int
│       ├── text: str                       # 本文
│       ├── has_proviso: bool
│       └── items: list[Item]               # 各号
│           ├── number: int
│           └── text: str
├── 翻訳
│   ├── translation_status: TranslationStatus
│   ├── machine_translated: bool
│   └── english_translation: EnglishTranslation | None
├── 判例リンク
│   └── cases: list[CaseReference]
│       ├── case_id, court, decision_date, citation, ...
│       ├── relevance: Relevance
│       └── summary_ja, summary_en
├── 改正履歴
│   └── amendments: list[Amendment]
└── その他
    ├── version_date, source_url, source_format, last_verified
    ├── license, tags, notes
```

---

## 3. 各モデルの詳細

### 3.1 JuriCodeArticle(条文)

最上位エンティティ。1 つの条文 = 1 ファイル。

```python
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

class JuriCodeArticle(BaseModel):
    """1 つの条文を表す中間表現."""

    model_config = ConfigDict(extra="forbid")  # 不明なフィールドは禁止(IR は厳密)

    # ---- 基本メタデータ ----
    law_id: str = Field(..., description="e-Gov 法令ID(例: 140AC0000000045)")
    law_name_ja: str = Field(..., description="法令名(日本語、例: 刑法)")
    law_name_en: str = Field(..., description="法令名(英語、政府公定訳優先)")
    article_number: str = Field(
        ...,
        pattern=r"^[0-9]+(-[0-9]+)*$",
        description="条番号. 算用数字、枝番ハイフン区切り(例: '36', '36-2')",
    )
    article_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9-]*-art-[0-9]+(-[0-9]+)*$",
        description="条文の一意 ID(例: 'keihou-art-36', 'keihou-art-36-2')",
    )
    version_date: date = Field(..., description="現行条文の施行日")

    # ---- 本文構造 ----
    article_caption: str | None = Field(
        None, description="条見出し(例: '(正当防衛)')"
    )
    article_title: str | None = Field(
        None, description="条のタイトル(例: '第三十六条')"
    )
    parent_section: "ParentSection | None" = Field(
        None, description="編・章・節・款・目の親階層情報"
    )
    paragraphs: list["Paragraph"] = Field(
        default_factory=list, description="項の一覧"
    )

    # ---- 翻訳 ----
    translation_status: "TranslationStatus" = Field(
        ..., description="英訳の出所(official / community / draft / none)"
    )
    machine_translated: bool = Field(
        False, description="機械翻訳が含まれているか"
    )
    english_translation: "EnglishTranslation | None" = Field(
        None, description="英訳本文(全体)"
    )

    # ---- 判例リンク ----
    cases: list["CaseReference"] = Field(
        default_factory=list, description="関連判例の一覧"
    )

    # ---- 改正履歴 ----
    amendments: list["Amendment"] = Field(
        default_factory=list, description="この条文の改正履歴"
    )

    # ---- 出典・メタ ----
    source_url: str = Field(
        ..., description="e-Gov 法令API の参照 URL"
    )
    source_format: Literal[
        "e-gov-xml",
        "e-gov-html",
        "manual",
        "import-lawtext",
    ] = Field(
        "e-gov-xml", description="元データのフォーマット"
    )
    # source_format の使い分け (2026-05-18 P0-1 で 4 値に拡張):
    #   - "e-gov-xml":      e-Gov 法令 API v2 から XML を取得して構造化した場合 (推奨パス)
    #   - "e-gov-html":     e-Gov の HTML レンダリングをパースして構造化した場合
    #                       (Phase 1 初期サンプルなど、API 移行前に作った条文に使う)
    #   - "manual":         手動入力 (新法施行直後で API 未対応のときの暫定)
    #   - "import-lawtext": Lawtext (yamachig) の XML を変換して取り込んだ場合
    last_verified: date = Field(..., description="原典との突合日")
    license: str = Field("MIT", description="このファイルのライセンス")

    # ---- タグ・注記 ----
    tags: list[str] = Field(default_factory=list, description="自由なタグ")
    notes: str | None = Field(None, description="本文外の補足説明")

    @field_validator("article_id")
    @classmethod
    def article_id_matches_number(cls, v: str, info) -> str:
        """article_id と article_number の整合性を検証."""
        if "article_number" in info.data:
            num = info.data["article_number"]
            if not v.endswith(f"-art-{num}"):
                raise ValueError(
                    f"article_id ({v}) must end with '-art-{num}' "
                    f"to match article_number"
                )
        return v
```

### 3.2 Paragraph(項)

```python
class Paragraph(BaseModel):
    """項."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., ge=1, description="項番号(1 始まり)")
    text: str = Field(..., description="項の本文(漢数字でも算用数字でも OK)")
    has_proviso: bool = Field(
        False, description="但書を含むか(本文の構造化判定用)"
    )
    items: list["Item"] = Field(
        default_factory=list, description="号(列挙)があれば一覧"
    )
```

### 3.3 Item(号)

```python
class Item(BaseModel):
    """号(項内の列挙)."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., ge=1, description="号番号(1 始まり)")
    text: str = Field(..., description="号の本文")
```

### 3.4 ParentSection(編・章・節情報)

```python
class ParentSection(BaseModel):
    """親階層(編・章・節・款・目)."""

    model_config = ConfigDict(extra="forbid")

    hen: str | None = Field(None, description="編名(例: '第一編 総則')")
    shou: str | None = Field(None, description="章名(例: '第七章 犯罪の不成立及び刑の減免')")
    setsu: str | None = Field(None, description="節名")
    kan: str | None = Field(None, description="款名")
    moku: str | None = Field(None, description="目名")
```

### 3.5 TranslationStatus(列挙)

```python
from enum import StrEnum

class TranslationStatus(StrEnum):
    """英訳の出所."""

    OFFICIAL = "official"      # 法務省 JLT-DB の公定訳
    COMMUNITY = "community"    # コミュニティ訳(CC BY 4.0 推奨)
    DRAFT = "draft"            # 機械翻訳・ドラフト
    NONE = "none"              # 英訳なし
```

### 3.6 EnglishTranslation(英訳)

```python
class EnglishTranslation(BaseModel):
    """英訳本文."""

    model_config = ConfigDict(extra="forbid")

    paragraphs: list["EnglishParagraph"] = Field(
        ..., description="項単位の英訳"
    )
    source: str | None = Field(
        None,
        description=(
            "英訳の出典(例: 'Japanese Law Translation Database, "
            "Ministry of Justice')"
        ),
    )
    source_url: str | None = Field(None, description="出典 URL")

class EnglishParagraph(BaseModel):
    """項単位の英訳."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., ge=1)
    text: str
    items: list["EnglishItem"] = Field(default_factory=list)

class EnglishItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(..., ge=1)
    text: str
```

### 3.7 CaseReference(判例リンク)

```python
class CaseReference(BaseModel):
    """判例リンク."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(
        ...,
        pattern=r"^[a-z]{3,5}-[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+$",
        description=(
            "判例の一意 ID. 形式: '{court-abbrev}-{YYYY}-{MM}-{DD}-{citation-slug}'. "
            "例: 'scj-1969-12-04-keishu-23-12-1573'"
        ),
    )
    court: str = Field(..., description="裁判所(日本語、例: '最高裁判所第一小法廷')")
    court_en: str = Field(
        ..., description="裁判所(英語、例: 'Supreme Court of Japan, First Petty Bench')"
    )
    decision_date: date = Field(..., description="判決日")
    citation: str = Field(
        ..., description="掲載誌・巻号(例: '刑集23巻12号1573頁')"
    )
    case_name_ja: str | None = Field(None, description="事件名(日本語)")
    case_name_en: str | None = Field(None, description="事件名(英語)")
    url: str = Field(
        ..., description="裁判所 Web の permalink、または判例 DB の永続 URL"
    )
    relevance: "Relevance" = Field(
        ..., description="この条文との関連度(high / medium / low)"
    )
    relevant_paragraph: int | None = Field(
        None, ge=1, description="この判例が関連する項番号(任意)"
    )
    summary_ja: str | None = Field(None, description="判例要旨(日本語)")
    summary_en: str | None = Field(None, description="判例要旨(英語)")

class Relevance(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

### 3.8 Amendment(改正履歴)

```python
class Amendment(BaseModel):
    """この条文の改正履歴(1 件)."""

    model_config = ConfigDict(extra="forbid")

    effective_date: date = Field(..., description="改正の施行日")
    law_num: str = Field(
        ..., description="改正法の法令番号(例: '令和7年法律第15号')"
    )
    law_name: str | None = Field(None, description="改正法の名称")
    description: str | None = Field(
        None, description="改正の概要(自由記述、例: '拘禁刑への一本化')"
    )
    source_url: str | None = Field(None, description="改正情報の出典 URL")
```

---

## 4. ID 規約

### 4.1 `article_id`

形式: `{law-abbrev}-art-{article_number}`

| 例 | 意味 |
|---|---|
| `keihou-art-36` | 刑法 第 36 条 |
| `keihou-art-36-2` | 刑法 第 36 条の 2 |
| `keiji-soshou-hou-art-203` | 刑事訴訟法 第 203 条 |
| `kenpou-art-9` | 日本国憲法 第 9 条 |

検証ロジック: `tools/shared/src/juricode_shared/ids.py::make_article_id()` で生成、`article_number` と一致する正規表現でバリデート。

### 4.2 `case_id`

形式: `{court-abbrev}-{YYYY}-{MM}-{DD}-{citation-slug}`

| 例 | 意味 |
|---|---|
| `scj-1969-12-04-keishu-23-12-1573` | 最高裁 1969-12-04 / 刑集 23 巻 12 号 1573 頁 |
| `oh-2010-03-25-hanji-2080-65` | 大阪高裁 2010-03-25 / 判時 2080 号 65 頁 |
| `tdc-2024-01-15-keishu-78-1-12` | 東京地裁 2024-01-15 / 刑集 78 巻 1 号 12 頁 |

裁判所略号:
- `scj` = Supreme Court of Japan(最高裁判所、大法廷・小法廷を区別しない場合)
- `scj-gb` = Grand Bench(大法廷)
- `scj-pb1` / `scj-pb2` / `scj-pb3` = 第一/二/三小法廷
- `oh` / `nh` / `th` 等 = 高等裁判所(大阪・名古屋・東京)
- `tdc` / `odc` 等 = 地方裁判所(東京・大阪)

citation-slug:
- 掲載誌略号 + 巻号(例: `keishu-23-12-1573`)
- 全部小文字、ハイフン区切り
- 判例集略号は `docs/glossary.md` §3 参照

---

## 5. 検証ルール

### 5.1 必須フィールド一覧

| フィールド | 必須 | 検証 |
|---|---|---|
| `law_id` | ✅ | 非空、英数 13 桁 or 特例 |
| `law_name_ja` | ✅ | 非空 |
| `law_name_en` | ✅ | 非空 |
| `article_number` | ✅ | `^[0-9]+(-[0-9]+)*$` |
| `article_id` | ✅ | `^[a-z][a-z0-9-]*-art-[0-9]+(-[0-9]+)*$`、`article_number` と整合 |
| `version_date` | ✅ | ISO 8601 date |
| `source_url` | ✅ | URL 形式、`https://laws.e-gov.go.jp/...` 推奨 |
| `last_verified` | ✅ | ISO 8601 date、`version_date` 以降 |
| `translation_status` | ✅ | TranslationStatus 列挙のいずれか |
| `paragraphs` | (空配列 OK) | 各項の `number` は 1 始まり連番 |
| `cases` | (空配列 OK) | `case_id` 重複禁止 |
| `amendments` | (空配列 OK) | `effective_date` 昇順推奨 |

### 5.2 整合性ルール

| ルール | 実装 (2026-05-18) |
|---|---|
| `article_id` が `{law-abbrev}-art-{article_number}` パターンと一致 | ✅ IR `article_id_matches_number` |
| `last_verified >= version_date` | ✅ IR `last_verified_after_version_date` |
| `paragraphs` の `number` は 1, 2, 3, ... の連番 | ✅ IR `paragraphs_numbered_sequentially` |
| `cases[].case_id` の重複禁止 | ✅ IR `cases_have_unique_ids` |
| `english_translation` 存在 → `translation_status != NONE` | ✅ IR `english_translation_implies_status` (P0-2 追加) |
| `cases[].relevant_paragraph` → `paragraphs[].number` と一致 | ✅ IR `cases_relevant_paragraph_exists` (P0-2 追加) |
| `machine_translated == True` → `translation_status` は `DRAFT` 推奨 | ⚠️ `_validate.py` で warning 出力 (P0-2 追加) |

### 5.3 警告(エラーではないが推奨)

- `translation_status == OFFICIAL` で `english_translation.source` が空 → 警告
- `cases[].url` の生存確認(別ジョブで `tools/validate/case_url_check.py`)
- `notes` が 500 字超 → 構造化を再検討すべき

---

## 6. シリアライゼーション

IR は通常 in-memory で扱うが、デバッグ用に JSON シリアライズ可能:

```python
article = JuriCodeArticle(...)
json_str = article.model_dump_json(indent=2, exclude_none=True)
# → JSON で保存(`tools/pipeline/--dump-ir` で使用)
```

### 6.1 YAML frontmatter とのマッピング

IR フィールド → YAML frontmatter:

| IR フィールド | YAML frontmatter キー | 備考 |
|---|---|---|
| `law_id` | `law_id` | そのまま |
| `law_name_ja` | `law_name_ja` | そのまま |
| `law_name_en` | `law_name_en` | そのまま |
| `article_number` | `article_number` | クォート必須(`"36"`) |
| `article_id` | `article_id` | そのまま |
| `version_date` | `version_date` | ISO 8601 |
| `source_url` | `source_url` | そのまま |
| `last_verified` | `last_verified` | ISO 8601 |
| `license` | `license` | そのまま |
| `translation_status` | `translation_status` | StrEnum → string |
| `machine_translated` | `machine_translated` | bool |
| `paragraphs[]` | `paragraphs[]` | `number` と `has_proviso` のみ frontmatter、本文は MD 内 |
| `cases[]` | `cases[]` | 全部 frontmatter |
| `amendments[]` | `amendments[]` | 全部 frontmatter |
| `tags` | `tags` | そのまま |
| `parent_section` | `parent_section` | 任意 |

本文(Markdown body)に出力されるのは:
- `## 原文(日本語)` セクション ← `paragraphs[].text`
- `## English Translation` セクション ← `english_translation.paragraphs[].text`
- `## 判例リンク` セクション ← `cases[]` の人間可読版
- `## 改正履歴` セクション ← `amendments[]` の人間可読版
- `## 注記` セクション ← `notes`

詳細は [format-spec.md](./format-spec.md) を参照。

---

## 7. 利用例

### 7.1 刑法 36 条の IR インスタンス例

```python
from datetime import date
from juricode_shared.ir import (
    JuriCodeArticle, Paragraph, ParentSection,
    TranslationStatus, EnglishTranslation, EnglishParagraph,
    CaseReference, Relevance,
)

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
        hen="第一編 総則",
        shou="第七章 犯罪の不成立及び刑の減免",
    ),
    paragraphs=[
        Paragraph(
            number=1,
            text="急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。",
            has_proviso=False,
        ),
        Paragraph(
            number=2,
            text="防衛の程度を超えた行為は、情状により、その刑を減軽し、又は免除することができる。",
            has_proviso=False,
        ),
    ],
    translation_status=TranslationStatus.OFFICIAL,
    machine_translated=False,
    english_translation=EnglishTranslation(
        paragraphs=[
            EnglishParagraph(
                number=1,
                text=(
                    "An act unavoidably performed to defend the rights of "
                    "oneself or any other person against imminent and "
                    "unlawful infringement is not punishable."
                ),
            ),
            EnglishParagraph(
                number=2,
                text=(
                    "An act exceeding the limits of defense may lead to "
                    "the punishment being reduced or exonerated in light "
                    "of the circumstances."
                ),
            ),
        ],
        source="Japanese Law Translation Database, Ministry of Justice",
        source_url="http://www.japaneselawtranslation.go.jp/...",
    ),
    cases=[
        CaseReference(
            case_id="scj-pb1-1969-12-04-keishu-23-12-1573",
            court="最高裁判所第一小法廷",
            court_en="Supreme Court of Japan, First Petty Bench",
            decision_date=date(1969, 12, 4),
            citation="刑集23巻12号1573頁",
            case_name_ja="急迫不正の侵害の意義",
            case_name_en="Meaning of 'imminent and unjust infringement'",
            url="https://www.courts.go.jp/app/hanrei_jp/detail2?id=...",
            relevance=Relevance.HIGH,
            relevant_paragraph=1,
            summary_ja="...",
            summary_en="...",
        ),
    ],
    amendments=[],
    source_url="https://laws.e-gov.go.jp/law/140AC0000000045",
    source_format="e-gov-xml",
    last_verified=date(2026, 5, 14),
    license="MIT",
    tags=["phase1-police", "正当防衛", "違法性阻却事由"],
)
```

### 7.2 IR → YAML+MD への変換

`tools/render/` の責任。IR を Pydantic で構築 → `juricode_render.render_yaml(article)` で YAML 文字列、`render_markdown(article)` で MD 文字列を生成。

`examples/keihou/keihou-article-36.md` がこの変換の正解出力。

---

## 8. バージョニング

IR スキーマ自体のバージョンを `juricode_shared.__version__` で管理。

- 破壊的変更(必須フィールドの追加・型変更)→ メジャー版アップ
- 後方互換な拡張(任意フィールドの追加)→ マイナー版アップ
- ドキュメント・コメント変更 → パッチ版アップ

`data/` 配下の各 Markdown ファイル frontmatter にも `ir_version: "0.1"` を含める提案(将来仕様)。

---

## 9. 関連

- [architecture.md](./architecture.md)— 全体アーキテクチャ
- [format-spec.md](./format-spec.md)— 最終 YAML+Markdown 出力フォーマット
- [glossary.md](./glossary.md)— 日英用語集、法令略称、判例集略号

---

*最終更新: 2026-05-18 (深夜更新: SourceFormat を 4 値に拡張、§5.2 整合性ルール表に impl 状況追加 — P0-1/P0-2 反映)*
*次回更新の目安: tools/shared/src/juricode_shared/ir.py 実装時、Pydantic で実体化したらドキュメントと突合*

# tools/shared — JuriCode-JP 共通モデル

すべての `tools/` サブパッケージが依存する共通ライブラリ。Pydantic v2 ベースの IR(中間表現)、ID 規約、ファイル配置ルールを集約。

## 主な公開 API

```python
from juricode_shared.ir import (
    JuriCodeArticle, Paragraph, Item, ParentSection,
    TranslationStatus, EnglishTranslation, CaseReference, Relevance, Amendment,
)
from juricode_shared.ids import make_article_id, make_case_id
from juricode_shared.paths import article_path
from juricode_shared.frontmatter import parse_frontmatter, dump_frontmatter
```

## 依存

- `pydantic>=2.7`
- `pyyaml>=6.0`

(他の tools/ サブパッケージには依存しない)

## セットアップ

```bash
cd tools/shared
uv sync
uv run pytest -v
```

## 関連ドキュメント

- [../../docs/ir-spec.md](../../docs/ir-spec.md) — IR の詳細仕様
- [../../docs/architecture.md](../../docs/architecture.md) — 全体設計
- [../../docs/format-spec.md](../../docs/format-spec.md) — 最終 YAML+Markdown 出力フォーマット

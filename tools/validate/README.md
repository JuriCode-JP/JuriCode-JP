# tools/validate — データ検証

法令データファイルの構造・スキーマ・出典の検証を行うツール群。

## 検証レイヤー

| レイヤー | 内容 | ツール |
|---|---|---|
| 1. Frontmatter スキーマ | YAML frontmatterが `schema/law-frontmatter.schema.json` を満たすか | `validate-file.py` |
| 2. 本文構造 | セクション順序・項番号の整合 | `validate-file.py` |
| 3. 判例リンク健全性 | citation形式、URL生存 | `check-case-urls.py` |
| 4. 原典忠実性 | e-Gov公式テキストと一致するか(注意: API依存・差分検出) | `verify-source.py`(将来) |
| 5. 英訳の出典 | `translation_status` と source_note の整合 | `validate-file.py` |

## CLI ユースケース(想定)

```bash
# 単一ファイルの検証
python tools/validate/validate-file.py data/phase1-police/keihou/keihou-article-36.md

# 全データ検証
python tools/validate/validate-all.py

# 判例URLの生存確認
python tools/validate/check-case-urls.py --since-days 30
```

## 依存

- `pyyaml`(YAML frontmatter 抽出)
- `jsonschema`(JSON Schema 検証)
- `requests` または `httpx`(URL確認)
- `frontmatter`(python-frontmatter)

## CI連携(将来)

PR時に GitHub Actions で自動実行する予定。

```yaml
# .github/workflows/validate.yml (将来)
on: [pull_request]
jobs:
  validate:
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r tools/validate/requirements.txt
      - run: python tools/validate/validate-all.py
```

## 実装ステータス

**v0.1 実装完了**(2026-05-18)。

- `_validate.py` — 検証ロジック(共通)
- `validate-file.py` — 単一/複数ファイル検証 CLI
- `validate-all.py` — `data/` + `examples/` 配下の全条文ファイル一括検証 CLI
- `tests/test_validate.py` — 8 件のテスト(`pytest tools/validate/tests/ -v`)

### 実装済み検証項目

1. ファイル存在・拡張子(`.md`)
2. YAML frontmatter のパース可能性
3. Pydantic IR (`JuriCodeArticle`) によるスキーマ検証(`tools/shared/` 連携)
4. ファイル名と `article_id` の整合(`{law-abbrev}-article-{N}.md`)
5. 本文必須セクション(`## 原文`)の存在
6. 警告レベル: `translation_status != none` のとき `## English Translation` セクション存在確認、`cases` 宣言があるとき `## 判例リンク` セクション存在確認

### 将来追加予定

- `check-case-urls.py` — 判例 URL の生存確認(`--since-days` で差分検出)
- `verify-source.py` — e-Gov 公式テキストとの原典忠実性検証
- GitHub Actions 連携(PR 時自動検証)

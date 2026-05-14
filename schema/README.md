# schema/ — JSON Schema for JuriCode-JP

このフォルダには法令データの**構造検証用 JSON Schema** を置く。

すべて [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12) に準拠する。

## ファイル一覧

| Schema | 用途 |
|---|---|
| [law-frontmatter.schema.json](./law-frontmatter.schema.json) | 法令ファイルのYAML frontmatterを検証 |
| [article.schema.json](./article.schema.json) | 条文全体(本文含む)の正規構造を定義 |
| [case-link.schema.json](./case-link.schema.json) | 判例リンク1件分の構造を定義(law-frontmatterから参照) |

## 検証方法

`tools/validate/` にPythonの検証スクリプトを置く予定。手元で確認したい場合は [ajv-cli](https://github.com/ajv-validator/ajv-cli) や [check-jsonschema](https://github.com/python-jsonschema/check-jsonschema) を使用:

```bash
# frontmatterをYAMLとして抜き出し、JSON Schemaで検証
python tools/validate/validate-file.py data/phase1-police/keihou/keihou-article-36.md
```

## スキーマのバージョニング

- 現在 v0.1 (Phase 1構築中、破壊的変更あり得る)
- v1.0 で Phase 1 終了時に固定
- それ以降は追加フィールドのみ可、必須フィールドの削除や型変更は major bump

## 関連仕様

- 仕様の自然言語版: [docs/format-spec.md](../docs/format-spec.md)
- 用語集: [docs/glossary.md](../docs/glossary.md)
- 参照実装: [examples/keihou/keihou-article-36.md](../examples/keihou/keihou-article-36.md)

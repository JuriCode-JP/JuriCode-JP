# schema/ — JSON Schema for JuriCode-JP

このフォルダには法令データの**構造検証用 JSON Schema** を置く。

すべて [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12) に準拠する。

## ファイル一覧

| Schema | 用途 | 出所 |
|---|---|---|
| [**juricode-article.schema.json**](./juricode-article.schema.json) | **条文 IR (Pydantic) の canonical schema (v0.1〜)** | **自動生成** ([export-schema.py](../tools/shared/scripts/export-schema.py)) |
| [law-frontmatter.schema.json](./law-frontmatter.schema.json) | YAML frontmatter のみの初期検証 (v0.0、参考) | 手書き |
| [article.schema.json](./article.schema.json) | 条文全体の初期設計 (v0.0、参考) | 手書き |
| [case-link.schema.json](./case-link.schema.json) | 判例リンク 1 件分の初期設計 (v0.0、参考) | 手書き |

### v0.0 (手書き) と v0.1 (IR 派生) の関係

- `juricode-article.schema.json` は Pydantic IR (`tools/shared/src/juricode_shared/ir.py`) から自動生成される **canonical な spec**。スキーマ変更は IR を編集して再生成 (`python tools/shared/scripts/export-schema.py`)。
- 残りの 3 ファイル (`law-frontmatter` / `article` / `case-link`) は 2026-05-14 初期設計時の手書き版。**v1.0 までに IR と統合・廃止予定**。当面は参考資料として残置。
- 機械検証は v0.1 以降は `juricode-article.schema.json` を使用すること。

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

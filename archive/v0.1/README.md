# JuriCode-JP v0.1 corpus (deprecated)

このディレクトリは **2026-05-25 に deprecate された v0.1 corpus** を保管しています。

## なぜ deprecate されたか

`business/v02-corpus-quality-investigation-2026-05-25.md` で実地調査の結果、v0.1 corpus には以下の構造的問題があると判明:

1. **`has_proviso` / `has_items` が全件 false (parser バグ)**: `tools/parse/parse-egov.py` の `_emit_article` が frontmatter にハードコードで `False` を設定していた。`ただし、` / `次に掲げる` 等の検出ロジックを通していない。
2. **各号 (Item) content が .md 本体から欠落**: 柱書 (hashira) のみが .md body に書かれ、各号本文は失われていた。検索 query で号情報を必要とすると recall が落ちる構造。

詳細は `business/data-quality-finding-2026-05-22.md` (2026-05-22 発見) を参照。

## v0.2 corpus との関係

- v0.2 corpus は `data/v0.2/` に配置済 (本ディレクトリと同じ 11,758 条 / 43 法令)
- v0.2 では `has_proviso` / `has_items` が正しく検出済 (`segment_parser.py` が body から判定)
- 各号 content は `build/chunks/{law}/{law}-article-{N}.chunks.jsonl` に補完済 (Option A 設計: 1 条 = 1 file 維持 + retrieval 用 chunks 別途生成)

## このディレクトリの扱い

- 履歴保全のため git に残すが、CI の verify / validate は対象外
- 復元が必要な場合は `git log archive/v0.1/` で history を辿る
- v0.3 以降の機能追加 (柱 1 Reranker fine-tune、柱 2 L4 prompt layer 等) は **v0.2 corpus のみ**を対象とする

## 関連

- `business/v02-corpus-quality-investigation-2026-05-25.md` — 本 deprecate の実行プラン
- `business/data-quality-finding-2026-05-22.md` — v0.1 構造問題の発見
- `business/file-unit-decision-aid-2026-05-22.md` — Option A 設計の決定
- `tools/parse/parse-egov.py` — v0.1 parser (本 deprecate の原因となった parser)
- `tools/parse/v0.2/segment_parser.py` — v0.2 parser (有効な parser)
- `tools/parse/v0.2/manifest/` — v0.2 corpus 用 manifest 生成パッケージ (2026-05-25 新設)

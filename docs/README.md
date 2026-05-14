# docs/ — プロジェクト方針・仕様文書

このフォルダにはJuriCode-JPの**方針・仕様・参考情報**を置く。実データは `data/`、コードは `tools/` を参照。

## 文書一覧

| ファイル | 内容 |
|---|---|
| [format-spec.md](./format-spec.md) | ★ 法令データフォーマットの正式仕様 |
| [strategy.md](./strategy.md) | 段階戦略(Phase 1〜3)とマイルストーン |
| [differentiation.md](./differentiation.md) | 先行OSSとの差別化と関係 |
| [glossary.md](./glossary.md) | 法令略称・専門用語の日英対訳辞書 |

## 文書追加時のルール

- 方針や仕様の変更は必ずこのフォルダの該当ファイルを更新する(コードのコメントだけに留めない)
- 文書はMarkdownのみ。図はMermaidまたは`assets/`に画像を置く
- 文書本文の改訂は Conventional Commits の `docs:` スコープでコミット

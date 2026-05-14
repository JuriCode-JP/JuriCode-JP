# data/ — 構造化済み法令データ(本体)

このフォルダにはJuriCode-JPで構造化された**法令データ本体**を置く。

## 構成

```
data/
├── phase1-police/         # Phase 1: 警察関連法令(2026-2027)
├── phase2-civil-commercial/   # Phase 2: 民事・商事法令(2027-2028、未着手)
└── phase3-all/            # Phase 3: 全領域(2028-2030、未着手)
```

各Phaseディレクトリは段階ごとの対象法令を含み、その下に法令ごとのディレクトリを配置する。

```
phase1-police/
├── keihou/                # 刑法
│   ├── README.md
│   ├── _meta.yaml         # 法令全体メタデータ(任意)
│   ├── keihou-article-1.md
│   ├── keihou-article-36.md
│   └── ...
├── keiji-soshou-hou/      # 刑事訴訟法
├── keisatsu-hou/          # 警察法
└── keisatsukan-shokumu-shikkou-hou/  # 警察官職務執行法
```

## ファイル仕様

法令データの記法は [docs/format-spec.md](../docs/format-spec.md) を必読。

- 1条文=1ファイル
- ファイル名: `[law-abbrev]-article-[N].md`
- YAML frontmatter + Markdown本文(日本語原文 + 英訳 + 判例リンク + 改正履歴 + 注記)

## サンプル

検証可能な参照実装は [examples/keihou/keihou-article-36.md](../examples/keihou/keihou-article-36.md)(刑法第36条 正当防衛)を参照。

## 追加ワークフロー

1. 対象法令のローマ字略称が [docs/glossary.md](../docs/glossary.md) に登録されているか確認(なければ追加PR)
2. 法令ディレクトリを作成、`README.md` と `_meta.yaml` を配置
3. 条文ごとに `.md` ファイルを追加(1コミット1〜数条程度)
4. `python tools/validate/validate-file.py [path]` で検証(将来)
5. PRレビューを経て `main` にマージ

## ライセンス

- 法令本文はパブリックドメイン(著作権法第13条)
- 構造化レイヤーは MIT ライセンス
- 詳細は各ファイルの frontmatter `license` フィールド参照

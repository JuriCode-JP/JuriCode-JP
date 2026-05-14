# tools/translate — 英訳補助ツール

法令本文の英訳を補助する。**完全自動翻訳は目的ではなく**、政府公定訳の取り込みと、公定訳のない条文へのドラフト訳生成が主用途。

## 翻訳ソースの優先順位

1. **政府公定訳**(日本法令外国語訳データベース / JLT-DB)
   - URL: http://www.japaneselawtranslation.go.jp/
   - `translation_status: official` を立てる
2. **コミュニティ翻訳**(レビュー済)
   - `translation_status: community` を立てる
3. **AIドラフト訳**(Claude API等)
   - `translation_status: draft` + `machine_translated: true` を立てる
   - 必ず人間レビュー前提

## 想定構成

```
translate/
├── README.md
├── fetch-jlt/         # 日本法令外国語訳DBから取得
├── draft-claude/      # Claude APIでドラフト訳生成
└── compare/           # 既存訳との差分比較
```

## CLI ユースケース(想定)

```bash
# JLT-DBから刑法第36条の公定訳を取得
python tools/translate/fetch-jlt.py --law-id 140AC0000000045 --article 36

# Claude APIでドラフト訳を生成(公定訳のない条文用)
python tools/translate/draft-claude.py --input data/phase1-police/keihou/keihou-article-200.md

# 既存ファイルの英訳を更新(in-place、要確認モード)
python tools/translate/update-translation.py --file [path] --source jlt
```

## ポリシー

- AIドラフト訳を作成した場合は、**必ず** `translation_status: draft` と `machine_translated: true` を立てる
- 公定訳が後日提供された場合は、ドラフト訳を公定訳で上書きし、`translation_status: official` に変更
- 英訳のみを変更するPRは `data([law]/[N]): update translation` とコミットメッセージを区別する

## 実装ステータス

**未着手**(2026-05-14時点)。Phase 1の主要条文に公定訳がない場合に着手。

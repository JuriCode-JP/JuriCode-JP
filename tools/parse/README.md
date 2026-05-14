# tools/parse — XML → JuriCode-JP 形式変換

e-Gov XML(または Lawtext)から JuriCode-JP の Markdown + YAML frontmatter 形式に変換する。

## 設計方針

- **既存OSSを最優先で活用**: [`ja-law-parser`](https://github.com/takuyaa/ja-law-parser) をXMLパースに使用する想定。独自実装は最後の手段。
- **入力フォーマット**: e-Gov 法令API のXML(Lawtext 形式も将来対応)
- **出力フォーマット**: `docs/format-spec.md` で定義する Markdown + YAML frontmatter
- **冪等性**: 同じ入力から常に同じ出力を生成する(差分ノイズを避けるため)

## 処理フロー(想定)

```
[e-Gov XML]
     │
     ▼
[ja-law-parser]
     │
     ▼
[中間オブジェクト(条・項・号)]
     │
     ▼
[JuriCode-JP transformer]
     │
     ├──► [frontmatter生成(law_id, version_date, source_url等)]
     │
     ├──► [原文Markdown生成]
     │
     ├──► [英訳取り込み(JLT-DBから別途取得)]
     │
     └──► [判例リンク・改正履歴のplaceholder生成(後で手動補完)]
     │
     ▼
[.md ファイル出力]
```

## CLI ユースケース(想定)

```bash
# 単一条文を変換
python -m juricode_parse \
  --law-id 140AC0000000045 \
  --article 36 \
  --output data/phase1-police/keihou/keihou-article-36.md

# 法令全体を一括変換
python -m juricode_parse --law-id 140AC0000000045 --all
```

## 実装ステータス

**未着手**(2026-05-14時点)。`fetch-egov` の次に着手予定。

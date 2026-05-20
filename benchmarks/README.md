# JuriCode-JP Benchmarks

JuriCode-JP の RAG retrieval 精度を定量評価する公開ベンチマーク。

## 比較対象

| 軸 | 対象 |
|---|---|
| データセット A (baseline) | e-Gov 生 XML / Markdown(法令まるごと 1 ファイル) |
| データセット B (本プロジェクト) | JuriCode-JP NDJSON(1 条 1 チャンク + 31 フィールド) |
| **比較目的** | 「LLM 最適化された前処理」が retrieval 精度をどれだけ改善するかを定量的に示す |

**重要**: 本ベンチマークは「**e-Gov 生 XML ベース vs JuriCode-JP 構造化ベース**」の **データ前処理品質**を比較するものです。源内 (Lawsy-Custom-BQ) や他の特定実装と直接対決する意図はありません。源内はむしろ JuriCode-JP の上流データを利用する **ダウンストリーム**として位置付けています。

## 評価方法

1. **評価セット**: [`../data/eval-set/`](../data/eval-set/) の Q&A エントリ (30 件想定)
2. **embedding モデル**: 複数モデルでマトリクス評価
   - OpenAI `text-embedding-3-small`
   - HuggingFace `intfloat/multilingual-e5-large`
   - HuggingFace `pkshatech/GLuCoSE-base-ja`
3. **retrieval**: ベクトル類似度 (cosine) で top-K 抽出
4. **メトリクス**: Recall@1, Recall@3, Recall@10, MRR, nDCG (詳細は [methodology.md](./methodology.md))

## 結果ファイル

`results/` ディレクトリに JSON 形式で時系列保存:

```
results/
├── YYYY-MM-DD-baseline.json          (e-Gov 生データのみ)
├── YYYY-MM-DD-juricode-with-cases.json  (判例リンク追加後)
└── YYYY-MM-DD-juricode-full.json     (全機能 ON)
```

各結果ファイルの schema:

```jsonc
{
  "run_id": "2026-05-25-baseline-openai-3small",
  "date": "2026-05-25",
  "dataset_a": "egov-raw-xml-snapshot-2026-05-20",
  "dataset_b": "juricode-jp@e09b258",
  "embedding_model": "text-embedding-3-small",
  "eval_set_version": "v0.1 (8 samples)",
  "metrics": {
    "dataset_a": {
      "recall_at_1": 0.0,
      "recall_at_3": 0.0,
      "recall_at_10": 0.0,
      "mrr": 0.0,
      "ndcg_at_10": 0.0
    },
    "dataset_b": {
      "recall_at_1": 0.0,
      "recall_at_3": 0.0,
      "recall_at_10": 0.0,
      "mrr": 0.0,
      "ndcg_at_10": 0.0
    }
  },
  "per_question_results": [
    { "question_id": "eval-police-001", "rank_in_a": null, "rank_in_b": null },
    ...
  ],
  "notes": "ベンチマーク実行時の設定、特記事項"
}
```

## 公開原則

- **再現性**: コミットハッシュ・モデル名・評価セットバージョンを明記
- **継続性**: 改善履歴が時系列で見える(過去結果は削除せず追加)
- **誠実性**: 結果が悪かった場合も削除せず公開し、改善の根拠とする

## 関連リソース

- 評価セット: [`../data/eval-set/`](../data/eval-set/)
- embedding 生成: [`../tools/embed/`](../tools/embed/)
- データ本体: [`../data/`](../data/)

---

*作成: 2026-05-20 / MIT License / 株式会社CHOKAI*

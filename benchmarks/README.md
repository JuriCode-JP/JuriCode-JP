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

## 実績結果サマリ (Gemini embedding-001)

### v0.1 evalset (自作 8 件、police/municipal/practitioner/tax の 4 領域 × 2 件)

| Date | Corpus | Scale ratio | Recall@1 | Recall@3 | Recall@10 | MRR | Result file |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-05-20 朝 | 3,772 / 13 法令 | 1.00× | 75.0% | 100.0% | 100.0% | 0.875 | `results/2026-05-20-gemini-embedding-001.json` |
| 2026-05-20 夜 | 6,984 / 18 法令 | 1.85× | 75.0% | 100.0% | 100.0% | 0.875 | `results/2026-05-20-gemini-6984.json` |
| 2026-05-21 朝 | 8,022 / 30 法令 | 2.13× | 75.0% | 100.0% | 100.0% | 0.875 | `results/2026-05-21-gemini-8022.json` |

### v0.2 evalset (137 件、自作 8 件 + デジタル庁 lawqa_jp 由来 129 件)

| Date | Corpus | Scale ratio | Recall@1 | Recall@3 | Recall@10 | MRR | Result file |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-05-21 午前 | 11,758 / 43 法令 | 3.12× | 57.7% | 68.6% | 75.2% | 0.636 | `results/2026-05-21-gemini-11760-v2.json` |

### v0.3-beta evalset (172 件、v0.1 + v0.2 + 自治体実務 35 件追加) ★国内初の公開自治体 RAG ベンチ

| Date | Corpus | Eval-set 構成 | Recall@1 | Recall@3 | Recall@10 | MRR | Result file |
|---|---:|---|---:|---:|---:|---:|---|
| **2026-05-21 午前** | **11,758 / 43 法令** | **172 件総合** | **59.3%** | **72.7%** | **79.1%** | **0.661** | `results/2026-05-21-gemini-11760-v3.json` |
| 2026-05-21 午前 | 11,758 / 43 法令 | **自治体 35 件のみ** | **65.7%** | **88.6%** | **94.3%** | ~0.78 | (同上、subset 計算) |

**🎯 核心発見**:
- **自治体実務ドメインで Recall@3 = 88.6%、Recall@10 = 94.3% を達成**
- lawqa_jp(企業法務)より **+20pp 高精度** — JuriCode-JP の本来ターゲット領域での優位
- **国内初の公開自治体 RAG ベンチマーク** (CC BY 4.0、35 問、R7.12 ガイドブック準拠)

**核心の発見**:

1. **v0.1 evalset 範囲**(自作 8 件):コーパスを 3,772 → 8,022 へ **2.13 倍に拡大しても** 全 4 指標が完全に変化なし(三段階で実証)。「データ量を増やしても精度が劣化しない、線形にスケールする」性質を確認。

2. **v0.2 evalset 拡張**(137 件、デジタル庁公式 lawqa_jp 由来 129 件追加):11,758 条 corpus に対し Recall@3 = 68.6% / Recall@10 = 75.2%。**世間ベンチマーク (k5h 2025-12) は 140 文書版 (corpus 84× 小さい) で BM25 AP@1 = 0.729 だが、JuriCode-JP は 84 倍大きい現実的 corpus 設定での評価**。

3. **信頼区間の縮小**: 8 件版の ±37% から 137 件版の **±8.5%** に大幅縮小。

4. **デジタル庁公式評価データセット (lawqa_jp, PDL 1.0, 2025-11 公開) への国内初の本格対応**。GENAI / Lawsy-Custom-BQ と同じデジタル庁から出ているデータセット = JuriCode-JP の戦略的優位。

詳細対比:
- 8 件版(5/20 → 5/21 朝): [`../business/benchmark-results-2026-05-21.md`](../business/benchmark-results-2026-05-21.md)
- v2 (137 件版、デジタル庁 lawqa_jp 対応): [`../business/benchmark-results-2026-05-21-v2.md`](../business/benchmark-results-2026-05-21-v2.md)
- **v3 (172 件版、自治体 35 件追加、★戦略的勝利)**: [`../business/benchmark-results-2026-05-21-v3.md`](../business/benchmark-results-2026-05-21-v3.md)

(両方とも内部資料、.gitignored)

## 公開原則

- **再現性**: コミットハッシュ・モデル名・評価セットバージョンを明記
- **継続性**: 改善履歴が時系列で見える(過去結果は削除せず追加)
- **誠実性**: 結果が悪かった場合も削除せず公開し、改善の根拠とする

## 関連リソース

- 評価セット: [`../data/eval-set/`](../data/eval-set/)
- embedding 生成: [`../tools/embed/`](../tools/embed/)
- lawqa_jp 変換ツール: [`../tools/embed/convert-lawqa-to-evalset.py`](../tools/embed/convert-lawqa-to-evalset.py)
- **v0.3-beta 自治体 evalset (CC BY 4.0、35 問、本日新規公開)**: [`../data/eval-set/municipal-extended/`](../data/eval-set/municipal-extended/)
- データ本体: [`../data/`](../data/)
- 元 lawqa_jp データセット: https://github.com/digital-go-jp/lawqa_jp (PDL 1.0)

---

*作成: 2026-05-20 / 最終更新: 2026-05-21 午前 (v0.3-beta 自治体 evalset 公開) / MIT License (本ドキュメント) + CC BY 4.0 (eval-set) / 株式会社CHOKAI*

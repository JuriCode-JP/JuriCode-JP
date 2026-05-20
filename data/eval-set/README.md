# JuriCode-JP RAG Evaluation Set

JuriCode-JP の **retrieval 精度を定量的に評価するためのオープンデータセット**です。

JuriCode-JP は「日本の法令を AI/LLM 時代に最適化された構造化データとして整備する」プロジェクトですが、構造化したデータが**実際に RAG で動くか**を独立に検証できる仕組みは、データ整備自体と同じくらい重要です。

本ディレクトリは MIT で公開され、誰でも以下が可能になります:

- 自分の embedding モデルで JuriCode-JP を retrieval テストする
- 別の法令データセットとの比較ベンチマークに使う
- 自分の RAG パイプラインの精度監視に使う
- 質問サンプルを参考に、独自の評価セットを構築する

---

## ファイル構成

| ファイル | カテゴリ | 想定件数 |
|---|---|---|
| `police.jsonl` | 警察関連法令(刑法・刑訴法・警察法・警職法) | 10 件 |
| `municipal.jsonl` | 自治体関連(地方自治法・行政手続法・行政不服審査法) | 10 件 |
| `practitioner.jsonl` | 民法 | 5 件 |
| `tax.jsonl` | 税法(国税通則法・法人税法・所得税法・消費税法) | 5 件 |
| **合計** | | **30 件** |

(初期版はサンプル 8 件で公開。30 件への拡張は進行中。)

---

## レコード形式 (JSON Lines)

各行が 1 つの質問エントリです。

```jsonc
{
  "id": "eval-police-001",
  "category": "police",
  "question": "正当防衛が成立する要件は何か?",
  "expected_article_ids": ["keihou-art-36"],
  "relevance": "high",
  "difficulty": "easy",
  "topic_tags": ["正当防衛", "違法性阻却事由", "刑法総則"],
  "notes": "刑法 36 条 1 項が直接該当。条文選定の典型例。"
}
```

### フィールド定義

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | ✅ | 一意 ID。`eval-<category>-<NNN>` 形式 |
| `category` | string | ✅ | `police` / `municipal` / `practitioner` / `tax` |
| `question` | string | ✅ | 公益的な疑問形式の質問文(個別事案ではなく一般論) |
| `expected_article_ids` | string[] | ✅ | 想定される回答に含まれるべき条文の `article_id` 配列。1〜3 件想定 |
| `relevance` | string | ✅ | `high` (核心条文) / `medium` (関連条文) / `low` (背景情報) |
| `difficulty` | string | ✅ | `easy` (条文名直結) / `medium` (用語の言い換え必要) / `hard` (複数条文の合成解釈) |
| `topic_tags` | string[] | 任意 | 質問のテーマを示すタグ(検索 facet 用) |
| `notes` | string | 任意 | 評価作成者によるメモ(なぜこの条文が正解か、別の解釈の可能性、等) |

---

## 評価メトリクス (推奨)

### Recall@K
正解条文(`expected_article_ids` 内)が、retrieval 結果の上位 K 件に含まれる割合

- **Recall@1**: 厳しい。上位 1 件が正解と一致する比率
- **Recall@3**: 実用的な基準。上位 3 件以内に正解が含まれる比率
- **Recall@10**: ベースライン。広く取った時の精度

### MRR (Mean Reciprocal Rank)
正解条文の最初のヒット順位の逆数の平均。順位を考慮した精度指標。

### nDCG (Normalized Discounted Cumulative Gain)
relevance ("high" / "medium" / "low") を重み付けして評価する場合に使用。

---

## 公開原則

1. **個別事案 / 実物データを含めない**: 質問はすべて「公益的疑問」レベルに保つ(✅「正当防衛の要件は?」 ❌「特定事件で正当防衛が認められるか?」)
2. **専門家レビューを経た品質**: 法学的に妥当な質問・正解条文選定とする
3. **透明な更新履歴**: 質問の追加・修正は git commit で追跡可能
4. **多様性**: 警察 + 自治体 + 民法 + 税法 の四本柱をバランスよくカバー

---

## 質問追加のガイドライン

新規エントリを追加するときは:

1. **質問の文体**: 「〜とは?」「〜の要件は?」「〜の手続きは?」など、一般論を問う形
2. **`expected_article_ids`**: 必ず存在する `article_id` を指定(`data/phase1-*/` で grep して確認)
3. **`relevance` の判断基準**:
   - `high`: その条文を見せずに回答することが困難
   - `medium`: その条文を見せると回答の質が上がる
   - `low`: 関連はあるが必須ではない
4. **`difficulty`**: retrieval モデルが見つけにくい質問ほど `hard`

---

## 関連リソース

- データ本体: [`../phase1-*/`](../) (全 3,772 条)
- RAG 出力ツール: [`../../tools/export/lawsy-bq/`](../../tools/export/lawsy-bq/)
- embedding 生成: [`../../tools/embed/`](../../tools/embed/) (整備中)
- ベンチマーク結果: [`../../benchmarks/`](../../benchmarks/) (整備中)

---

*作成: 2026-05-20 / MIT License / 株式会社CHOKAI*

# JuriCode-JP Benchmark Methodology

## 評価メトリクスの定義

### Recall@K

正解条文(`expected_article_ids` 内のいずれか)が、retrieval 結果の上位 K 件に含まれる割合。

```
Recall@K = (上位 K 件に正解条文を 1 件以上含む質問の数) / (全質問数)
```

| K | 解釈 |
|---|---|
| Recall@1 | 単一ベストヒット精度。LLM 入力に 1 件しか入れない用途で重要 |
| Recall@3 | 実用的バランス。LLM プロンプトに 3 条文同梱する場合 |
| Recall@10 | 広く取った recall。再ランキングの前処理として |

### MRR (Mean Reciprocal Rank)

正解条文が最初にヒットする順位の逆数の平均。

```
MRR = (1/N) * Σ (1 / rank_i)
```

- rank_i: 質問 i における最初の正解条文の順位 (1 から始まる)
- 正解が見つからない場合は 0

### nDCG@K (Normalized Discounted Cumulative Gain)

relevance ("high" / "medium" / "low") を考慮した順位精度。

```
gain(r) = { 3 if r=="high", 2 if r=="medium", 1 if r=="low", 0 otherwise }
DCG@K   = Σ gain(r_i) / log2(i + 1)   for i in 1..K
nDCG@K  = DCG@K / iDCG@K              (iDCG = 理想順序での DCG)
```

## 実験プロトコル

### Step 1: データ準備

1. **データセット A (baseline)**: e-Gov 法令 API から取得した XML を Markdown 化(1 法令 = 1 ファイル)
2. **データセット B (JuriCode-JP)**: 本リポジトリの `data/phase1-*/` 全条文を `tools/export/lawsy-bq/export-jsonl.py` で NDJSON 化

### Step 2: Embedding 生成

両データセットに対して同一 embedding モデルでベクトル化。

```bash
python tools/embed/embed.py \
    --input build/dataset-a.jsonl \
    --output build/dataset-a-embedded.jsonl \
    --model text-embedding-3-small

python tools/embed/embed.py \
    --input build/dataset-b.jsonl \
    --output build/dataset-b-embedded.jsonl \
    --model text-embedding-3-small
```

### Step 3: Retrieval 実行

各評価セットの質問に対して、両データセットで top-K 取得:

```bash
python tools/embed/retrieve.py \
    --embeddings build/dataset-a-embedded.jsonl \
    --queries data/eval-set/*.jsonl \
    --model text-embedding-3-small \
    --top-k 10 \
    --output build/results-a.json

python tools/embed/retrieve.py \
    --embeddings build/dataset-b-embedded.jsonl \
    --queries data/eval-set/*.jsonl \
    --model text-embedding-3-small \
    --top-k 10 \
    --output build/results-b.json
```

### Step 4: メトリクス計算

```bash
python tools/embed/evaluate.py \
    --results-a build/results-a.json \
    --results-b build/results-b.json \
    --eval-set data/eval-set/ \
    --output benchmarks/results/2026-MM-DD-<run-id>.json
```

## 公平性の担保

- **同一 embedding モデル**で両側を生成
- **同一クエリセット**で両側を retrieve
- **同一メトリクス計算**コードで両側を評価
- **データセット A の前処理は最小限**(XML → text のみ、改変なし)で「素の e-Gov」を表現

## 既知の制約

1. **質問の網羅性**: 初期 30 件は典型例に偏る。実用ワークロードの分布とは異なる可能性
2. **embedding モデルバイアス**: モデルが法令文体に最適化されていない可能性
3. **正解条文の主観性**: `expected_article_ids` の選定に評価作成者の解釈が入る
4. **チャンクサイズ差**: データセット A (法令まるごと) vs データセット B (1 条) でチャンク粒度が大きく異なり、これ自体が結果に影響

これらの制約は `notes` フィールドや個別 README で明示します。

## 改善の優先順位

ベンチマーク結果に応じて、以下の順で改善を検討:

1. **データセット B の Recall@3 が高ければ** → JuriCode-JP の基本前処理が正しい証拠
2. **Recall@1 を上げるには** → 長文条文の sub-chunking、re-ranking 導入
3. **MRR を上げるには** → 章節・判例メタデータを retrieval にも反映
4. **モデル横断で差が小さければ** → データセット品質が retrieval を律速している証拠

---

*作成: 2026-05-20 / MIT License*

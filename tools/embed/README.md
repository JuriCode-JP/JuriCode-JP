# tools/embed/ — Embedding Generation Pipeline

JuriCode-JP の法令データを embedding 化し、RAG retrieval で使える形にするツール群です。

## 目的

`tools/export/lawsy-bq/` が生成する 31 フィールドの NDJSON レコード(条文テキスト + メタデータ)に対して、**文字列ベクトル (embedding)** を付与し、ベクトル類似検索による retrieval を可能にします。

```
data/phase1-*/<law>/*.md      [JuriCode-JP Markdown]
        │
        ▼
tools/export/lawsy-bq/        [31 フィールド NDJSON]
        │  + 各レコードに text フィールド
        ▼
tools/embed/                  ← このディレクトリ
        │  + embedding ベクトルを各レコードに追加
        ▼
出力 (例: build/juricode-bq-with-embeddings.jsonl)
        │  各レコードに embedding: [0.123, -0.456, ...] が付与
        ▼
BigQuery Vector Search / FAISS / pgvector 等
```

## Retrieval 構成の推奨 (2026-05-31 ablation)

**現行パラメータ (BM25 char 2-3gram + RRF k=60) における推奨構成は dense-only** です。

ablation (2026-05-31, eval-set 172 queries):

| 構成 | R@1 | R@3 | R@10 |
|---|---|---|---|
| dense-only | 59.3% | **72.7%** | 79.1% |
| hybrid (BM25+dense RRF) | 39.0% | 57.6% | 76.2% |
| hybrid + reranker | 44.2% | 57.6% | 69.8% |

現行設定の hybrid は dense を劣化させ、cross-encoder reranker でも回復しません (R@3 は hybrid と同値、R@10 は悪化)。
このため `--hybrid-bm25` / `--reranker` は **既定オフ・実験的扱い** とします。

**FU-512 ablation (2026-05-31) で確定**: hybrid は全 RRF k (10〜200) で dense を下回り (最良 k=10 でも -10pt)、逐語型クエリでも悪化した。
よって **dense-only を正式既定**とする。BM25 char-ngram / RRF / 正規化の抜本是正による hybrid 再評価は FU-513 (正準テキスト正規化の集約) に委譲する。

## 設計方針

### 1. 複数モデル対応

embedding モデルは「正解」がないので、複数の選択肢を CLI フラグで切り替えられる設計とします:

| モデル | 次元 | 想定用途 |
|---|---|---|
| OpenAI `text-embedding-3-small` | 1536 | 軽量、コスト効率良い |
| OpenAI `text-embedding-3-large` | 3072 | 高精度、コスト高 |
| Cohere `embed-multilingual-v3.0` | 1024 | 日本語含む多言語 |
| `intfloat/multilingual-e5-large` (HF) | 1024 | OSS、ローカル実行可 |
| `pkshatech/GLuCoSE-base-ja` (HF) | 768 | 日本語特化 OSS |

### 2. 出力フォーマット

入力 NDJSON の各レコードに `embedding` と `embedding_model` フィールドを追加して出力:

```jsonc
{
  // 既存 31 フィールド
  "article_id": "minpou-art-90",
  "text": "公の秩序又は善良の風俗に反する...",
  ...
  // 新規追加
  "embedding": [0.123, -0.456, 0.789, ...],  // 数百-数千次元
  "embedding_model": "text-embedding-3-small",
  "embedding_generated_at": "2026-05-21T10:30:00Z"
}
```

### 3. 生成済みベクトルの配布

生成済みベクトルは**サイズが大きい**(3,772 条 × 1536 次元 × 8 byte ≈ 46 MB)ため、GitHub には含めず別途配布します:

| 配布チャネル | 対象 |
|---|---|
| Hugging Face Datasets (`JuriCode-JP/embeddings`) | 主要モデル(OpenAI 3-small, e5-large 等)の生成済みベクトル |
| GitHub Releases | バージョンタグ付きで rebrand リリース時に同梱 |
| ローカル生成 | 個別モデル / 機密用途は `tools/embed/` で利用者が再生成 |

### 4. 設定ファイル

```yaml
# tools/embed/configs/openai-small.yaml
model_provider: openai
model_name: text-embedding-3-small
input_field: text         # NDJSON のどのフィールドを embedding 対象にするか
batch_size: 100
rate_limit_rpm: 3000
output_dim: 1536
```

## 前処理: 本則 table chunks の生成 (FU-515, 必須 standard step)

`build-v0.2-corpus.py` は `build/chunks/` 配下の `*.chunks.jsonl` を `rglob` で自動収集しますが、**本則の `<TableStruct>` (税率表等) は別ステップで生成**する必要があります。corpus rebuild / 増分 embed の **前段**で必ず以下を実行してください (実行しないと地方税法312条 均等割税率表などが retrieval に乗りません)。

```bash
# 1. 本則 table chunks を生成 (既定 --data-dir data/v0.2, 出力 build/chunks/)
python tools/parse/v0.2/extract_table_from_xml.py
#    -> Main table chunks: 296 / SupplProviso: 1046 / no-XML: 0 が想定

# 2. (任意・cache/laws がある環境のみ) 取りこぼし再発防止 parity
python tools/parse/v0.2/verify_table_parity.py
#    -> PARITY OK (article-level coverage + no-drop)

# 3. corpus を rebuild してから増分 embed
python tools/embed/build-v0.2-corpus.py
```

`build/chunks/` は `.gitignore` 対象のため CI には乗りません。`verify_table_parity.py` は `cache/laws` (gitignored) を要するので CI ステップではなく、**push 前ローカル CI 再現** (`python tools/scripts/run-ci.py`) の optional step として走ります (`cache/laws` 不在時は自動 SKIP)。

## 柱1-D ablation 起動コマンド (E1-E3', m5 実行用)

dense+rerank (BM25 除去) と HyDE の ablation を `retrieve.py` 単体で実行する。強 reranker (bge-v2-m3) は Windows CPU では非現実的 (15-20s/クエリ) なので **m5 MPS** で回す。本格 ablation 前に **MPS デバイス監査スモーク** (NotImplementedError/nan/silent CPU fallback の検知) を必ず通すこと。

| # | 構成 | コマンド要点 |
|---|---|---|
| baseline | dense-only (= 新 baseline) | フラグなし |
| E1 | dense → 強 rerank (hybrid off) | `--reranker --reranker-model BAAI/bge-reranker-v2-m3` (**`--hybrid-bm25` を付けない**) |
| E2 | dense → 軽量 rerank (hybrid off) | `--reranker --reranker-model <japanese-reranker-small>` |
| E3 | HyDE → dense | `--hyde-only --hyde-cache <path>` |
| E3' | HyDE + 原クエリ Late Fusion | `--hyde --hyde-fusion rrf --hyde-cache <path>` (または `--hyde-fusion minmax`) |

```bash
# baseline (dense-only / 新 baseline をロックする実測)
python tools/embed/retrieve.py --embedded <prefix> --eval-set data/eval-set/*.jsonl --top-k 10

# E1: クリーン dense 候補に強 rerank (--hybrid-bm25 を付けない = select_rerank_candidates(hybrid_on=False))
python tools/embed/retrieve.py --embedded <prefix> --eval-set data/eval-set/*.jsonl --top-k 10 \
    --reranker --reranker-corpus <corpus.jsonl> --reranker-model BAAI/bge-reranker-v2-m3 --reranker-candidates 30

# E3: HyDE 仮想文 dense のみ (trial 1 が cache を生成、trial 2/3 は ID 照合で再利用)
GEMINI_API_KEY=... python tools/embed/retrieve.py --embedded <prefix> --eval-set data/eval-set/*.jsonl \
    --hyde-only --hyde-cache build/hyde-cache.jsonl --hyde-gen-model gemini-2.5-flash

# E3': HyDE + 原クエリ Late Fusion (RRF / 生スコア加算は不可)
GEMINI_API_KEY=... python tools/embed/retrieve.py --embedded <prefix> --eval-set data/eval-set/*.jsonl \
    --hyde --hyde-fusion rrf --hyde-cache build/hyde-cache.jsonl --hyde-gen-model gemini-2.5-flash
```

- **dense+rerank は新規コード不要**: `--reranker` を `--hybrid-bm25` なしで付けると `RetrievalPipeline.select_rerank_candidates(hybrid_on=False)` が **クリーンな dense top-N** をそのまま rerank に渡す (BM25 混入なし)。既存の `run-ablation.py` の `reranker` config がこれに相当。
- **HyDE の融合は RRF / Min-Max 正規化のみ** (`hyde.rrf_fuse` / `hyde.min_max_fuse`)。生スコア加算・embedding 加算は禁止 (レンジ差で片方がサイレント抹殺される)。仮想文キャッシュは `query_hash` 照合で trial 跨ぎ再利用・欠落は fail-loud。
- **per-domain 内訳**は eval-set ファイルを 1 本ずつ渡して実行する (各 `data/eval-set/*.jsonl` が 1 ドメイン)。**warm 定常 p95 / HyDE 誤誘導テール**の計測は m5 の cluster harness 側で行う (retrieve.py は R@1/3/5/10/20 + MRR を出力)。

## 実装スケジュール (予定)

| ステップ | 内容 | 状態 |
|---|---|---|
| 1 | README (本ファイル) | ✅ |
| 2 | CLI スケルトン (`embed.py`) | 未着手 |
| 3 | OpenAI provider 実装 | 未着手 |
| 4 | HuggingFace provider 実装 | 未着手 |
| 5 | バッチ処理 + retry | 未着手 |
| 6 | 評価セット (`data/eval-set/`) との連携テスト | 未着手 |
| 7 | benchmarks/ 結果出力 | 未着手 |

## 関連ファイル

- 評価セット: [`../../data/eval-set/`](../../data/eval-set/)
- ベンチマーク結果: [`../../benchmarks/`](../../benchmarks/)
- 上流 NDJSON 生成: [`../export/lawsy-bq/`](../export/lawsy-bq/)

---

*作成: 2026-05-20 / MIT License / 株式会社CHOKAI*

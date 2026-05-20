# Embedding Providers — JuriCode-JP RAG パイプライン

`tools/embed/embed.py` と `tools/embed/retrieve.py` は **複数の embedding provider** を切り替えられるよう設計されています。

| Provider | フラグ | API key | コスト | 想定用途 |
|---|---|---|---|---|
| `tfidf` (default) | `--provider tfidf` | 不要 | 無料 | 開発・ベースライン |
| `openai` | `--provider openai` | `OPENAI_API_KEY` | 約 $0.02 (6,984 条) | 本番・NLnet ベンチマーク |

将来追加予定:
- `huggingface-e5` (multilingual-e5-large、OSS、ローカル GPU 推奨)
- `huggingface-glucose` (pkshatech/GLuCoSE-base-ja、日本語特化)
- `cohere` (Cohere embed-multilingual-v3)

---

## 1. TF-IDF (default)

オフラインで動く文字 n-gram ベースライン。API key 不要。

```bash
python tools/embed/embed.py \
    --input build/juricode-bq-article.jsonl \
    --output build/juricode-bq-embedded-tfidf

python tools/embed/retrieve.py \
    --embedded build/juricode-bq-embedded-tfidf \
    --eval-set data/eval-set/*.jsonl \
    --top-k 10 --show-per-query
```

**期待結果**: Recall@10 = 0% (2026-05-20 計測値、評価セット v0.1)。
意味的ギャップを越えられないため、実用には不向き。**ベースラインとして数字を残す目的のみ**。

---

## 2. OpenAI text-embedding-3-small (推奨)

OpenAI の埋め込み API。多言語 (日本語含む) 対応、コストが極めて安い。

### 2.1 事前準備

#### (a) OpenAI API key を取得

1. https://platform.openai.com/ にログイン (アカウント作成)
2. 右上のアカウントメニュー → **API keys** → **+ Create new secret key**
3. 名前を `juricode-jp-embed` 等で作成 → 表示された `sk-...` をコピー
4. **このキーは一度しか表示されないので、安全な場所に保存**

#### (b) クレジット課金設定

- 課金有効化が必要 (https://platform.openai.com/account/billing)
- $5 程度の入金で十分(本ベンチマークの消費は $0.02 オーダー)

### 2.2 環境変数設定

**WSL2 / Linux**:
```bash
export OPENAI_API_KEY="sk-...あなたのキー..."
# または永続化したい場合
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.bashrc
source ~/.bashrc
```

**Windows PowerShell** (セッションのみ):
```powershell
$env:OPENAI_API_KEY = "sk-...あなたのキー..."
```

**注意**: `OPENAI_API_KEY` は秘密情報です。**git に commit しない**、**スクリーンショットに含めない**、**人に共有しない**。

### 2.3 実行

```bash
# パッケージ追加 (初回のみ)
pip install openai
# または uv pip install openai

# 全 6,984 条で embedding 生成
python tools/embed/embed.py \
    --provider openai \
    --openai-model text-embedding-3-small \
    --input build/juricode-bq-article.jsonl \
    --output build/juricode-bq-embedded-openai-3small

# Retrieval テスト
python tools/embed/retrieve.py \
    --embedded build/juricode-bq-embedded-openai-3small \
    --eval-set data/eval-set/*.jsonl \
    --top-k 10 --show-per-query
```

### 2.4 コスト見積もり

| モデル | 単価 (per 1M tokens) | 6,984 条のコスト | 評価セット 30 件 | 合計 |
|---|---|---|---|---|
| `text-embedding-3-small` | $0.020 | 約 $0.02 | < $0.001 | **約 $0.02** |
| `text-embedding-3-large` | $0.130 | 約 $0.13 | < $0.001 | 約 $0.13 |

(token 数: 6,984 条 × 平均 255 tokens ≈ 178 万 tokens)

### 2.5 期待される改善

|  | TF-IDF | OpenAI 3-small (期待) |
|---|---|---|
| Recall@1 | 0% | 30-60% |
| Recall@3 | 0% | 50-80% |
| Recall@10 | 0% | 70-95% |

(法令データに対する経験則、実測は要確認)

### 2.6 トラブルシューティング

| エラー | 原因 / 対処 |
|---|---|
| `RateLimitError` | tier 1 では 3000 RPM / 1M TPM。バッチサイズを下げる `--openai-batch-size 50` |
| `AuthenticationError` | API key が無効 / 未設定。`echo $OPENAI_API_KEY` で確認 |
| `InsufficientQuotaError` | クレジット残高不足。Billing で入金 |
| `403 Country not supported` | API が利用不可な国。VPN ではなく Anthropic / Cohere を検討 |

---

## 3. Provider 比較ベンチマーク (推奨ワークフロー)

複数 provider を試して NLnet ベンチマークに反映:

```bash
# 1) TF-IDF (baseline)
python tools/embed/embed.py --provider tfidf \
    --input build/juricode-bq-article.jsonl \
    --output build/embedded-tfidf
python tools/embed/retrieve.py --embedded build/embedded-tfidf \
    --eval-set data/eval-set/*.jsonl --top-k 10 \
    > benchmarks/results/$(date +%Y-%m-%d)-tfidf.txt 2>&1

# 2) OpenAI 3-small
python tools/embed/embed.py --provider openai \
    --openai-model text-embedding-3-small \
    --input build/juricode-bq-article.jsonl \
    --output build/embedded-openai-3small
python tools/embed/retrieve.py --embedded build/embedded-openai-3small \
    --eval-set data/eval-set/*.jsonl --top-k 10 \
    > benchmarks/results/$(date +%Y-%m-%d)-openai-3small.txt 2>&1

# 3) OpenAI 3-large (オプション)
python tools/embed/embed.py --provider openai \
    --openai-model text-embedding-3-large \
    --input build/juricode-bq-article.jsonl \
    --output build/embedded-openai-3large
```

結果は `benchmarks/results/YYYY-MM-DD-<run-id>.json` 形式で記録します(手動編集または将来の自動化スクリプトで)。

---

## 4. 公開ポリシー再確認

| 要素 | 場所 | 公開 |
|---|---|---|
| embed.py / retrieve.py (コード) | `tools/embed/` | ✅ 公開 (MIT) |
| ベンチマーク結果 (JSON) | `benchmarks/results/` | ✅ 公開 |
| 評価セット | `data/eval-set/` | ✅ 公開 |
| 生成済み embedding ベクトル (.npy) | `build/` | ❌ git 非公開 (.gitignore)、HF Datasets で別配布検討 |
| OpenAI API key | 環境変数 | ❌ **絶対に commit しない** |

`.gitignore` に `build/` が含まれていることを確認してください:
```bash
grep -E "^build" .gitignore
```

---

*作成: 2026-05-20 / 株式会社CHOKAI*

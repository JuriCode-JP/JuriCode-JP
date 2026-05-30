# tools/search-ui — 検索 UI プロトタイプ

JuriCode-JP の embedding artefacts を使った最小構成のローカル検索 UI.
営業デモ / マネタイズ Step 1 (検索 UI プロトタイプ) を目的とする.

## 構成

```
tools/search-ui/
├── README.md
├── server.py     # Python stdlib http.server ベース (依存: numpy のみ + 任意で google-genai/openai)
└── index.html    # 1 ページの検索 UI
```

サーバは 1 ファイルで動き, retrieve.py が出力する artefacts (`.npy` + `.meta.jsonl` +
`.vec.pkl`) をロードしてコサイン類似度上位 K 件を返す.

## 必須前提

事前に `tools/embed/embed.py` で embedding を生成しておくこと.

```bash
# 例: TF-IDF
python tools/embed/embed.py \
    --input  build/juricode-bq-article.jsonl \
    --output build/juricode-bq-embedded \
    --provider tfidf

# 例: Gemini (推奨, Recall@3 = 100% 実証済)
GEMINI_API_KEY=xxx python tools/embed/embed.py \
    --input  build/juricode-bq-article.jsonl \
    --output build/juricode-bq-embedded \
    --provider gemini \
    --gemini-model gemini-embedding-001
```

## 起動

```bash
cd JuriCode-JP

# TF-IDF artefacts を使う場合は API キー不要
python tools/search-ui/server.py --embedded build/juricode-bq-embedded

# Gemini artefacts を使う場合 (クエリ encode で API を呼ぶ)
GEMINI_API_KEY=xxx python tools/search-ui/server.py \
    --embedded build/juricode-bq-embedded

# OpenAI artefacts を使う場合
OPENAI_API_KEY=xxx python tools/search-ui/server.py \
    --embedded build/juricode-bq-embedded
```

ブラウザで `http://localhost:8765/` を開く. ポート変更は `--port`.

## 提供エンドポイント

| パス | 内容 |
|---|---|
| `GET /` | 検索 UI (index.html) |
| `GET /api/info` | provider / model / 次元 / コーパス件数を返す |
| `GET /api/search?q=<質問>&k=10` | top-K のヒット条文を JSON で返す |

`/api/search` レスポンス例:

```json
{
  "query": "正当防衛が成立する要件は何か?",
  "k": 10,
  "results": [
    {
      "rank": 1,
      "score": 0.873,
      "article_id": "keihou-art-36",
      "law_name_ja": "刑法",
      "law_id": "140AC0000000045",
      "article_number": "36",
      "phase_category": "phase1-police",
      "hen_name_ja": "第一編　総則",
      "shou_name_ja": "第七章　犯罪の不成立及び刑の減免",
      "source_url": "https://laws.e-gov.go.jp/law/140AC0000000045"
    }
  ]
}
```

## 制約 / 既知事項

- 認証なし. ローカルデモ専用. `--host 0.0.0.0` で公開する場合は必ず別途認証を挟むこと.
- ローカル `127.0.0.1` バインドが default. 検索結果はキャッシュしない (no-store).
- artefacts は起動時に全部メモリにロードする (3,772 条 / Gemini 3072 次元で約 46 MB).
- 検索結果は条文の **メタデータのみ** 返す. 本文は別途 `data/` 配下の Markdown を参照.

## ロードマップ

| 項目 | 状態 |
|---|---|
| top-K 検索 | ✓ MVP |
| 条文本文プレビュー | ☐ 次回 (data/ からファイル読み出し) |
| 判例リンク表示 | ☐ A 計画 (判例リンク追加) と連動 |
| ハイブリッド検索 (TF-IDF + Gemini) | ☐ |
| 認証 / レートリミット | ☐ Hosted ティア化のときに |
| Pro ティア向け Multi-tenancy | ☐ Phase 2 |

## 質問ログ (v0.3 柱5)

検索 UI は PoC 利用時に 4 原材料 (質問文 / 👍👎 feedback / クリックした条文 / 滞在時間) を
SQLite (`build/search-ui-logs.db`, gitignore 対象) に記録し、柱1 reranker fine-tune の学習データ
基盤 (data moat) を作る.

- **API**: `POST /api/question` (検索 + 記録、question_id 返却) / `POST /api/feedback`
  (👍👎、per-question) / `POST /api/click` (clicked rank + article_id + dwell) / `GET /api/health`.
- **起動**: `python tools/search-ui/server.py --embedded build/juricode-bq-embedded --corpus-version v0.2 --port 8765`.
  `--corpus-version` 必須、`--log-db` で DB パス変更可.
- **PII**: ingest 時に Tier 1 正規表現で PII (email / 電話 / 郵便番号 / カード / マイナンバー / URL) を
  検出. 検出時は質問文 raw を保存せず匿名化版 + 検出パターン名のみ記録. 既存行の匿名化列は
  `python tools/search-ui/anonymize-batch.py --db build/search-ui-logs.db --dry-run|--apply` で後追い fill.
- **セキュリティ (重要)**: 既定で 127.0.0.1 ローカル限定. **外部公開 (`--host 0.0.0.0` 等) は
  `--allow-external` が必須**で、PII フィルタが動作していても質問文 raw が漏洩するリスクがあるため、
  信頼できるネットワーク内でのみ公開すること. 技術規律の詳細は repo `CLAUDE.md`
  の「やってはいけないこと」を参照.

## 関連

- `tools/embed/` — embedding 生成パイプライン
- `tools/embed/retrieve.py` — 評価セット駆動のベンチマーク CLI
- `benchmarks/results/` — 公開可能なベンチマーク結果

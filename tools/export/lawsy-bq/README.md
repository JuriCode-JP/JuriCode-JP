# tools/export/lawsy-bq — JuriCode-JP → BigQuery JSONL Exporter

JuriCode-JP の法令データ Markdown ファイルを、デジタル庁「源内 (GENAI)」の
法制度 AI アプリ **Lawsy-Custom-BQ** が読める **BigQuery JSON Lines (NDJSON)**
形式に変換するスクリプト群。

このディレクトリで実現したいこと:

1. **源内接続** — JuriCode-JP の整理済み法令データを、政府の生成 AI 基盤
   (源内) に投入できる形式に変換する
2. **RAG-ready 化** — AI が検索・引用しやすい構造 (1 条 or 1 項ごとの
   レコード + メタデータ + 典拠 URL) を生成する

実は (1) と (2) は同じ作業です。RAG-ready なデータが、そのまま源内に投入
できる形式になっています。

---

## ファイル

| ファイル | 役割 |
|---|---|
| `export-jsonl.py` | メインの変換スクリプト |
| `schema.json` | BigQuery テーブルスキーマ (15 列) |
| `README.md` | このファイル |

---

## 使い方

### 1. 既存サンプル 2 件を条文単位で書き出し

```bash
# リポジトリのルートで実行
python tools/export/lawsy-bq/export-jsonl.py \
    --input examples \
    --output build/juricode-bq.jsonl
```

これで `examples/keihou/keihou-article-36.md` と
`examples/keiji-soshou-hou/keiji-soshou-hou-article-198.md` を読み込み、
`build/juricode-bq.jsonl` に 2 行の JSON Lines を出力します。

### 2. 項単位 (paragraph) でチャンクを細かくしたい場合

RAG では「チャンクが小さい方が検索精度が上がる」傾向があります。
1 条が長い法令 (例: 地方自治法) で項単位に分けたい場合:

```bash
python tools/export/lawsy-bq/export-jsonl.py \
    --input examples \
    --chunk paragraph
```

刑法 36 条は 2 項あるので、`--chunk paragraph` だと 2 行に分かれます。

### 3. 標準出力に流す (パイプ用)

```bash
python tools/export/lawsy-bq/export-jsonl.py --input examples | head -1 | jq
```

---

## 出力レコード例

`--chunk article` モードで `examples/keihou/keihou-article-36.md` を変換すると、
次のような 1 行が得られます (見やすさのため改行を入れていますが、実際は 1 行):

```json
{
  "article_id": "keihou-art-36",
  "law_id": "140AC0000000045",
  "law_name_ja": "刑法",
  "law_name_en": "Penal Code",
  "article_number": "36",
  "paragraph_number": null,
  "chunk_type": "article",
  "text": "### 第三十六条\n\n急迫不正の侵害に対して...",
  "source_url": "https://laws.e-gov.go.jp/law/140AC0000000045",
  "source_format": "e-gov-html",
  "version_date": "2007-06-12",
  "last_verified": "2026-05-14",
  "license": "MIT",
  "translation_status": "draft",
  "tags": ["phase1-police", "刑事法", "正当防衛", "違法性阻却事由", "sample"]
}
```

---

## BigQuery への投入手順 (実機検証用)

NLnet M5 (€5,000) の A/B ベンチマークでは、JuriCode-JP データを BigQuery に
投入して、源内 Lawsy-Custom-BQ の RAG 回答精度を e-Gov 単体と比較する想定です。
個人 GCP アカウントで動かす場合の参考手順:

```bash
# 1. JSONL を生成
python tools/export/lawsy-bq/export-jsonl.py \
    --input examples \
    --output build/juricode-bq.jsonl

# 2. BigQuery にデータセット・テーブル作成 (一度だけ)
bq mk --dataset juricode_jp
bq mk --table \
    --schema tools/export/lawsy-bq/schema.json \
    juricode_jp.articles

# 3. 投入
bq load \
    --source_format=NEWLINE_DELIMITED_JSON \
    juricode_jp.articles \
    build/juricode-bq.jsonl

# 4. テスト検索
bq query --use_legacy_sql=false '
    SELECT article_id, law_name_ja, text
    FROM `juricode_jp.articles`
    WHERE REGEXP_CONTAINS(text, r"正当防衛")
'
```

---

## チャンク戦略の方針

| モード | 1 レコード | 用途 |
|---|---|---|
| `article` | 1 条 | デフォルト。条文単位で AI に渡したいとき |
| `paragraph` | 1 項 | 長い条文での RAG 検索精度向上、または項単位での引用が必要なとき |

将来的には、刑法・刑訴法のような短い条文は `article`、地方自治法のような
長い条文は `paragraph` を選ぶような自動判定も検討余地あり。

---

## 関連

- **源内 (GENAI)**: https://www.digital.go.jp/en/policies/genai
- **Lawsy-Custom-BQ 解説**: https://dev.classmethod.jp/articles/digital-genai-lawsy-aws/
- **JuriCode-JP IR 仕様**: [docs/ir-spec.md](../../../docs/ir-spec.md)
- **NLnet M5 (€5,000)**: 源内 exporter + A/B ベンチマーク報告 — 採択時の主要 deliverable
- **Follow-up tracker**: [FU-P0-3](../../../docs/follow-ups.html#fu-p0-3-toolsexportlawsy-bq-nlnet-m5)

---

## ステータス

- v0.1 (2026-05-19): MVP 初版. `examples/` の 2 件を変換できる. data/ 配下の本データはまだ空.
- 次の一歩: data/phase1-domestic/ (旧 phase1-police) 配下の本データを充実させて、再変換 → 本物の RAG ベンチマークへ

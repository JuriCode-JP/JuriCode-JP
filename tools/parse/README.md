# tools/parse — e-Gov XML → JuriCode-JP Markdown 変換

JuriCode-JP の Layer 2 (生成時) と Layer 3 (検証) を担う.
詳細設計: [docs/verification-framework.md](../../docs/verification-framework.md)

---

## ファイル

| ファイル | 役割 |
|---|---|
| `parse-egov.py` | e-Gov 法令 XML を 1 条 1 ファイルの Markdown に変換 |
| `verify.py` | 生成済み Markdown が改変されていないかハッシュで検証 |
| `_canonicalize.py` | 正規化ヘルパー (parse と verify で共有) |
| `tests/fixtures/sample-egov-format-FIXTURE.xml` | 動作確認用ダミー XML (`data/` に投入禁止) |

---

## 使い方

### 前提: e-Gov XML を手元に用意

サンドボックス・CI から e-Gov 直接到達はできないので, 手元の PC で
`tools/fetch-egov/` を走らせて XML をキャッシュする:

```bash
cd tools/fetch-egov
uv run fetch-egov get-law keisatsukan-shokumu-shikkou-hou \
    -o ../../cache/323AC0000000136.xml
```

### Step 1. XML を Markdown に変換

```bash
python tools/parse/parse-egov.py \
    --input cache/323AC0000000136.xml \
    --output data/phase1-police/keisatsukan-shokumu-shikkou-hou/ \
    --abbrev keisatsukan-shokumu-shikkou-hou
```

生成物:

- `data/.../<law>-article-N.md` (条文数だけ)
- `data/.../_source-manifest.json` (全件分のハッシュ記録)

### Step 2. ハッシュ検証

```bash
python tools/parse/verify.py --path data/phase1-police/keisatsukan-shokumu-shikkou-hou/
```

各 Markdown 本文を再ハッシュしてマニフェストと突合.
本文を 1 文字でも変えると即 **FAIL**.

### Step 3. (オプション) スキーマ検証も

```bash
python tools/validate/validate-all.py
```

---

## 検証フレームワーク 3 層 + 人間

```
Layer 1 (取得時)   tools/fetch-egov/         e-Gov API → cache/
Layer 2 (生成時)   tools/parse/parse-egov.py  XML → Markdown + manifest
Layer 3 (CI 時)    tools/parse/verify.py      Markdown vs manifest
                   tools/validate/            schema 検証
Layer 4 (人間)     PR レビューで原典目視
```

---

## なぜハッシュ検証が必要か

CLAUDE.md §4.1 「法令本文の改変・要約・読みやすさ調整はすべて禁止」を
**機械的に**保証する必要がある.

`verify.py` の hash チェックは:

- うっかり Markdown を編集してしまった
- エディタの自動整形で空白や句読点が変わった
- 善意の (しかし禁止された) 「読みやすさ調整」
- merge conflict の解決ミス

を検知する. 実証 (2026-05-19): フィクスチャ本文に 2 文字追加 → 即 FAIL.

---

## 動作確認 (フィクスチャ)

`data/` に触らずに動作確認:

```bash
# parse
python tools/parse/parse-egov.py \
    --input tools/parse/tests/fixtures/sample-egov-format-FIXTURE.xml \
    --output build/test-parse-output/ \
    --abbrev test-fixture-law \
    --law-id 999AC9999999999 \
    --version-date 2026-05-19 --force

# verify
python tools/parse/verify.py --path build/test-parse-output/

# 改竄テスト → FAIL するはず
sed -i 's/第二条第二項/第二条第二項改竄/' build/test-parse-output/test-fixture-law-article-2.md
python tools/parse/verify.py --path build/test-parse-output/  # exit 1
```

---

## ステータス

- v0.1 (2026-05-19): MVP. 標準法 XML schema v3 の `<Law>` / `<LawBody>` /
  `<MainProvision>` / `<Article>` / `<Paragraph>` を扱う.
  附則・経過措置・別表は未対応 (Phase 2 検討).
- 次の一歩: 実 e-Gov XML を手元取得 → `data/phase1-police/` 配下を本物データで埋める.

---

## 関連

- [FU-P0-1](../../docs/follow-ups.html#fu-p0-1-toolsparse-mvp-nlnet-m2) — この MVP の元タスク
- [tools/fetch-egov/](../fetch-egov/README.md) — Layer 1 (上流)
- [tools/validate/](../validate/README.md) — Layer 3 (スキーマ検証)
- [tools/export/lawsy-bq/](../export/lawsy-bq/README.md) — 下流 (BigQuery 投入)

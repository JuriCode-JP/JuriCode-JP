# tools/fetch-egov — e-Gov 法令API v2 クライアント

JuriCode-JP のデータ取得層。e-Gov 法令API v2(https://laws.e-gov.go.jp/api/2/) から法令 XML を取得し、ローカルキャッシュに保存する。

## 状態

**v0.1.0 / 2026-05-18 スケルトン作成**。動作テスト(実 API へのリクエスト)はこれから。

---

## ディレクトリ構成

```
fetch-egov/
├── README.md
├── pyproject.toml
├── .gitignore
├── src/
│   └── fetch_egov/
│       ├── __init__.py
│       ├── client.py        # EGovClient(HTTP クライアント本体)
│       ├── models.py        # Pydantic モデル(LawMetadata, LawData)
│       ├── cache.py         # FileCache(ローカルキャッシュ)
│       ├── law_id_map.py    # 略称 ↔ 法令ID マップ(glossary.md と同期)
│       └── cli.py           # CLI エントリポイント
├── tests/
│   ├── __init__.py
│   └── test_client.py       # 基本テスト(モック使用、ライブ API なし)
└── cache/                   # .gitignore 対象(取得 XML のローカル保存先)
```

---

## セットアップ

[uv](https://docs.astral.sh/uv/) を推奨。

```bash
cd tools/fetch-egov
uv sync                            # 依存関係インストール
uv run pytest                      # テスト実行(ライブ API は呼ばない、モックのみ)
```

または pip:

```bash
cd tools/fetch-egov
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

---

## CLI 使い方

### 法令を取得

```bash
# 略称で取得(刑法)
uv run fetch-egov get-law keihou

# 法令IDで取得(同じく刑法)
uv run fetch-egov get-law 140AC0000000045

# 特定時点の刑法(2020年1月1日時点、v2 機能)
uv run fetch-egov get-law keihou --at-date 2020-01-01

# キャッシュを無視して再取得
uv run fetch-egov get-law keihou --force-refresh

# 標準出力ではなくファイルに保存
uv run fetch-egov get-law keihou -o /tmp/keihou.xml
```

### キャッシュ管理

```bash
# キャッシュ済みの法令一覧
uv run fetch-egov list-cached

# キャッシュ全削除(確認なし)
uv run fetch-egov clear-cache --yes
```

### 略称⇔法令ID

```bash
# 登録されている略称一覧
uv run fetch-egov list-abbrev

# 略称を法令IDに解決
uv run fetch-egov resolve keihou
# → 140AC0000000045
```

---

## Python から使う

```python
from fetch_egov import EGovClient, FileCache
from datetime import date

# クライアント初期化(キャッシュは ./cache/)
with EGovClient(cache=FileCache("cache/")) as client:
    # 最新の刑法を取得
    xml = client.get_law("keihou")

    # 2020年1月1日時点の刑法
    xml_2020 = client.get_law("keihou", as_of=date(2020, 1, 1))

    # メタデータ付きで取得
    data = client.get_law_data("keihou")
    print(data.law_name)            # → 刑法
    print(data.article_count_estimate())  # → 264(刑法の条数の目安)
```

---

## 設計の前提

### v1 互換 URL を仮定

現状の `_fetch_law_xml()` は v1 系の URL パス(`/lawdata/{law_id}`)を仮定して実装している。
e-Gov 法令API v2(2025-03-19 公開)の正確なエンドポイント名は OpenAPI 仕様で要再確認:

- ReDoc: https://laws.e-gov.go.jp/api/2/redoc/
- Swagger UI: https://laws.e-gov.go.jp/api/2/swagger-ui

動作テスト時に必要に応じて `client.py` の `_fetch_law_xml()` と `list_laws()` を修正する。

### レート制限

公式の明文レート制限は無いが、自主規制として 1 秒 1 リクエストの間隔を `EGovClient.DEFAULT_RATE_LIMIT_SECONDS = 1.0` で設定。テスト時は `rate_limit_seconds=0` で無効化できる。

### キャッシュ

`cache/laws/{law_id}.xml`(最新版)と `cache/snapshots/{law_id}__{date}.xml`(特定時点)を分離して保存。`cache/` は `.gitignore` 対象でリポジトリには含まない。

### Pydantic モデル

`models.py` は `extra="allow"` で未知フィールドを許容。e-Gov API v2 のレスポンス仕様が今後変更されても、Pydantic 側で壊れない設計。

---

## 上位レイヤとの接続

- **`tools/parse/`**: 取得した XML を `ja-law-parser`(takuyaa)に渡してパース → Pydantic オブジェクト化
- **`tools/validate/`**: パース結果と `schema/*.schema.json` の整合性検証
- **`tools/translate/`**: 法務省「日本法令外国語訳DB」の公定訳取り込み
- **`data/phase1-police/`**: 構造化済みの YAML frontmatter + Markdown 出力先

---

## API 仕様の参考

- 公式トップ: https://laws.e-gov.go.jp/apitop/
- v2 OpenAPI (ReDoc): https://laws.e-gov.go.jp/api/2/redoc/
- v2 Swagger UI: https://laws.e-gov.go.jp/api/2/swagger-ui
- v2 公開日: 2025-03-19(JuriCode-JP プロジェクト start より前)

---

## 既存 OSS との関係

| プロジェクト | 関係 |
|---|---|
| [ja-law-parser](https://github.com/takuyaa/ja-law-parser) | `tools/parse/` で直接依存(pydantic-xml ベースの XML パーサー)。fetch-egov が XML を取得 → ja-law-parser がパース、という分業 |
| [gitlaw-jp](https://github.com/aluqas/gitlaw-jp) | 同じ e-Gov API を使うが、用途は Git コミット生成。fetch-egov は構造化 Markdown 用、住み分け |
| [Lawtext](https://github.com/yamachig/Lawtext) | 法令テキストフォーマット、変換ツール群。本パッケージとは直接依存なし(将来 `tools/convert/lawtext/` で連携) |
| [e-Gov MCP](https://github.com/ryoooo/e-gov-law-mcp) | リアルタイム取得 MCP サーバー。fetch-egov は静的データセット用、用途が異なる |

---

## 既知の TODO

- [ ] e-Gov API v2 の正確なエンドポイント名を OpenAPI 仕様で確認 → `client.py` の URL 修正
- [ ] `list_laws()` のレスポンス構造を v2 仕様に合わせる
- [ ] 一括ダウンロード(`all_xml.zip`)対応の検討(将来)
- [ ] HTTP 429 / 5xx 系エラーの自動リトライ実装
- [ ] async 版クライアント(httpx.AsyncClient)
- [ ] CLI に `get-articles` サブコマンド(条文単位取得)

---

## ライセンス

MIT(JuriCode-JP プロジェクトと同じ)

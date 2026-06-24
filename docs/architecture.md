# JuriCode-JP アーキテクチャ設計

**バージョン**: v0.1 (2026-05-18 初版)
**対象**: Phase 1(2026-2027、警察関連法令)
**関連文書**: [ir-spec.md](./ir-spec.md)(中間表現詳細仕様)、[format-spec.md](./format-spec.md)(最終 YAML+Markdown 出力仕様)、[strategy.md](./strategy.md)(段階戦略)

---

## 1. 概要

JuriCode-JP は **e-Gov 法令API から取得した XML を、LLM/RAG 最適化された YAML+Markdown コーパスに変換する**パイプラインを核とする。本書はその実装アーキテクチャを定義する。

### 1.1 設計原則

1. **段階分離(Stage Separation)**: 取得 → パース → 変換 → 翻訳 → 出力 → 検証 を独立したステージに分離。各ステージは入出力契約だけで結合する。
2. **共通中間表現(IR)**: ja-law-parser の `Law` Pydantic モデルから、JuriCode 独自の `JuriCodeArticle` IR に変換し、以降の処理は全て IR を流す。詳細は [ir-spec.md](./ir-spec.md)。
3. **車輪の再発明禁止**: e-Gov XML パースは `ja-law-parser`(takuyaa)に依存、フォーマット変換は将来 `Lawtext`(yamachig)との相互運用も視野。
4. **MIT ライセンス・OSS 原則**: 全コードは MIT、外部依存も MIT/BSD/Apache 互換のみ。
5. **テスタブル**: 各ステージはモック可能、ライブ API テストは別レイヤ。

### 1.2 高レベルアーキテクチャ図

```
┌─────────────────────────────────────────────────────────────┐
│                    e-Gov 法令API v2                          │
│         https://laws.e-gov.go.jp/api/2/                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ XML (標準法 XML スキーマ v3)
                           ▼
                ┌──────────────────────┐
                │   tools/fetch-egov   │  HTTP クライアント + キャッシュ
                │   ✅ 完成 (v0.1.0)    │
                └──────────┬───────────┘
                           │ cache/laws/{law_id}.xml
                           ▼
                ┌──────────────────────┐
                │     tools/parse      │  XML → ja-law-parser Pydantic
                │   🟡 未着手(takuyaa  │
                │       依存)          │
                └──────────┬───────────┘
                           │ Law (ja_law_parser.model.Law)
                           ▼
                ┌──────────────────────┐
                │   tools/transform    │  Law → JuriCode IR (条文単位)
                │   ★ 設計済・未実装    │
                └──────────┬───────────┘
                           │ list[JuriCodeArticle]
                           ▼
            ┌──────────────────────────┐
            │     tools/translate      │  IR + 公定訳 → IR(英訳統合)
            │   🟡 未着手(法務省 JLT)  │
            └──────────┬───────────────┘
                           │ list[JuriCodeArticle](英訳付き)
                           ▼
                ┌──────────────────────┐
                │     tools/render     │  IR → YAML frontmatter + MD
                │   ★ 設計済・未実装    │
                └──────────┬───────────┘
                           │ data/phase1-police/keihou/keihou-article-36.md
                           ▼
                ┌──────────────────────┐
                │    tools/validate    │  ファイル → schema/*.schema.json 検証
                │   🟡 未着手           │
                └──────────────────────┘
                           │
                           ▼
                    ✅ Phase 1 MVP
```

---

## 2. リポジトリ全体構造(Phase 1 実装後の状態)

```
JuriCode-JP/
├── README.md
├── CLAUDE.md
├── LICENSE
├── .gitignore
├── docs/
│   ├── README.md
│   ├── architecture.md             ★ 本書
│   ├── ir-spec.md                  ★ 中間表現詳細
│   ├── format-spec.md              ✅ 最終出力フォーマット
│   ├── strategy.md                 ✅ 段階戦略
│   ├── differentiation.md          ✅ 先行 OSS との関係
│   └── glossary.md                 ✅ 日英用語集
├── schema/
│   ├── law-frontmatter.schema.json ✅ YAML frontmatter 検証
│   ├── article.schema.json         ✅ 条文構造検証
│   └── case-link.schema.json       ✅ 判例リンク検証
├── examples/
│   └── keihou/
│       └── keihou-article-36.md    ✅ 正規参考例
├── data/
│   └── phase1-police/              🟡 順次量産
│       ├── keihou/
│       │   ├── README.md
│       │   ├── keihou-article-1.md
│       │   ├── keihou-article-2.md
│       │   ├── ... (主要 100-150 条)
│       │   └── archive/             ← 過去版(将来仕様)
│       │       └── 2020-01-01/
│       │           └── keihou-article-36.md
│       ├── keiji-soshou-hou/
│       ├── keisatsu-hou/
│       └── keisatsukan-shokumu-shikkou-hou/
├── tools/
│   ├── README.md                   ← 全体オーケストレーション
│   ├── shared/                     ★ 新規: 共通モデル・ユーティリティ
│   │   ├── pyproject.toml
│   │   ├── src/juricode_shared/
│   │   │   ├── __init__.py
│   │   │   ├── ir.py               ← JuriCode IR Pydantic 定義
│   │   │   ├── frontmatter.py      ← YAML frontmatter 構造
│   │   │   ├── ids.py              ← article_id, case_id 規約
│   │   │   ├── paths.py            ← ファイル配置ルール
│   │   │   └── enums.py            ← TranslationStatus 等の列挙
│   │   └── tests/
│   ├── fetch-egov/                 ✅ 完成: HTTP + キャッシュ
│   ├── parse/                      🟡 未着手: ja-law-parser ラッパ
│   │   ├── pyproject.toml          (ja-law-parser に依存)
│   │   └── src/juricode_parse/
│   │       ├── parser.py           ← XML → Law (ja_law_parser)
│   │       └── ir_converter.py     ← Law → JuriCodeArticle list
│   ├── transform/                  ★ 新規
│   │   ├── pyproject.toml
│   │   └── src/juricode_transform/
│   │       ├── splitter.py         ← Law を条文単位に分割
│   │       └── normalizer.py       ← 漢数字 → 算用数字、空白整形 等
│   ├── translate/                  🟡 未着手
│   │   ├── pyproject.toml
│   │   └── src/juricode_translate/
│   │       ├── jlt_db.py           ← 法務省 JLT-DB クライアント
│   │       └── merger.py           ← 公定訳 + IR をマージ
│   ├── render/                     ★ 新規
│   │   ├── pyproject.toml
│   │   └── src/juricode_render/
│   │       ├── yaml_renderer.py    ← IR → YAML frontmatter
│   │       ├── markdown_renderer.py← IR → 本文 Markdown
│   │       └── file_writer.py      ← data/ 配下に書き出し
│   ├── validate/                   🟡 未着手
│   │   ├── pyproject.toml
│   │   └── src/juricode_validate/
│   │       ├── schema_check.py     ← JSON Schema 検証
│   │       ├── case_url_check.py   ← 判例 URL 生存確認
│   │       └── completeness.py     ← 必須フィールド完備性
│   ├── pipeline/                   ★ 新規: ワークフローオーケストレーション
│   │   ├── pyproject.toml
│   │   └── src/juricode_pipeline/
│   │       ├── orchestrator.py     ← fetch → ... → validate を連結
│   │       └── cli.py              ← uv run juricode build keihou
│   └── tests/                      ← 統合テスト
└── .github/
    ├── ISSUE_TEMPLATE/
    ├── PULL_REQUEST_TEMPLATE.md
    └── workflows/                  ← CI(将来)
        ├── lint.yml
        ├── test.yml
        └── validate-data.yml
```

凡例: ✅ 実装済 / 🟡 計画あり未着手 / ★ 設計済・未実装

---

## 3. tools/ サブパッケージ詳細

### 3.1 `tools/shared/` — 共通モデル・ユーティリティ

すべての tools が依存する共通ライブラリ。Pydantic IR、ID 規約、ファイル配置ルールを集約。

**主な公開 API**:
- `juricode_shared.ir.JuriCodeArticle` — 条文単位の IR
- `juricode_shared.ir.CaseReference` — 判例リンクの IR
- `juricode_shared.ids.make_article_id(law_abbrev, number)` — `keihou-art-36` を生成
- `juricode_shared.paths.article_path(law_abbrev, number)` — 出力先パスを生成

依存: pydantic のみ(他の tools/ には依存しない)。

### 3.2 `tools/fetch-egov/` ✅ 完成

(本書 v0.1.0 時点で完成済。詳細は `tools/fetch-egov/README.md`)

### 3.3 `tools/parse/`

**役割**: e-Gov XML を `ja-law-parser`(takuyaa)でパースし、`Law` Pydantic オブジェクトに変換 → さらに JuriCode IR に変換。

**主な公開 API**:
- `juricode_parse.parse_xml(xml: str) -> ja_law_parser.model.Law`
- `juricode_parse.law_to_ir(law: Law, law_abbrev: str) -> list[JuriCodeArticle]`

依存: `ja-law-parser>=0.3.0`, `juricode-shared`, `pydantic`

**takuyaa 氏との関係**: jp-oss-outreach.md §4 で打診中。`ja-law-parser` が e-Gov API v2 未対応の場合は、JuriCode-JP 側で PR を出すか、forkメンテを検討。

### 3.4 `tools/transform/`

**役割**: Law(法令単位)を Article(条文単位)に分割し、表記揺れを正規化。

**主な公開 API**:
- `juricode_transform.split_articles(law: Law) -> list[Article]` ← parse 後の中間
- `juricode_transform.normalize_article_number("第三十六条") -> "36"`(漢数字変換)
- `juricode_transform.normalize_paragraph_number("２") -> "2"`(全角→半角)

依存: `juricode-shared`

### 3.5 `tools/translate/`

**役割**: 法務省「日本法令外国語訳DB」(JLT-DB)から公定訳を取得し、JuriCode IR にマージ。

**主な公開 API**:
- `juricode_translate.fetch_official_translation(law_id: str, article_number: str) -> str | None`
- `juricode_translate.merge_translation(article: JuriCodeArticle, translation: str) -> JuriCodeArticle`

依存: `httpx`, `juricode-shared`, `juricode-fetch-egov`(英訳エンドポイントを共有する場合)

**JLT-DB の特殊性**:
- API がなく、Web スクレイピング or 一括ダウンロードのみ
- 翻訳が古いままの法令も多い(`translation_status` で明示)
- 公定訳がない場合は `translation_status: draft` で `machine_translated: true` のドラフトを生成(Claude API 経由、別系統)

### 3.6 `tools/render/`

**役割**: JuriCode IR を YAML frontmatter + Markdown 形式の最終ファイルに変換。

**主な公開 API**:
- `juricode_render.render_yaml(article: JuriCodeArticle) -> str`
- `juricode_render.render_markdown(article: JuriCodeArticle) -> str`
- `juricode_render.write_file(article: JuriCodeArticle, root: Path) -> Path`(配置ルールで自動配置)

依存: `pyyaml`, `juricode-shared`, `jinja2`(テンプレート)

**出力テンプレート**: `examples/keihou/keihou-article-36.md` をベースに jinja2 化。

### 3.7 `tools/validate/`

**役割**: 生成された Markdown ファイルが schema を満たすか検証。

**主な公開 API**:
- `juricode_validate.check_file(path: Path) -> ValidationResult`
- `juricode_validate.check_all(root: Path) -> list[ValidationResult]`
- `juricode_validate.check_case_urls(article: JuriCodeArticle) -> list[UrlResult]`(判例 URL 生存確認、ネット必要)

依存: `jsonschema`, `pyyaml`, `httpx`, `juricode-shared`

### 3.8 `tools/pipeline/`

**役割**: 全ステージを連結するオーケストレーション。

**CLI 例**:
```bash
# 刑法を fetch → parse → transform → translate → render → validate
uv run juricode build keihou

# 刑法 36 条のみ
uv run juricode build keihou --article 36

# Phase 1 全 4 法令を一括ビルド
uv run juricode build-phase1

# 既存データの再検証のみ
uv run juricode validate
```

**主な公開 API**:
- `juricode_pipeline.run(law_abbrev: str, articles: list[str] | None = None) -> BuildResult`

依存: 上記すべての tools/

---

## 4. データフロー詳細

### 4.1 標準パイプライン

```
1. fetch    : e-Gov API → cache/laws/{law_id}.xml
2. parse    : XML → ja_law_parser.model.Law (in-memory)
3. transform: Law → list[JuriCodeArticle] (条文単位 IR)
4. translate: 公定訳取得 → IR.english_translation 更新
5. render   : IR → YAML+MD ファイル(data/ 配下)
6. validate : ファイル → schema 検証 → CI 通過
```

### 4.2 ステージ間の入出力契約

| ステージ | 入力 | 出力 | 永続化? |
|---|---|---|---|
| fetch | law_id, as_of | XML 文字列 | ✅ cache/laws/ |
| parse | XML 文字列 | `Law` (Pydantic) | ❌ in-memory |
| transform | `Law` | `list[JuriCodeArticle]` | ❌ in-memory |
| translate | `JuriCodeArticle` | `JuriCodeArticle`(英訳追加) | ❌ in-memory |
| render | `JuriCodeArticle` | `Path`(書き出し済み) | ✅ data/ |
| validate | `Path` | `ValidationResult` | ❌(レポートのみ) |

中間ステージは in-memory パス。デバッグ時のみ `--dump-ir` 等で JSON 出力可能(設計)。

### 4.3 エラーハンドリング方針

| エラー | 対応 |
|---|---|
| fetch: 404 / 5xx | リトライ 3 回 → 失敗時は警告ログ + 該当法令スキップ |
| parse: XML 構造異常 | エラー詳細を JSON でダンプ、ja-law-parser に Issue 報告候補 |
| transform: 想定外の構造(N段ロケット等) | スキップして警告、`tools/manual-review/` に隔離 |
| translate: 公定訳なし | `translation_status: draft` で続行 |
| render: I/O エラー | 即座に fail-fast |
| validate: schema 違反 | エラー詳細出力、CI 失敗 |

---

## 5. ストレージレイアウト

### 5.1 ローカルキャッシュ(.gitignore 対象)

```
tools/fetch-egov/cache/
├── laws/
│   └── {law_id}.xml          # 最新版
└── snapshots/
    └── {law_id}__{date}.xml  # 特定時点
```

### 5.2 生成物(コミット対象)

```
data/phase1-police/{law-abbrev}/
├── README.md                          ← 各法令の進捗概要
├── {law-abbrev}-article-{N}.md        ← 主要条文(最新版)
└── archive/                            ← 過去版(将来仕様、Phase 1 では使わない)
    └── {date}/
        └── {law-abbrev}-article-{N}.md
```

### 5.3 一時ファイル(.gitignore 対象)

```
tools/pipeline/.work/
├── ir-dump/                  # --dump-ir で出力された JSON
├── validation-reports/       # 検証結果レポート
└── logs/                     # パイプライン実行ログ
```

---

## 6. パイプライン CLI 設計

### 6.1 基本コマンド

```bash
# 単一法令のビルド
uv run juricode build keihou

# 単一条文のビルド(デバッグ・テスト用)
uv run juricode build keihou --article 36

# Phase 1 全 4 法令を並列ビルド
uv run juricode build-phase1 --parallel

# 特定時点取得
uv run juricode build keihou --as-of 2020-01-01

# 既存データの再検証のみ(変換しない)
uv run juricode validate
uv run juricode validate data/phase1-police/keihou/

# 個別ステージのみ実行(デバッグ用)
uv run juricode fetch keihou           # → cache/ にのみ保存
uv run juricode parse keihou --dump-ir # → IR を JSON で出力
uv run juricode render keihou          # → cache/ からのみ render
```

### 6.2 CI 用コマンド

```bash
# 全データの schema 検証(.github/workflows/validate-data.yml で実行)
uv run juricode validate --strict --exit-on-error

# 全データの判例 URL 生存確認(週次実行、CI で別ジョブ)
uv run juricode validate --check-urls
```

---

## 7. テスト戦略

### 7.1 単体テスト(各 tools/{X}/tests/)

各パッケージに最低限の単体テスト:
- `tools/fetch-egov/tests/` — モック HTTP、ライブ API なし(✅ 実装済 10 テスト)
- `tools/parse/tests/` — `ja-law-parser` の動作を含むサンプル XML テスト
- `tools/transform/tests/` — 漢数字変換、条文分割の境界条件
- `tools/render/tests/` — IR → 既知の Markdown 出力の一致確認
- `tools/validate/tests/` — schema 違反検出の精度

### 7.2 統合テスト(tools/tests/integration/)

実 API・実データを使うテスト。手動実行(CI では skip):

```bash
# 刑法 36 条が「正しく」生成される end-to-end テスト
uv run pytest tools/tests/integration/test_build_keihou_36.py
```

このテストは `examples/keihou/keihou-article-36.md` を期待値として比較し、パイプライン全体の動作を保証。

### 7.3 CI で実行するテスト

`.github/workflows/test.yml`:
- 全 tools/ の単体テスト(ライブ API なし)
- ruff によるリント
- mypy による型チェック

`.github/workflows/validate-data.yml`:
- 全 data/ のスキーマ検証
- main ブランチで失敗するとマージ不可

---

## 8. 依存関係(外部 OSS)

### 8.1 必須依存

| パッケージ | 用途 | バージョン | ライセンス | 確保状況 |
|---|---|---|---|---|
| `ja-law-parser` | XML パース | >=0.3.0 | MIT | takuyaa 氏に打診中(jp-oss-outreach.md §4)|
| `pydantic` | データモデル | >=2.7 | MIT | 安定 |
| `httpx` | HTTP クライアント | >=0.27 | BSD-3 | 安定 |
| `click` | CLI | >=8.1 | BSD-3 | 安定 |
| `pyyaml` | YAML 入出力 | >=6.0 | MIT | 安定 |
| `jinja2` | レンダリングテンプレート | >=3.1 | BSD-3 | 安定 |
| `jsonschema` | スキーマ検証 | >=4.0 | MIT | 安定 |

### 8.2 任意依存

| パッケージ | 用途 |
|---|---|
| `Lawtext`(yamachig) | 双方向変換(将来 `tools/convert/lawtext/`) |
| `e-Gov MCP`(ryoooo) | リアルタイム法令取得との相互参照(README リンクのみ) |
| `gitlaw-jp`(aluqas) | 設計参考、直接依存なし |

### 8.3 開発依存

`pytest`, `pytest-mock`, `respx`, `ruff`, `mypy`

---

## 9. バージョニング

各 tools/ サブパッケージは独立した SemVer(例: `fetch-egov-0.1.0`)。

破壊的変更:
- IR スキーマの破壊的変更 → `juricode-shared` のメジャー版アップ
- 出力フォーマットの破壊的変更 → `format-spec.md` のバージョンアップ + `juricode-render` のメジャー版アップ

---

## 10. 拡張(Phase 2/3 への備え)

### 10.1 Phase 2(民事・商事、2027〜)で何が変わるか

- 新法令の追加 → `LAW_ID_MAP` 拡張、`data/phase2-civil/` 新設
- **民事判決オープン化(2026 年度運用開始)との接続** → `tools/fetch-judgments/` 新規パッケージ追加
- 判例リンクの量が爆発的に増える → IR の `cases:` フィールドのスケール対応

### 10.2 Phase 3(全領域、2028-2030)で何が変わるか

- 全領域カバー → 並列ビルド最適化、データ量の分割管理
- 国際展開 → `legalize.dev` 互換のエクスポート機能(`tools/export/legalize-dev/`)
- 源内 Lawsy-BQ への投入 → `tools/export/lawsy-bq/`

これらすべて、現状のパイプライン構造を拡張する形で実装可能。

---

## 11. 関連メモリ・記録

- `_SESSION_BRIEFING.md`(Vault)— 日々の進捗
- `business/phase1-implementation-plan-2026.md` — 5/28 〜 11 月の月別マイルストン
- メモリ `project_juricode_phase_balance.md` — 対外フレーミング vs 内部目標のバランスルール
- `awards/applications/jp-oss-outreach.md` — OSS 4 メンテナへの打診戦略

---

*最終更新: 2026-05-18 / 作成者: Claude(計画セッション)*
*次回更新の目安: tools/parse/ 実装着手時、IR スキーマが確定したタイミング*

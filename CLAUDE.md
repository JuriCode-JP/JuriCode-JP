# CLAUDE.md — AI Assistant Guide for JuriCode-JP

このファイルは、Claude等のAIアシスタントがこのリポジトリで作業するときに、最初に必ず読むべきガイドです。
人間のコントリビューターは `README.md` と `docs/` から読み始めてください。

> **土台**: 本リポの全作業は司令塔『共通規範_選択的厳密性とAI検証』(`司令塔/システム/プロトコル/`) に従う。
> **運用・戦略レベルは ① Vault CLAUDE.md、ソースコードの具体規約は本②**。①には判断・検証の共通OS
> （選択的厳密性／Tier／不変条件ゲート／AI検証）が統合済み。本②はそのコード作業向け凝縮版（§0）。

---

## 0. 判断・検証の共通OS（選択的厳密性とAI検証）— コード作業の土台

> 全業務OS＝司令塔『共通規範』に従う。本§0はコード作業に効かせる凝縮版。運用・戦略は ① Vault CLAUDE.md。
> 重複する具体規則は本ファイル該当節（§5/§7/§8/§10）に集約済みで、ここからは参照のみ（再掲しない）。

### 0.1 着手プロトコル（Tier 宣言）
- 着手前に **Tier（S/A/B/C）を宣言**。間違いのコストに比例して厳密性を配分（厳密性は資源）。**S 以外で多巡しない**（過剰研磨の禁止）。
  - S=制度・数値・施行日・判例の事実/数値・公開可否 ／ A=新規実装・スキーマ・重要な構成変更 ／ B=権威データの忠実取込・初稿 ／ C=対外連絡・探索アイデア。

### 0.2 不変条件＝ハードゲート（満たさねば merge 不可）
- 法令本文 == e-Gov ソース（本文非改変を機械照合 → §4.1 / §5）。判例は出典必須・推測追加禁止（→ §3.5 / §5）。
- round-trip hash 一致／schema valid／表・別表の欠落ゼロ／出典付与（→ §8 の検証コマンドで実証）。
- ロック済 expected を改変しない。**テストが落ちたら直すのはコード、期待値ではない**（期待値変更は user 明示承認）。
- **PR 必須（main 直 push 禁止）**・一機能一コミット・CI 全ステップ green（→ §6 / §7）。
- **完了は版管理で検証**（commit 存在／差分が意図ファイルのみ／テスト反映）。**自己申告で完了報告しない**。

### 0.3 着手前チェック（6 地雷・税務エンジン査読由来）
- **集計単位マトリクス**: 概念を束ねる時、種類×サブ処理の表で「集計単位・丸め・適用ルールが同一か」を明示検証（"同じはず"禁止）。
- **同名異義辞書**: 「法人税額／月数／課税標準／資本金等」等はプロパティ名で区別。
- **受け渡し点チェック**: A→B 境界で〔流れるプロパティ／丸め・端数規則／スキーマ予約の要否〕を書く。
- **テスト脱一般化**: 「常に〜」禁止。入力区間ごとに期待値固定。境界／退化／収束を必須ケース化。
- **先送り規律**: ロジック先送りとスキーマ先送りを分離。スキーマは今予約する。

### 0.4 プロセス弱点ガード（Claude 再発弱点 W1-11 抜粋）
- 「no-impact／no-regression」と言う前に **call graph 追跡**（W1）。
- **結論と機構を分離**（技術=sandbox 実証／ドメイン=一次資料照合）（W3）。
- 日付・状態・「誰が何をしたか」は **版管理／実物から取得**してから断定（W4）。
- **hotfix 前に根因検討**（症状回避禁止）（W5）。
- 反映後に **自記録の数値で副作用を再検証**＋打ち切り基準（新規構造指摘ゼロ）で停止（W2）。
- 反映前に **対象（文書／コミット／値）を照合**、値は 1 件ずつ出典確認（W10）。

### 0.5 環境ゲート（W9・push 前 CI 全ステップのローカル再現）
- `ruff check` / `pytest` だけでは CI の一部しか再現しない。**push 前に CI（`.github/workflows/ci.yml`）の全 9 ステップをローカルで通す**:
  1. `ruff check tools/`  2. `ruff format --check tools/`  3. `pytest`（全 workspace）  4. `python tools/validate/validate-all.py`
  5. `python tools/parse/verify.py --path data`  6. `python tools/scripts/fix-phase-tags.py --path data/v0.2 --check-only`
  7. `python tools/embed/build-v0.2-corpus.py --validate-only`  8. `python tools/scripts/check-cp932-safe.py --path tools`（em-dash `—`/U+2014 等の cp932-unsafe 検出。FU-505 の鬼門）
  9. schema drift（`python tools/shared/scripts/export-schema.py` + `git diff --exit-code schema/`）
- 特に **8（cp932）・2（format）・9（schema drift）は `ruff check`/`pytest` では拾えない独立ステップ**。NUL byte／末尾整合／MAX_PATH も併せて担保（→ §10.2 と一体運用）。

### 0.6 現行性
- 税率・閾値・施行日は将来課題に棚上げせず、**e-Gov／総務省／都主税局／裁判所の一次情報で確認してからロック**。

### 0.7 自動化の線引き
- **L1 構造化／L2 検証 = round-trip ＋ 不変条件ゲートで自動可**（人間介在 O(1)）。
- **L3 解釈（訳の質／判例選定／法務／戦略）= 人間残余**・draft フラグ・本流を止めない。**L3 を人間レビュー無しで本番投入しない**。自動化は最後、オーナーは降りない。

---

## 1. プロジェクトの目的

**JuriCode-JP** は、日本の法令を AI/LLM 時代に最適化されたフォーマットで構造化し、判例リンクと英訳併記を伴ったオープンな法令データ基盤として提供する LegalTech イニシアティブです。

- **主体**: 株式会社CHOKAI (CHOKAI Co.,Ltd.)
- **ライセンス**: MIT (法令本文・判例情報は引用範囲、構造化レイヤーがMIT)
- **哲学**: *Treating legislation as code. One commit at a time.*

段階的フォーカス戦略を採用しています。

| Phase | 期間 | 対象 |
|---|---|---|
| Phase 1 | 2026-2027 | 憲法 + 警察関連 + 行政 + 民法 + 税法 (四本柱完成) |
| Phase 2 | 2027-2028 | 商法・会社法 ほか民事・商事法令 |
| Phase 3 | 2028-2030 | 全領域(労働法・知財・行政個別法など) |

canonical corpus は `data/v0.2/` (Phase 1 四本柱 + Phase 2・3 の一部を bulk-ingest 先取り投入)。全法令が `_source-manifest.json` で round-trip 検証済、v0.1 corpus は `archive/v0.1/` に deprecate。**現況の条数・法令数・進捗は固定値を本ファイルに書かず `docs/strategy.md` / `_SESSION_BRIEFING.md` を参照**。

---

## 2. リポジトリ構成

```
JuriCode-JP/
├── CLAUDE.md              # AIアシスタント向けガイド(このファイル)
├── README.md              # プロジェクト紹介(人間向け入り口)
├── LICENSE                # MIT
├── .gitignore
├── docs/                  # プロジェクト方針・仕様文書
│   ├── README.md
│   ├── format-spec.md     # 法令データフォーマット仕様(★最重要)
│   ├── ir-spec.md         # 中間表現(Pydantic IR)詳細仕様
│   ├── architecture.md    # 全体アーキテクチャ(6 段階パイプライン)
│   ├── tag-vocabulary.md  # メタタグ標準語彙(5 カテゴリ)
│   ├── strategy.md        # 段階戦略
│   ├── differentiation.md # 先行OSSとの関係
│   ├── glossary.md        # 日英対訳用語集
│   └── follow-ups.md      # 既知の改善余地・将来タスク (P1〜P3) ★レビュー由来
├── schema/                # JSON Schema(構造検証用): law-frontmatter / article / case-link
├── data/                  # 構造化済み法令データ(本体)。条数・法令数は strategy.md 参照
│   ├── README.md
│   └── v0.2/                     # ★ canonical corpus (各法令に _source-manifest.json)
│       ├── phase1-foundational/      # 憲法
│       ├── phase1-police/            # 刑法・刑訴法・警察法・警職法・道交法・軽犯罪法・ストーカー規制法・風営法・犯収法
│       ├── phase1-administrative/    # 地方自治法・行政手続法・行政不服審査法・個保法・公文書管理法・情報公開法・国家公務員法・地方公務員法・デジタル社会形成基本法
│       ├── phase1-practitioner/      # 民法・借地借家法
│       ├── phase1-tax/               # 国税通則法・法人税法・所得税法・消費税法・相続税法・地方税法
│       ├── phase2-commercial/        # 商法・会社法・独占禁止法・金商法関連 (Phase 2 先取り)
│       ├── phase3-labor/             # 労働基準法 (Phase 3 先取り)
│       └── phase3-pharma/            # 薬機法・薬機法施行規則 (Phase 3 先取り)
├── archive/v0.1/          # v0.1 deprecate corpus (参照のみ、CI 対象外)
├── build/chunks/          # retrieval 用 chunks (各号 chunks 含む Option A 設計)
├── cache/laws/            # e-Gov XML cache (.gitignore で公開リポ除外)
├── business/              # 内部資料 (.gitignored、 code-reviews / strategy 等)
├── examples/              # スキーマを満たすサンプル法令
│   ├── README.md
│   └── keihou/            # 刑法のサンプル
│       └── keihou-article-36.md   # ★ フォーマット正規参考例
├── tools/                 # 取得・変換・検証スクリプト
│   ├── README.md
│   ├── shared/            # juricode_shared (Pydantic IR / safe_write / paths / ids / frontmatter)
│   ├── fetch-egov/        # e-Gov法令APIからの取得 + bulk-ingest (PHASE_MAP)
│   ├── parse/             # XML → IR Markdown (parse-egov.py / verify.py / _canonicalize.py) + NTA 通達パーサ
│   │   └── v0.2/          # segment-aware parser (segment_parser.py 他) + manifest/ (_source-manifest.json 生成)
│   ├── validate/          # IR / frontmatter / filename 検証 (CI で稼働中)
│   ├── translate/         # 英訳補助 (Claude APIなど、FU-107 で MVP 予定)
│   ├── embed/             # embedding 生成 (Gemini) + retrieve (hybrid + reranker)
│   ├── finetune/          # reranker fine-tune + 学習データ生成 (柱1 用)
│   ├── search-ui/         # Flask 検索 UI (柱5 質問ログ UI の基盤)
│   └── export/lawsy-bq/   # 源内 Lawsy-Custom-BQ exporter (NLnet M5 €5,000、FU-P0-3)
├── .github/               # Issue/PR テンプレート + workflows/ci.yml (CI 稼働中)
└── awards/                # 応募準備・内部メモ(.gitignoreで公開リポから除外)
```

**`awards/` の扱い**: Tokyo Award 等の応募準備資料を置く内部作業ディレクトリ。`.gitignore` で公開リポジトリには含めない。AIアシスタントは、公開向けデータ作成中は `awards/` 配下を参照・引用しないこと。

---

## 3. 法令データの書き方(★最重要セクション)

詳細仕様は `docs/format-spec.md` を、検証用スキーマは `schema/` を参照してください。
ここでは AI アシスタントが頻繁に参照する要点だけを書きます。

### 3.1 ファイル命名規則

- 法令ごとに1ディレクトリ。ディレクトリ名は法令略称(ローマ字、ハイフン区切り、小文字)
- 条文ごとに1ファイル。ファイル名形式: `[law-abbrev]-article-[N].md`
- 例: `data/phase1-police/keihou/keihou-article-36.md`

法令略称ローマ字の対応表:

| 法令名 | 略称ディレクトリ |
|---|---|
| 日本国憲法 | `kenpou` |
| 刑法 | `keihou` |
| 刑事訴訟法 | `keiji-soshou-hou` |
| 警察法 | `keisatsu-hou` |
| 警察官職務執行法 | `keisatsukan-shokumu-shikkou-hou` |
| 民法 | `minpou` |
| 商法 | `shouhou` |
| 会社法 | `kaisha-hou` |
| 国税通則法 | `kokuzei-tsuusoku-hou` |
| 法人税法 | `houjin-zei-hou` |
| 所得税法 | `shotoku-zei-hou` |
| 消費税法 | `shouhi-zei-hou` |

新法令を追加するときは `docs/glossary.md` に略称を登録してから作業すること。

### 3.2 ファイルの全体構造

`examples/keihou/keihou-article-36.md` を**正規の参考例**とする。すべての法令ファイルはこの構造（frontmatter → 本文セクション順）に従う。frontmatter フィールドは §3.3、判例は §3.5、完全な実例は上記参考例ファイルを参照（重複を避けここでは骨子のみ）。

```markdown
---
# YAML frontmatter — §3.3 の必須フィールド + 任意フィールド (paragraphs/cases/amendments/tags 等)
---

# 刑法 第36条(正当防衛)

## 原文 (日本語)
### 第三十六条
...

## English Translation
### Article 36
...

## 判例リンク (Case Law)
...

## 改正履歴 (Amendments)
...

## 注記 (Notes)
...
```

### 3.3 frontmatter の必須フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `law_id` | string | e-Gov法令ID(13桁の正規ID) |
| `law_name_ja` | string | 法令名(日本語、正式名称) |
| `law_name_en` | string | 法令名(英語、政府公定訳優先) |
| `article_number` | string | 条番号(必ずクォート)。例: `"36"`, `"36-2"`。pattern: `^[0-9]+(-[0-9]+)*$` |
| `article_id` | string | 条文の一意ID(`[law-abbrev]-art-[N]`) |
| `version_date` | YYYY-MM-DD | 現行条文の施行日 |
| `source_url` | URL | e-Gov 法令APIの参照URL |
| `last_verified` | YYYY-MM-DD | 最後に原典と突き合わせた日 |
| `license` | string | このファイル自体のライセンス(通常 `MIT`) |
| `translation_status` | enum | `official` / `community` / `draft` / `none` |

任意フィールド: `paragraphs`, `cases`, `amendments`, `tags`, `notes`, `parent_section`(編・章・節情報)

### 3.4 本文の原則

- **日本語原文セクション**は e-Gov公式テキストの完全コピー。句読点・送り仮名・漢字いずれも改変禁止。
- **英訳セクション**は政府公定訳(日本法令外国語訳DB)があればそれを優先し、無い場合は `translation_status: draft` を立てて掲載。
- 各項(`第〇項`)は `### 第○項` 見出しを付けて区分けする。
- 但書(ただしがき)、号(各号)は本文ベタ書きで構わないが、Frontmatterの `paragraphs[].has_proviso` を立てる。

### 3.5 判例リンクの書き方

`cases:` フィールドに記載し、本文末尾の「判例リンク」セクションにMarkdown表現を置く。

```yaml
cases:
  - case_id: scj-1969-12-04-keishu-23-12-1573
    court: 最高裁判所第一小法廷
    court_en: Supreme Court of Japan, First Petty Bench
    decision_date: 1969-12-04
    citation: 刑集23巻12号1573頁
    case_name_ja: 急迫不正の侵害の意義
    case_name_en: Meaning of "imminent and unjust infringement"
    url: https://www.courts.go.jp/app/hanrei_jp/detail2?id=...
    relevance: high           # high | medium | low
    relevant_paragraph: 1     # この判例が関連する項番号(任意)
    summary_ja: |
      ...
    summary_en: |
      ...
```

**判例リンクで絶対に守ること**:
- 推測・記憶からの判例追加は厳禁。出典(URL or 掲載誌・巻号)を必ず確認してから追加すること。
- URLは追加時に実際にアクセスして存在確認すること。
- `relevance` は本人の主観で構わないが、`high` の判例は学説・実務での重要性を要する。
- 判例本文・要旨のライセンス（著作権法13条＝PD／要旨は改変禁止＝自前要約）の一覧は `docs/licensing.md` を参照。

---

## 4. 必ず守ること(原則)

### 4.1 法令本文の改変禁止
原文(e-Gov公式テキスト)をそのまま転載する。読みやすさを目的とした句読点追加・漢字変換・要約は**すべて禁止**。構造化のために必要な追加情報(項番号の明示・見出し・注記)は本文ブロックの外に置く。

### 4.2 出典明示の原則
- 法令テキストは必ず `source_url` に e-Gov 法令APIの参照URLを記載
- 判例は裁判所Webサイトのpermalinkを使用、なければ判例情報DBの永続URL

### 4.3 英訳の扱い
- 公定訳優先: 法務省「日本法令外国語訳データベース」(http://www.japaneselawtranslation.go.jp/) の訳がある場合はそれを採用し、`translation_status: official` を立てる
- 公定訳がない場合: `translation_status: draft` または `community` で掲載、`machine_translated: true` を併用してよい
- 英訳の改善はデータ修正とは別PRで歓迎する
- 各ソース（JLT 英訳＝PDL1.0 等）のライセンスの一覧は `docs/licensing.md` を参照。

### 4.4 改正・施行日の追跡
- 法令は頻繁に改正される。`version_date` は現行条文の施行日を明示
- 改正があった場合は `amendments:` に履歴を残し、`version_date` を更新
- 改正前の条文を保持したい場合は `archive/` サブディレクトリへ移動(将来仕様)

---

## 5. やってはいけないこと

- **法令本文の改変・要約・読みやすさ調整** — 構造化のための情報は本文外で。
- **推測による判例追加** — 出典確認のない判例リンクは絶対に追加しない。
- **私的解釈の混入** — 解釈は `## 注記` セクションに、出典付きで。本文や英訳には混ぜない。
- **学習データ提供契約の独断締結** — このリポジトリの法令データは MIT で公開済みだが、第三者LLMベンダーへの「優先提供」「独占学習」契約はプロジェクト合意なしには結ばない。
- **公式改正の反映を待たずに勝手にバージョン更新** — e-Gov公式反映を確認してから `version_date` を更新する。
- **search-ui (質問ログ) の外部公開** — `tools/search-ui/server.py` は質問文を匿名化前の raw で SQLite (`build/search-ui-logs.db`) に記録する。注意書きバナー (柱5 Phase C) と PII フィルタ (柱5 Phase D) が本番投入されるまで、`127.0.0.1` ローカル限定で起動し `--host 0.0.0.0` 等での外部公開を禁止する (柱5 鉄の規律、2026-05-30)。

---

## 6. コミット規約

[Conventional Commits](https://www.conventionalcommits.org/) に準拠。

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

- **type**: `feat` / `fix` / `docs` / `data` / `schema` / `chore` / `refactor` / `test`
- **scope**: 法令略称、または `schema`, `tools`, `docs`, `examples` など

例:
- `data(keihou): add article 36 (正当防衛)`
- `data(keihou/36): add Supreme Court 1969-12-04 case link`
- `schema: require last_verified field`
- `docs(format-spec): clarify proviso handling`

1コミット1論理単位を厳守。法令データの追加と英訳追加は別コミットが望ましい。

---

## 7. ブランチ命名

- 機能追加: `feature/[short-topic]`
- 法令データ追加: `data/[law-abbrev]/article-[N]`
- 修正: `fix/[issue-id-or-topic]`
- スキーマ変更: `schema/[topic]`

`main` への直接pushは原則禁止。PRレビューを経ること(コラボレーター追加後)。

---

## 8. 検証コマンド

実装済 + GitHub Actions CI で稼働中 (`.github/workflows/ci.yml`)。**push 前に通すべき CI 全 9 ステップの正本リストは §0.5**。以下はローカル個別実行例:

```bash
# 全コード lint / format
ruff check tools/
ruff format --check tools/

# 全ワークスペースパッケージの pytest
pytest tools/shared/tests tools/validate/tests tools/parse/v0.2/tests tools/parse/v0.2/manifest/tests

# 全データのスキーマ検証 (data/v0.2/ + examples/ を自動 rglob)
python tools/validate/validate-all.py

# 1ファイルのfrontmatter検証
python tools/validate/validate-file.py data/v0.2/phase1-police/keihou/keihou-article-36.md

# Round-trip hash 検証 (data/v0.2/ 配下の全 manifests を検証)
python tools/parse/verify.py --path data/v0.2

# v0.2 corpus に manifest を再生成 (Phase 1 で 1 度実行済、新法令追加時に再実行)
cd tools/parse/v0.2 && python -m manifest.cli \
    --data-dir ../../../data/v0.2 \
    --cache-dir ../../../cache/laws \
    --parser-version "tools/parse/v0.2/segment_parser.py@0.1.0"

# 判例リンクのURL生存確認 (FU-205、P3 で実装予定)
# python tools/validate/check-case-urls.py
```

---

## 9. 既存OSSとの関係

JuriCode-JPは既存プロジェクトの**置き換えではなく、上に積む**ことで価値を出す。

| プロジェクト | 関係 |
|---|---|
| [gitlaw-jp](https://github.com/aluqas/gitlaw-jp) | Git管理設計思想の参考 |
| [Lawtext](https://github.com/yamachig/Lawtext) | 法令テキストフォーマットの参考、変換ツール候補 |
| [ja-law-parser](https://github.com/takuyaa/ja-law-parser) | e-Gov XML → 中間表現の処理に活用予定 |
| [e-Gov MCP](https://github.com/ryoooo/e-gov-law-mcp) | LLM連携のMCPサーバー、補完関係 |

`docs/differentiation.md` で詳細を扱う。新機能を作る前に、既存OSSで実現できないかを確認すること。

---

## 10. AIアシスタントへの追加ガイダンス

- **不明な法令テキストは推測しない**。e-Gov法令APIから取得するか、ユーザに確認を求める。
- **判例情報は記憶からは出さない**。最高裁判決でも、必ず citation と URL を確認してから記載する。
- **大量の条文を一気に生成しない**。1コミットあたり1〜数条程度に留め、検証を挟む。
- **英訳の質より出典の明示を優先**。draft訳でも公定訳でも、由来を明らかにすること。
- **ユーザに対しては「法律相談」を行わない**。このリポジトリは法令データ基盤であり、個別事案へのアドバイスは提供しない。

### 10.1 コーディング原則 (バイブコーディング 3 原則、2026-05-25 採用)

AI との共作前提のコードは下記 3 原則を厳守する。詳細 + 実装事例: `business/v02-corpus-quality-investigation-2026-05-25.md` §0.5。

1. **コンポーネントの「責任」が明確**: 1 ファイル 1 責務、1 関数 50 行以下、引数 5 個以下 (SOLID)
2. **型 (Type) が厳格**: Python 3.11+ type hints 必須、戻り値の dict 化禁止 → Pydantic `BaseModel` (`extra="forbid"` + `frozen=True`) または `@dataclass(frozen=True)`
3. **「なぜ (Why)」が記述**: Google-style docstring に `Why:` セクション必須

commit 前に 4 観点で自己レビュー: (1) SOLID リファクタリング (2) エッジケース + 堅牢性 (3) 可読性 + AI フレンドリー度 (4) パフォーマンス + セキュリティ。

### 10.2 JuriCode-JP 固有の必須ルール

- **`safe_write_text` / `safe_write_jsonl` / `safe_append_jsonl_records` 必須** (`juricode_shared.safe_write` 経由、FU-302)。直接 `open(path, 'w').write()` は禁止 (NUL padding / 末尾切断事故源)
- **`defusedxml` 優先** (XXE / billion-laughs 防御)。stdlib fallback には `RuntimeWarning` を出す
- **path traversal 防御**: `ABBREV_PATTERN` (parse-egov.py:57) / `SAFE_FILENAME_RE` (verify.py:65) の正規表現を使う
- **`ruff format` は Windows 側で実行**: WSL `/mnt/c/` からの ruff format は corruption 事故源 (2026-05-22 5 ファイル同時 corrupt)
- **`--import-mode=importlib`**: 同名 `tests/` パッケージ衝突回避のため `pyproject.toml` で設定済 (新規 tests/ ディレクトリ追加時に動作確認)
- **新規モジュールに `tests/test_*.py` 同時作成**: TDD でなくても unit test 必須

### 10.3 作業環境の役割分担 (2026-05-27 採用)

ソースコード作業は二層運用: **実装は OS native の CLI 環境**、**計画策定・レビュー・ドキュメント管理は別の作業環境**で行う。詳細な運用ルールは非公開の運用ガイドで管理し、本リポは要点のみ記す。

- **実装環境 (CLI) で行う作業**: 新規実装 / refactoring / pytest + ruff iterate ループ / git 操作 / 多 file 一括置換 / debug loop (OS native 実行)。
- **計画環境で行う作業**: 計画書策定 (`business/`) / planning-checklist 通過確認 / レビュー / `docs/follow-ups.md` 更新 / memory 累積 / scheduled task。
- **ファイル所有権の境界**:
  - 計画環境専有: `business/` (gitignored)、運用ガイド側ファイル
  - 実装環境専有: `tools/` 配下のコード、`data/v0.2/` corpus、`.github/workflows/`、`tests/`
  - 両方触ってよい (但し同時編集禁止): `docs/follow-ups.md`、`CLAUDE.md`、`README.md`、`pyproject.toml`
- **ハンドオフ**: 計画環境で計画書策定 → execution briefing 生成 → 実装環境で実装 + commit + push + PR → merge 後に docs/memory/briefing 更新。
- **例外的に計画環境で docs を直接編集した場合**: 作業後に `wc -l` + `tail -3` + NUL byte count で末尾整合性を verify する。

---

## 11. 既知の改善余地・コードレビュー履歴

実装の質を保つため、以下のドキュメントを**作業開始前に必ず確認**すること.

### 11.1 公開フォローアップトラッカー

- **[docs/follow-ups.md](./docs/follow-ups.md)** — P0〜P3 の改善タスク. Phase 1 ロールアウト gate-keeper (P0)、Phase 1 着手前 (P1)、Phase 1 中期 (P2)、後期 / Phase 2 検討 (P3) に整理.
- 新規実装に着手する前にこのファイルを開き、関連する FU-xxx 項目があれば**併せて解消**するのが推奨ワークフロー.
- 解消したら同ファイル末尾の「完了済み」セクションに timestamp 付きで移動 + コミットハッシュ記録.

### 11.2 内部コードレビュー履歴

- **`business/code-reviews/YYYY-MM-DD-*.md`** に Tier 1〜4 観点でのレビュー結果を記録 (gitignore 対象、外部非公開).
- 新規 PR を出す前に直近のレビュー文書の該当 Tier (とくに Tier 1 = 設計ロックイン、Tier 4 = spec 整合) を一読すること.
- レビュー由来の改善は (a) コード修正 (b) `docs/follow-ups.md` への移行 (c) `business/code-reviews/` 側にも「DONE 2026-MM-DD」マーカー追記、の 3 点セットで完了とする.

### 11.3 履歴（最新数件のみ。全件の完了記録は `docs/follow-ups.md` / `business/code-reviews/` を正本とする）

| 日付 | sprint / 文書 | 成果 |
|---|---|---|
| 2026-05-18〜25 朝 | code-review 4 本 (tools&schema / v0.2 parser / full-tools) + v0.2.1 release + P0 sprint | FU-301..321 / FU-401..431 を `docs/follow-ups.md` に転載、P0 8/8 消化。詳細は `business/code-reviews/` |
| 2026-05-25 夕方 | FU-108 v0.2 manifest sprint | `tools/parse/v0.2/manifest/` 新設 + 全 manifests 生成 + v0.1 を `archive/v0.1/` に deprecate + CI を data/v0.2/ に切替 |
| 2026-05-26 | FU-415 phase tag sweep + FU-501..503 docs 訂正 | `fix-phase-tags.py` + `juricode_shared/phase_tag.py` 新設・全 phase tag swept、CI green 維持。planning learnings を `business/planning-checklist.md` (gitignored) に構造化 |
| 2026-06〜 | 税務深掘り (FU-514/519/520/521 基本通達ほか) 等 | **完了記録は `docs/follow-ups.md` の各 FU エントリ / 完了済みセクションを正本とする** |

---

### 11.4 計画書作成チェックリスト (内部、gitignored)

- **`business/planning-checklist.md`** — 大きめ sprint (sweep / migration / refactor / 新機能) の計画書を書く前に必ず開いて、過去の planning failure 由来の learnings を全項目通過させてから着手する内部チェックリスト. 4 つの主要項目を収録 (call graph 追跡 / post-merge dry-run / MERGE FIRST 明示 / 主張を控えめに).
- 新たな learning が見つかったら同ファイル末尾の §99 履歴に timestamp 付きで追記し、次以降の sprint で活かす. 累積知識のリビング・ドキュメント.
- 2026-05-26 FU-415 §1.8 overstatement 由来. 詳細は `business/fu-415-followup-fixes-plan-2026-05-26.md` §6 + PR #2 (commit `dcc3b67f`) 参照.

---

## 12. 連絡先・参考リンク

- 公式リポジトリ: https://github.com/JuriCode-JP/JuriCode-JP
- 主催: CHOKAI Co.,Ltd. (Tokyo, Japan)
- 関連プロジェクト: legalize.dev (国際比較法学プラットフォーム、32カ国目として参加予定)
- 公式データ: e-Gov 法令API (https://laws.e-gov.go.jp/) / 裁判所Webサイト (https://www.courts.go.jp/)

---

*Last updated: 2026-06-25 (棚卸し・圧縮パス: 全ルール・キーワード〔不変条件ゲート／Tier／環境ゲート9ステップ／cp932／safe_write／バイブコーディング3原則／PR規約 等〕を保持したまま、陳腐化した動的情報〔corpus 条数・法令数・tests 数等→strategy.md/BRIEFING へポインタ化〕・§11.3 履歴表の古い完了行・§3.2 の frontmatter 重複・§10 重複箇条を圧縮. 前回: 2026-06-20 §0 判断・検証の共通OS〔選択的厳密性とAI検証〕統合)*

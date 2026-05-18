# CLAUDE.md — AI Assistant Guide for JuriCode-JP

このファイルは、Claude等のAIアシスタントがこのリポジトリで作業するときに、最初に必ず読むべきガイドです。
人間のコントリビューターは `README.md` と `docs/` から読み始めてください。

---

## 1. プロジェクトの目的

**JuriCode-JP** は、日本の法令を AI/LLM 時代に最適化されたフォーマットで構造化し、判例リンクと英訳併記を伴ったオープンな法令データ基盤として提供する LegalTech イニシアティブです。

- **主体**: 株式会社CHOKAI (CHOKAI Co.,Ltd.)
- **ライセンス**: MIT (法令本文・判例情報は引用範囲、構造化レイヤーがMIT)
- **哲学**: *Treating legislation as code. One commit at a time.*

段階的フォーカス戦略を採用しています。

| Phase | 期間 | 対象 |
|---|---|---|
| Phase 1 | 2026-2027 | 警察関連法令(刑法・刑訴法・警察法など) |
| Phase 2 | 2027-2028 | 民事・商事法令 |
| Phase 3 | 2028-2030 | 全領域(行政法・税法・労働法など) |

詳細は `docs/strategy.md` を参照してください。

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
├── schema/                # JSON Schema(構造検証用)
│   ├── README.md
│   ├── law-frontmatter.schema.json
│   ├── article.schema.json
│   └── case-link.schema.json
├── data/                  # 構造化済み法令データ(本体)
│   ├── README.md
│   └── phase1-police/     # 警察関連法令(Phase 1)
│       └── README.md
├── examples/              # スキーマを満たすサンプル法令
│   ├── README.md
│   └── keihou/            # 刑法のサンプル
│       └── keihou-article-36.md   # ★ フォーマット正規参考例
├── tools/                 # 取得・変換・検証スクリプト(順次実装中)
│   ├── README.md
│   ├── fetch-egov/        # e-Gov法令APIからの取得
│   ├── parse/             # XML → 中間表現
│   ├── validate/          # スキーマ・データ検証
│   └── translate/         # 英訳補助(Claude APIなど)
├── .github/               # Issue/PRテンプレート(CI将来)
│   ├── ISSUE_TEMPLATE/
│   │   ├── config.yml
│   │   ├── data-correction.yml
│   │   ├── new-law-request.yml
│   │   └── translation-fix.yml
│   └── PULL_REQUEST_TEMPLATE.md
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

新法令を追加するときは `docs/glossary.md` に略称を登録してから作業すること。

### 3.2 ファイルの全体構造

`examples/keihou/keihou-article-36.md` を**正規の参考例**とする。すべての法令ファイルはこの構造に従う。

```markdown
---
# YAML frontmatter(構造化メタデータ)
law_id: 140AC0000000045
law_name_ja: 刑法
law_name_en: Penal Code
article_number: "36"
article_id: keihou-art-36
version_date: 2007-06-12
source_url: https://laws.e-gov.go.jp/law/140AC0000000045
source_format: e-gov-xml
last_verified: 2026-05-14
license: MIT
machine_translated: false
translation_status: official  # official | community | draft | none
paragraphs:
  - number: 1
    has_proviso: false
  - number: 2
    has_proviso: false
cases:
  - case_id: ...
    ...
amendments:
  - effective_date: ...
    ...
tags:
  - phase1-police
  - 正当防衛
  - 違法性阻却事由
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

(将来 `tools/validate/` 実装後)

```bash
# 全データのスキーマ検証
python tools/validate/validate-all.py

# 1ファイルのfrontmatter検証
python tools/validate/validate-file.py data/phase1-police/keihou/keihou-article-36.md

# 判例リンクのURL生存確認
python tools/validate/check-case-urls.py
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

---

## 11. 既知の改善余地・コードレビュー履歴

実装の質を保つため、以下のドキュメントを**作業開始前に必ず確認**すること.

### 11.1 公開フォローアップトラッカー

- **[docs/follow-ups.md](./docs/follow-ups.md)** — P1〜P3 計 15 件の改善タスク. Phase 1 着手前に潰すべき項目 (P1)、Phase 1 中期 (P2)、後期 / Phase 2 検討 (P3) に整理.
- 新規実装に着手する前にこのファイルを開き、関連する FU-xxx 項目があれば**併せて解消**するのが推奨ワークフロー.
- 解消したら同ファイル末尾の「完了済み」セクションに timestamp 付きで移動 + コミットハッシュ記録.

### 11.2 内部コードレビュー履歴

- **`business/code-reviews/YYYY-MM-DD-*.md`** に Tier 1〜4 観点でのレビュー結果を記録 (gitignore 対象、外部非公開).
- 新規 PR を出す前に直近のレビュー文書の該当 Tier (とくに Tier 1 = 設計ロックイン、Tier 4 = spec 整合) を一読すること.
- レビュー由来の改善は (a) コード修正 (b) `docs/follow-ups.md` への移行 (c) `business/code-reviews/` 側にも「DONE 2026-MM-DD」マーカー追記、の 3 点セットで完了とする.

### 11.3 履歴

| 日付 | レビュー文書 | 主な指摘範囲 |
|---|---|---|
| 2026-05-18 | `business/code-reviews/2026-05-18-tools-and-schema-review.md` | tools/shared (Pydantic IR) / tools/validate / schema export / pyproject root / CI workflow. 18 件 (P0×3 即修正、P1×5 / P2×5 / P3×5 は `docs/follow-ups.md` に転載) |

---

## 12. 連絡先・参考リンク

- 公式リポジトリ: https://github.com/JuriCode-JP/JuriCode-JP
- 主催: CHOKAI Co.,Ltd. (Tokyo, Japan)
- 関連プロジェクト: legalize.dev (国際比較法学プラットフォーム、32カ国目として参加予定)
- 公式データ: e-Gov 法令API (https://laws.e-gov.go.jp/) / 裁判所Webサイト (https://www.courts.go.jp/)

---

*Last updated: 2026-05-18 (added §11 follow-up tracker and code review history index)*

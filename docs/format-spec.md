# JuriCode-JP 法令データフォーマット仕様 (v0.1 draft)

最終更新: 2026-05-14 / ステータス: **Draft v0.1**(Phase 1の実データ整備中に固める)

このドキュメントは JuriCode-JP リポジトリで採用する**法令データの正規フォーマット**を定義する。
スキーマ検証用のJSON Schemaは `/schema/` に、参照実装サンプルは `/examples/keihou/keihou-article-36.md` にある。

---

## 1. 設計原則

1. **AI/LLM最適化** — 1ファイル=1条文、フロントマター + Markdown本文。LLMが単一チャンクで条文・項・判例・英訳を同時に把握できる。
2. **Diffability** — 条文・判例・英訳がプレーンテキストでバージョン管理され、改正履歴がgit logで追える。
3. **多言語併記** — 日本語原文と英訳を同一ファイル内で並列保持。今後の多言語追加時はセクション追加で拡張。
4. **検証可能性** — frontmatter は JSON Schema で機械検証可能。出典(URL・施行日)を必須項目に含める。
5. **原典忠実性** — 法令本文は e-Gov 公式テキストの完全コピーとし、改変・要約・修辞を一切加えない。

---

## 2. 単位(1ファイル=何にするか)

JuriCode-JPは**1ファイル=1条**を基本単位とする。

### 単位選定の比較

| 単位案 | 長所 | 短所 | 採否 |
|---|---|---|---|
| 1法令=1ファイル | 編集が一括 | 巨大化、判例リンクが薄まる、LLMチャンク不適 | ✗ |
| 1条=1ファイル | LLMチャンク最適、判例リンクが密、diffが細かい | ファイル数が多い | **○(採用)** |
| 1項=1ファイル | さらに細粒度 | 条文の文脈が壊れる、判例は条単位が多い | ✗ |

例外: 短い法令(例: 条文10条以下)は 1法令=1ファイルとしてもよい。ただし将来分割しやすいよう、各条を `## 第N条` で見出し分割すること。

---

## 3. ディレクトリ・ファイル命名

```
data/
└── phase1-police/
    └── keihou/                          # 法令略称ローマ字
        ├── _meta.yaml                   # 法令全体メタデータ(任意)
        ├── README.md                    # 法令の概要・収録状況
        ├── keihou-article-1.md
        ├── keihou-article-36.md
        └── ...
```

- ファイル名: `[law-abbrev]-article-[N].md`
- N は半角アラビア数字。枝番付き条(36条の2など)は `keihou-article-36-2.md`
- 法令略称は `docs/glossary.md` に登録されているローマ字短縮名を使用

---

## 4. YAML frontmatter 仕様

### 4.1 必須フィールド

| フィールド | 型 | 説明 | 例 |
|---|---|---|---|
| `law_id` | string | e-Gov法令ID(13桁の正規ID) | `132AC0000000045` |
| `law_name_ja` | string | 法令正式名称(日本語) | `刑法` |
| `law_name_en` | string | 法令正式名称(英語、公定訳優先) | `Penal Code` |
| `article_number` | string | 条番号 | `"36"`, `"36-2"` |
| `article_id` | string | 条文の一意ID | `keihou-art-36` |
| `version_date` | YYYY-MM-DD | 現行条文の施行日 | `2025-06-01` |
| `source_url` | URL | e-Gov 法令APIまたは該当条文ページのURL | `https://laws.e-gov.go.jp/law/132AC0000000045#Mp-Pa_1-Ch_7-At_36` |
| `last_verified` | YYYY-MM-DD | 原典との突き合わせを最後に行った日 | `2026-05-14` |
| `license` | string | このファイルのライセンス | `MIT` |
| `translation_status` | enum | 英訳の信頼度 | `official` / `community` / `draft` / `none` |

### 4.2 推奨フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `parent_section` | object | 編・章・節情報。`{hen, shou, setsu, kan}` の形 |
| `paragraphs` | array | 項のメタデータ(後述) |
| `cases` | array | 判例リンク(後述) |
| `amendments` | array | 改正履歴(後述) |
| `tags` | array of string | フリータグ。例: `["正当防衛", "違法性阻却事由", "phase1-police"]` |
| `machine_translated` | boolean | 英訳がMT由来か |
| `notes` | string | 構造化注記(法令工学的に重要な点) |

### 4.3 paragraphs(項のメタデータ)

```yaml
paragraphs:
  - number: 1
    has_proviso: false        # 但書を含むか
    has_items: false          # 各号(列挙)を含むか
    is_added_by_amendment: false  # 改正で追加された項か
  - number: 2
    has_proviso: false
    has_items: false
```

条全体が1項のみの場合は省略可能。

### 4.4 cases(判例リンク)

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
    relevant_paragraph: 1     # 該当する項番号(任意)
    summary_ja: |
      最高裁が「急迫不正の侵害」の意義について判示した事例。
    summary_en: |
      ...
```

**`case_id` の命名規則**:
- 最高裁: `scj-YYYY-MM-DD-[citation-shortcode]`
  - 例: `scj-1969-12-04-keishu-23-12-1573`
- 高裁: `hcj-[city]-YYYY-MM-DD-...`
- 地裁: `dcj-[city]-YYYY-MM-DD-...`

### 4.5 amendments(改正履歴)

```yaml
amendments:
  - effective_date: 2025-06-01
    law_no: 令和4年法律第67号
    summary: 懲役・禁錮を「拘禁刑」に統一する刑法改正の施行
    diff_summary: |
      旧文「死刑又は無期若しくは…の懲役」→ 新文「死刑又は無期若しくは…の拘禁刑」
```

### 4.5.1 Phase 1 スコープ(2026-05-18 確定)

**Phase 1(2026-2027)で扱う改正履歴の範囲を以下に明示する**:

| 項目 | Phase 1 の方針 |
|---|---|
| **格納対象** | **その条文に直接適用された改正のみ**(法令全体の改正ではなく、当該条文に影響した改正だけ) |
| **過去遡及** | **直近 5 年程度**(2020 年以降の改正を目安)、それ以前の改正は対象外 |
| **改正前の条文本文** | **保持しない**(`amendments[].diff_summary` で要点のみ記載、本文の旧版テキストは Phase 1 では非収録) |
| **過去版アーカイブ** | `data/phase1-police/{law-abbrev}/archive/` ディレクトリは Phase 1 では使用しない(将来仕様、Phase 2 以降で検討) |
| **改正記録の出典** | e-Gov 法令 API v2 `GET /law_revisions/{law_id_or_num}` のレスポンスから自動抽出する |
| **必須性** | `amendments` は**任意フィールド**(改正履歴がない条文では空配列または省略可) |

### 4.5.2 拡張(Phase 2 以降)

- 全改正履歴の保持(`archive/` ディレクトリの活用)
- 改正前後の本文 diff の構造化(Phase 2 で `tools/transform/diff-builder/` 検討)
- 改正法令本体へのリンク(改正法令側 JuriCode-JP データへのクロスリンク)

### 4.5.3 推奨

- 「**現行版**」の条文ファイル 1 つで Phase 1 の MVP は完結する
- 過去版を参照したいユーザーは e-Gov 法令 API v2 の `asof` パラメータで直接取得可能(`tools/fetch-egov` で対応済)
- これは「源内 Lawsy への上位データ層」要件として十分

---

## 5. 本文構造(Markdown)

frontmatter以下の本文は、以下のセクション順で記述する。

```markdown
# 刑法 第36条(正当防衛)

## 原文 (日本語)

### 第三十六条
急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。

### 第三十六条第二項
防衛の程度を超えた行為は、情状により、その刑を減軽し、又は免除することができる。

## English Translation

> **Note**: This translation is the official translation provided by the Ministry of Justice...

### Article 36 (Paragraph 1)
An act unavoidably performed to protect the rights of oneself or another person against imminent and unjust infringement shall not be punishable.

### Article 36 (Paragraph 2)
An act exceeding the limit of defense may be subject to a reduction or remission of punishment in accordance with the circumstances.

## 判例リンク (Case Law)

- **[最判 1969-12-04 刑集23巻12号1573頁]** 急迫不正の侵害の意義
  - 該当: 第1項
  - 関連度: high
  - 概要: ...
  - URL: https://www.courts.go.jp/app/hanrei_jp/detail2?id=...

## 改正履歴 (Amendments)

- **2025-06-01** (令和4年法律第67号)
  - 懲役・禁錮を「拘禁刑」に統一する刑法改正の施行
  - 第36条本文には影響なし(刑罰部分でないため)

## 注記 (Notes)

- 第1項は違法性阻却事由としての正当防衛、第2項は責任阻却・違法性減少事由としての過剰防衛を規定する。
- 学説上、急迫性・防衛の意思・相当性の3要件が議論される。
```

### 5.1 セクション順序(固定)

1. `# 法令名 第N条(通称)` — H1見出し
2. `## 原文 (日本語)` — 必須
3. `## English Translation` — 推奨(なしの場合は `translation_status: none`)
4. `## 判例リンク (Case Law)` — 任意
5. `## 改正履歴 (Amendments)` — 直近の改正があれば記載
6. `## 注記 (Notes)` — 任意

---

## 6. 検証

### 6.1 機械検証

```bash
# frontmatter のスキーマ検証
python tools/validate/validate-file.py [path-to-md]

# 全データ検証
python tools/validate/validate-all.py
```

### 6.2 人間レビュー必須項目

- 法令本文が e-Gov 公式テキストと**1字一句一致**しているか
- `source_url` のリンクが生きているか
- 判例の citation が正確か(掲載誌・巻号・頁)
- 英訳の出典(政府公定訳/コミュニティ訳/draft)が明示されているか

---

## 7. 将来拡張

- **多言語追加**: 中国語・韓国語等は `## Translation (zh-CN)` のようなセクション追加で対応
- **チャンクメタデータ**: `chunks:` フィールドにLLM向けの埋め込み用テキストを生成して格納(別ファイル化検討)
- **改正版アーカイブ**: 旧版条文を `archive/keihou/keihou-article-36@2024-01-01.md` のように保持
- **法令間リンク**: `references:` フィールドで他条文・他法令への参照を構造化

これらは Phase 1完了時点で再評価する。

---

## 8. 仕様の改訂方針

- 仕様変更は必ず PR で行い、`docs:` または `schema:` スコープでコミットする
- バージョンは セマンティック・バージョニング: `v0.1` → `v0.2` (フィールド追加) → `v1.0` (Phase 1完了時固定)
- 破壊的変更は `data/` 全体のマイグレーションを伴うため、Phase境界でのみ実施する

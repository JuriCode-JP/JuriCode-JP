# JuriCode-JP 法令データフォーマット仕様 v0.2

**バージョン:** v0.2 Draft v1.0
**作成日:** 2026-05-22
**ステータス:** Draft (parser 実装と並行して育てる)
**先行版:** `docs/format-spec.md` (v0.1)
**前提文書:** `business/japanese-law-rag-design-blueprint-2026-05-22.md`

---

## 0. v0.1 からの主な変更

| 項目 | v0.1 | v0.2 |
|---|---|---|
| ファイル単位 | 1 条 = 1 file | **維持** (Option A 採用、2026-05-22 決定) |
| frontmatter `paragraphs[]` | number / has_proviso / has_items | **`segments[]` を追加** |
| 本文 Markdown | `### 第N項` | `### 第N項` + segment 見出し `### 第N項 本文 / ただし書 / 第M号` |
| segment 構造 | なし | 前段/後段、本文/ただし書、柱書/各号、にかかわらず、準用 を構造化 |
| modality flag | なし | 義務 / 権限 / 禁止 / 努力義務 を frontmatter で明示 |
| 数量条件 | なし | `quantitative_conditions[]` で metadata 化 |
| override 表現 | なし | `override_flag` + `override_target[]` |
| retrieval 出力 | (なし、.md を直接 embed) | parser が `.chunks.jsonl` を別途生成 |

v0.1 の必須/推奨フィールドは v0.2 でも維持。**後方互換** (v0.1 を読むコードは v0.2 でも動く)。

---

## 1. ファイル単位の決定 (Option A)

```
data/v0.2/{phase}/{law}/{law}-article-{N}.md         ← 人間用 (v0.1 互換)
build/chunks/{law}/{law}-article-{N}.chunks.jsonl    ← retrieval 用 (parser 自動生成)
```

- `.md` は git に commit、人間が読み書きする「真実」
- `.chunks.jsonl` は parser の build artifact、CI で再生成可能
- Phase 1 では `.chunks.jsonl` も git に含める (利用者の負担最小化)。Phase 2 で .gitignore 化を検討

---

## 2. YAML frontmatter v0.2

### 2.1 v0.1 互換フィールド (変更なし)

`law_id`, `law_name_ja`, `law_name_en`, `article_number`, `article_id`, `version_date`,
`source_url`, `source_format`, `last_verified`, `license`, `translation_status`,
`machine_translated`, `parent_section`, `cases`, `amendments`, `tags`, `notes`

### 2.2 `paragraphs[]` の v0.2 拡張

```yaml
paragraphs:
  - number: 1
    has_proviso: true        # 既存 (v0.2 では正しく検出)
    has_items: false         # 既存 (v0.2 では正しく検出)
    is_added_by_amendment: false  # 既存
    segments:                # ★v0.2 新規
      - id: art-415-p1-honbun
        type: honbun
        text: '債務者がその債務の本旨に従った履行をしないとき…損害の賠償を請求することができる。'
        modality: kanou_kenri    # する権利あり (することができる)
      - id: art-415-p1-tadashi
        type: tadashi
        text: 'ただし、その債務の不履行が…この限りでない。'
        modality: jogai          # 例外
```

### 2.3 segment の `type` 列挙

| type | 意味 | 検出ヒント |
|---|---|---|
| `simple` | 単一ルール、段分割なし | 「ただし、」「次に掲げる」を含まない |
| `honbun` | 本文 | (tadashi と対) |
| `tadashi` | ただし書 | 「ただし、」で始まる |
| `zen_dan` | 前段 | 1 つの項を「。」で区切った前半 |
| `kou_dan` | 後段 | 「この場合において」「前段の場合において」で始まることが多い |
| `hashira` | 柱書 | 「次に掲げる」「次の各号」を含む、号より前の文 |
| `kou` | 号 | `item_number` も必須 |
| `tokusoku` | 特則 | 「にかかわらず」を含む、override 性質 |
| `junyou` | 準用 | 「準用する」を含む |

### 2.4 segment の `modality` 列挙

| modality | 意味 | 検出ヒント |
|---|---|---|
| `gimu` | 義務 | 「しなければならない」 |
| `gimu_negative` | 義務的禁止 | 「してはならない」「しない」(否定) |
| `kanou_kenri` | 権限・裁量 | 「することができる」 |
| `kanou_negative` | 禁止 | 「することができない」 |
| `doryoku_gimu` | 努力義務 | 「努めなければならない」「努める」 |
| `gimu_kei` | 義務的刑罰 | 「処する」 |
| `koka_mukou` | 効果: 無効 | 「無効とする」 |
| `koka_torikeshi` | 効果: 取消し | 「取り消すことができる」 |
| `jogai` | 例外 | 「この限りでない」 |
| `unspecified` | 不明 / 該当なし | (上記いずれにも該当しない) |

### 2.5 segment の追加フィールド

```yaml
segments:
  - id: art-23-p6
    type: tokusoku
    text: '輸入品に係る…第一項の規定にかかわらず、税関長に対し、するものとする。'
    modality: gimu
    override_flag: true                       # ★にかかわらず
    override_target: [kokuzei-tsuusoku-hou-art-23-p1-hashira]

  - id: art-23-p7
    type: junyou
    text: '前二条の規定は、更正の請求について準用する。'
    applies_provisions:                       # ★準用先 (絶対参照化済み)
      - kokuzei-tsuusoku-hou-art-21
      - kokuzei-tsuusoku-hou-art-22

  - id: art-23-p1-hashira
    type: hashira
    text: '納税申告書を提出した者は、次の各号のいずれかに該当する場合には、…五年(法人税については十年)以内に限り…'
    quantitative_conditions:                  # ★数量境界
      - type: period
        normal: { value: 5, unit: years }
        exception: { value: 10, unit: years, condition: '法人税に係る場合' }

  - id: art-415-p2-hashira
    type: hashira
    text: '前項の規定により損害賠償の請求をすることができる場合において…'
    references:                               # ★相対参照を絶対参照化
      - minpou-art-415-p1-honbun
```

### 2.6 完全な frontmatter 例

`examples/v0.2/` 配下の golden sample を参照:
- `minpou-article-90-v0.2.md` (simple)
- `keihou-article-197-v0.2.md` (zen_dan + kou_dan)
- `minpou-article-415-v0.2.md` (honbun + tadashi + hashira + kou)
- `minpou-article-5-v0.2.md` (にかかわらず)

---

## 3. 本文 Markdown 規約

### 3.1 セクション順序 (v0.1 と同じ)

1. `# 法令名 第N条(通称)` — H1 見出し
2. `## 原文 (日本語)` — 必須
3. `## English Translation` — 推奨
4. `## 判例リンク (Case Law)` — 任意
5. `## 改正履歴 (Amendments)` — 任意
6. `## 注記 (Notes)` — 任意

### 3.2 項の見出し (v0.1 互換)

```markdown
### 第N項
```

### 3.3 segment の見出し (v0.2 新規)

項の見出しの下に segment 見出しを置く。**項が単一 segment (`type: simple`) の場合は segment 見出しを省略可**。

```markdown
### 第N項
#### 本文
本文テキスト...

#### ただし書
ただし、...
```

または:

```markdown
### 第N項 (柱書+号)
#### 柱書
柱書テキスト...

#### 第一号
号 1 のテキスト

#### 第二号
号 2 のテキスト
```

### 3.4 HTML コメントによる parser ヒント (推奨)

```markdown
### 第百九十七条第一項
<!-- segment: zen_dan id: keihou-art-197-p1-zen -->
公務員が、その職務に関し、賄賂を収受し、又はその要求若しくは約束をしたときは、五年以下の拘禁刑に処する。
<!-- segment: kou_dan id: keihou-art-197-p1-kou depends_on: keihou-art-197-p1-zen -->
この場合において、請託を受けたときは、七年以下の拘禁刑に処する。
```

HTML コメントは GitHub Markdown でも表示されないので、人間の閲覧体験を損なわない。

---

## 4. `.chunks.jsonl` フォーマット

`build/chunks/{law}/{law}-article-{N}.chunks.jsonl` には 1 行 = 1 segment chunk。

```json
{"id": "minpou-art-415-p1-honbun", "article_id": "minpou-art-415", "law_id": "129AC0000000089", "law_name_ja": "民法", "article_number": "415", "paragraph_number": 1, "segment_type": "honbun", "modality": "kanou_kenri", "text": "債務者がその債務の本旨に従った履行をしないとき…損害の賠償を請求することができる。", "parent_section": {"hen": 3, "shou": 1, "setsu": 2, "kan": 1}}
{"id": "minpou-art-415-p1-tadashi", "article_id": "minpou-art-415", "law_id": "129AC0000000089", "law_name_ja": "民法", "article_number": "415", "paragraph_number": 1, "segment_type": "tadashi", "modality": "jogai", "text": "ただし、その債務の不履行が…この限りでない。", "parent_section": {"hen": 3, "shou": 1, "setsu": 2, "kan": 1}}
```

各 row は以下を含む (詳細スキーマは `schema/segment-chunk.schema.json` 別途):
- `id`: segment の一意 ID
- `article_id` / `law_id` / `law_name_ja` / `article_number` / `paragraph_number`
- `segment_type` / `modality`
- `text`: segment 本文
- `parent_section`: 階層パス
- (任意) `override_flag` / `override_target` / `applies_provisions` / `references` / `quantitative_conditions`

これは Gemini / source-genai / 自治体 RAG が直接 ingest できる形式。

---

## 5. parser の入出力契約 (実装ガイド)

```
入力:
  - e-Gov XML (一次)
  - または v0.1 .md (既存 corpus からの migration)

出力:
  - data/v0.2/{phase}/{law}/{law}-article-{N}.md
  - build/chunks/{law}/{law}-article-{N}.chunks.jsonl
```

parser は以下を検出:
- 段構造: 「ただし、」「次に掲げる」「この場合において」「前段」「後段」
- override: 「〜の規定にかかわらず」
- 準用: 「〜について準用する」
- modality: 文末 (「しなければならない」「することができる」「処する」等)
- 相対参照: 「前項」「前二条」「同項」 → 絶対参照化
- 数量条件: 数字 + 「年」「月」「日」「歳」「以上」「以下」「超」「未満」 + パターン

優先順位:
1. **rule-based を最大化** (高速 + 決定的)
2. **edge case のみ LLM** (Claude API or Gemini で補完)

---

## 6. v0.1 → v0.2 移行ガイド

### 6.1 段階的移行

1. v0.1 の `data/` はそのまま維持
2. v0.2 の `data/v0.2/` を新規作成 (parallel)
3. v0.2 corpus 完成後、利用者は `data/v0.2/` に切り替え
4. Phase 1 完了時に v0.1 を `archive/v0.1/` へ移動

### 6.2 各号の content 復元

v0.1 では各号 content が欠落しているため、e-Gov XML から再取得して segment 化。

### 6.3 has_proviso / has_items の正確化

v0.1 parser バグで全て false 固定の問題を、v0.2 parser で正しく検出。

---

## 7. 検証規則 v0.2

v0.1 規則 + 以下の追加:

- `segments[]` が空でない (paragraph に少なくとも 1 segment)
- `segment.id` は法令内で一意 (cross-paragraph 重複禁止)
- `override_flag: true` なら `override_target` 必須
- `type: junyou` なら `applies_provisions` 必須
- `type: kou` なら `item_number` 必須
- `.chunks.jsonl` の生成結果が `.md` の `segments[]` と一致 (CI で再生成して diff)

---

## 8. 残る Open Question (Phase 1 中に検討)

- `modality` の列挙はこれで網羅的か (例: 「処する」と「処せられる」の違い)
- 接続詞階層 AST (及び/並びに、若しくは/又は) の表現方法
- 章 scope 定義 (「以下この章において同じ」) の metadata 表現
- 不確定法概念 (「みだりに」「正当な理由なく」) の判例リンク方法

これらは民法 PoC の効果測定後に判断。

---

## 9. 関連文書

- 設計図: `business/japanese-law-rag-design-blueprint-2026-05-22.md`
- データ品質発見: `business/data-quality-finding-2026-05-22.md`
- ファイル単位決定: `business/file-unit-decision-aid-2026-05-22.md`
- v0.1 仕様書: `docs/format-spec.md`
- v0.1 IR 仕様書: `docs/ir-spec.md`

---

*Last updated: 2026-05-22 (v1.0 initial draft, parser 実装と並行して育てる)*

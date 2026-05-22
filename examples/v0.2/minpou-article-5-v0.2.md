---
# JuriCode-JP v0.2 形式 — 民法 第 5 条 未成年者の法律行為 (golden sample, にかかわらず + ただし書)
law_id: 129AC0000000089
law_name_ja: 民法
law_name_en: Civil Code
article_number: '5'
article_id: minpou-art-5
version_date: '2022-04-01'  # 民法成年年齢 18 歳引下げ
source_url: https://laws.e-gov.go.jp/law/129AC0000000089
source_format: e-gov-xml
last_verified: '2026-05-22'
license: MIT
translation_status: none
machine_translated: false
parent_section:
  hen: 1
  hen_name_ja: 第一編 総則
  shou: 2
  shou_name_ja: 第二章 人
  setsu: 3
  setsu_name_ja: 第三節 行為能力
paragraphs:
  - number: 1
    has_proviso: true   # ★v0.2 で正しく検出 (ただし書あり)
    has_items: false
    is_added_by_amendment: false
    segments:
      - id: minpou-art-5-p1-honbun
        type: honbun
        text: '未成年者が法律行為をするには、その法定代理人の同意を得なければならない。'
        modality: gimu  # しなければならない
      - id: minpou-art-5-p1-tadashi
        type: tadashi
        text: 'ただし、単に権利を得、又は義務を免れる法律行為については、この限りでない。'
        modality: jogai
  - number: 2
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
    segments:
      - id: minpou-art-5-p2
        type: simple
        text: '前項の規定に反する法律行為は、取り消すことができる。'
        modality: koka_torikeshi  # 取り消すことができる
        references:
          - minpou-art-5-p1-honbun  # ★「前項の規定」を絶対参照化
  - number: 3
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
    segments:
      - id: minpou-art-5-p3
        type: tokusoku  # ★特則 (にかかわらず)
        text: '第一項の規定にかかわらず、法定代理人が目的を定めて処分を許した財産は、その目的の範囲内において、未成年者が自由に処分することができる。目的を定めないで処分を許した財産を処分するときも、同様とする。'
        modality: kanou_kenri
        override_flag: true                                # ★override 発動
        override_target: [minpou-art-5-p1-honbun]          # ★1 項の制限を override
cases: []
amendments:
  - effective_date: '2022-04-01'
    law_no: 平成30年法律第59号
    summary: 民法改正により成年年齢が 20 歳から 18 歳に引下げ (本条そのものの文言は変わらず、定義の「未成年者」の年齢が変動)
tags:
  - phase1-practitioner
  - 民事法
  - 総則
  - 未成年者
  - 法律行為
  - v0.2-sample
  - sample-nikakawarazu
  - sample-override
notes: |
  v0.2 golden sample (override case): 3 項「第一項の規定にかかわらず」が override 表現の典型例。
  retrieval で 3 項の特則がヒットしたら、自動的に 1 項本文 (override_target) も同時取得する必要がある。
  prompt 側では「『にかかわらず』の規定が原則より優先」のガードレールを発動。
---

# 民法 第5条(未成年者の法律行為)

> **v0.2 サンプル** — 設計図カテゴリ 10「優先順位・エスケープハッチ (にかかわらず)」の典型例。

---

## 原文 (日本語)

### 第五条第一項

#### 本文
<!-- segment: honbun id: minpou-art-5-p1-honbun -->
未成年者が法律行為をするには、その法定代理人の同意を得なければならない。

#### ただし書
<!-- segment: tadashi id: minpou-art-5-p1-tadashi -->
ただし、単に権利を得、又は義務を免れる法律行為については、この限りでない。

### 第五条第二項
<!-- segment: simple id: minpou-art-5-p2 references: minpou-art-5-p1-honbun -->
前項の規定に反する法律行為は、取り消すことができる。

### 第五条第三項
<!-- segment: tokusoku id: minpou-art-5-p3 override_flag: true override_target: minpou-art-5-p1-honbun -->
第一項の規定にかかわらず、法定代理人が目的を定めて処分を許した財産は、その目的の範囲内において、未成年者が自由に処分することができる。目的を定めないで処分を許した財産を処分するときも、同様とする。

---

## 注記 (Notes)

### override 発動条件

3 項「第一項の規定にかかわらず」は **1 項本文の制限 (法定代理人の同意必要) を override** する特則。retrieval / prompt の動作:

| レイヤー | 動作 |
|---|---|
| **metadata** | `override_flag: true` + `override_target: [minpou-art-5-p1-honbun]` |
| **retrieval** | 3 項がヒットしたら 1 項本文も自動同時取得 |
| **prompt** | 「『にかかわらず』の指示が絶対」「元の制限規定より常に優先」のシステムルール |

### Query 例

質問: 「未成年者が処分許可された範囲内で財産を処分できるか?」
- ❌ 1 項のみ retrieve した場合: 「法定代理人の同意が必要」→ **誤回答**
- ✅ 3 項を retrieve し、1 項を同時取得して優先度判定: 「目的範囲内なら自由に処分可能 (1 項より 3 項が優先)」→ **正答**

### 設計図カテゴリ対応

- **カテゴリ 10**: 優先順位・エスケープハッチ (「〜の規定にかかわらず」)
- **構造パターン 2.2**: 本文+ただし書 (1 項)
- **相対参照**: 2 項「前項の規定」、3 項「第一項の規定」→ いずれも絶対参照化
- **モダリティ**: 1 項本文 `gimu` (しなければならない)、3 項 `kanou_kenri` (することができる)

---
# JuriCode-JP v0.2 形式 — 民法 第 415 条 債務不履行による損害賠償 (golden sample, honbun + tadashi + hashira + kou)
law_id: 129AC0000000089
law_name_ja: 民法
law_name_en: Civil Code
article_number: '415'
article_id: minpou-art-415
version_date: '2020-04-01'  # 平成 29 年改正、令和 2 年 4 月 1 日施行
source_url: https://laws.e-gov.go.jp/law/129AC0000000089
source_format: e-gov-xml
last_verified: '2026-05-22'
license: MIT
translation_status: none
machine_translated: false
parent_section:
  hen: 3
  hen_name_ja: 第三編 債権
  shou: 1
  shou_name_ja: 第一章 総則
  setsu: 2
  setsu_name_ja: 第二節 債権の効力
  kan: 1
  kan_name_ja: 第一款 債務不履行の責任等
paragraphs:
  - number: 1
    has_proviso: true   # ★v0.2 で正しく検出
    has_items: false
    is_added_by_amendment: false
    segments:
      - id: minpou-art-415-p1-honbun
        type: honbun  # 本文
        text: '債務者がその債務の本旨に従つた履行をしないとき又は債務の履行が不能であるときは、債権者は、これによつて生じた損害の賠償を請求することができる。'
        modality: kanou_kenri  # することができる
      - id: minpou-art-415-p1-tadashi
        type: tadashi  # ただし書
        text: 'ただし、その債務の不履行が契約その他の債務の発生原因及び取引上の社会通念に照らして債務者の責めに帰することができない事由によるものであるときは、この限りでない。'
        modality: jogai  # この限りでない
  - number: 2
    has_proviso: false
    has_items: true   # ★v0.2 で正しく検出
    is_added_by_amendment: false
    segments:
      - id: minpou-art-415-p2-hashira
        type: hashira  # 柱書
        text: '前項の規定により損害賠償の請求をすることができる場合において、債権者は、次に掲げるときは、債務の履行に代わる損害賠償の請求をすることができる。'
        modality: kanou_kenri
        references:
          - minpou-art-415-p1-honbun  # ★「前項の規定」を絶対参照化
      - id: minpou-art-415-p2-kou-1
        type: kou
        item_number: 1
        text: '債務の履行が不能であるとき。'
      - id: minpou-art-415-p2-kou-2
        type: kou
        item_number: 2
        text: '債務者がその債務の履行を拒絶する意思を明確に表示したとき。'
      - id: minpou-art-415-p2-kou-3
        type: kou
        item_number: 3
        text: '債務が契約によつて生じたものである場合において、その契約が解除され、又は債務の不履行による契約の解除権が発生したとき。'
cases: []
amendments:
  - effective_date: '2020-04-01'
    law_num: 平成29年法律第44号
    description: 民法 (債権関係) 改正により本条 1 項のただし書と 2 項柱書+各号が現行形式に整理された
amendments_summary: |
  平成 29 年改正 (令和 2 年 4 月 1 日施行) で 1 項に帰責事由要件のただし書を追加、2 項に履行に代わる損害賠償の要件を柱書+号で列挙化。
tags:
  - phase1-practitioner
  - 民事法
  - 債権法
  - 債務不履行
  - 損害賠償
  - v0.2-sample
  - sample-honbun-tadashi
  - sample-hashira-kou
notes: |
  v0.2 golden sample (complex case): 1 条に本文+ただし書 (1 項) と柱書+号 (2 項) が共存する複合構造。
  v0.1 では 2 項の各号 (1-3 号) が本文に欠落していたが、v0.2 で e-Gov XML から復元。
  has_proviso と has_items も v0.2 parser で正しく true に検出。
---

# 民法 第415条(債務不履行による損害賠償)

> **v0.2 サンプル** — 本文+ただし書 (1 項) と柱書+号 (2 項) を含む複合構造。
> v0.1 で欠落していた 2 項の各号 content を復元。

---

## 原文 (日本語)

### 第四百十五条第一項

#### 本文
<!-- segment: honbun id: minpou-art-415-p1-honbun -->
債務者がその債務の本旨に従つた履行をしないとき又は債務の履行が不能であるときは、債権者は、これによつて生じた損害の賠償を請求することができる。

#### ただし書
<!-- segment: tadashi id: minpou-art-415-p1-tadashi -->
ただし、その債務の不履行が契約その他の債務の発生原因及び取引上の社会通念に照らして債務者の責めに帰することができない事由によるものであるときは、この限りでない。

### 第四百十五条第二項

#### 柱書
<!-- segment: hashira id: minpou-art-415-p2-hashira references: minpou-art-415-p1-honbun -->
前項の規定により損害賠償の請求をすることができる場合において、債権者は、次に掲げるときは、債務の履行に代わる損害賠償の請求をすることができる。

#### 第一号
<!-- segment: kou id: minpou-art-415-p2-kou-1 item_number: 1 -->
債務の履行が不能であるとき。

#### 第二号
<!-- segment: kou id: minpou-art-415-p2-kou-2 item_number: 2 -->
債務者がその債務の履行を拒絶する意思を明確に表示したとき。

#### 第三号
<!-- segment: kou id: minpou-art-415-p2-kou-3 item_number: 3 -->
債務が契約によつて生じたものである場合において、その契約が解除され、又は債務の不履行による契約の解除権が発生したとき。

---

## 改正履歴 (Amendments)

- **2020-04-01** (平成29年法律第44号)
  - 民法 (債権関係) 改正による現行形式
  - 1 項にただし書 (帰責事由) を追加
  - 2 項に履行に代わる損害賠償の要件を柱書+号で列挙化

---

## 注記 (Notes)

### v0.1 からの修正点

| 項目 | v0.1 | v0.2 |
|---|---|---|
| `has_proviso` (1 項) | `false` (parser バグで誤検出) | **`true`** (正しく検出) |
| `has_items` (2 項) | `false` (parser バグで誤検出) | **`true`** (正しく検出) |
| 2 項各号の content | **欠落** (柱書のみ) | **復元** (e-Gov XML から) |
| 「前項の規定」 | 文字列のまま | **`references: [minpou-art-415-p1-honbun]`** に絶対参照化 |
| segment metadata | なし | `honbun` / `tadashi` / `hashira` / `kou` 区別 |

### 設計図カテゴリ対応

- **構造パターン 2.2**: 本文+ただし書 (1 項)、柱書+号 (2 項)
- **接続詞階層**: 1 項本文の「履行をしないとき **又は** 履行が不能であるとき」
- **相対参照**: 2 項「前項の規定」→ 絶対参照化
- **モダリティ**: 本文 `kanou_kenri` / ただし書 `jogai` / 柱書 `kanou_kenri`

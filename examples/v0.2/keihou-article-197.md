---
# JuriCode-JP v0.2 形式 — 刑法 第 197 条 収賄 (golden sample, zen_dan + kou_dan)
law_id: 140AC0000000045
law_name_ja: 刑法
law_name_en: Penal Code
article_number: '197'
article_id: keihou-art-197
version_date: '1907-04-24'
source_url: https://laws.e-gov.go.jp/law/140AC0000000045
source_format: e-gov-xml
last_verified: '2026-05-22'
license: MIT
translation_status: none
machine_translated: false
parent_section:
  hen: 2
  hen_name_ja: 第二編 罪
  shou: 25
  shou_name_ja: 第二十五章 汚職の罪
paragraphs:
  - number: 1
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
    segments:
      - id: keihou-art-197-p1-zen
        type: zen_dan  # 前段
        text: '公務員が、その職務に関し、賄賂を収受し、又はその要求若しくは約束をしたときは、五年以下の拘禁刑に処する。'
        modality: gimu_kei  # 処する
        penalty:
          type: kinkokei
          max_years: 5
      - id: keihou-art-197-p1-kou
        type: kou_dan  # 後段
        text: 'この場合において、請託を受けたときは、七年以下の拘禁刑に処する。'
        modality: gimu_kei
        penalty:
          type: kinkokei
          max_years: 7
        depends_on: keihou-art-197-p1-zen  # ★前段の文脈が必須
        condition: '請託を受けたとき'
  - number: 2
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
    segments:
      - id: keihou-art-197-p2
        type: simple
        text: '公務員になろうとする者が、その担当すべき職務に関し、請託を受けて、賄賂を収受し、又はその要求若しくは約束をしたときは、公務員となつた場合において、五年以下の拘禁刑に処する。'
        modality: gimu_kei
        penalty:
          type: kinkokei
          max_years: 5
cases: []
amendments: []
tags:
  - phase1-police
  - 刑事法
  - 収賄
  - 汚職
  - v0.2-sample
  - sample-zen-kou-dan
notes: |
  v0.2 golden sample (zen_dan + kou_dan): 1 項に「。」で前段と後段が同居する典型例。
  前段「五年以下」と後段「七年以下」で刑期が異なるため、retrieval で区別不能だと誤回答 (5 年 vs 7 年) を生む。
  後段 chunk には depends_on: 前段 ID を必ず付与し、retrieval は両 segment を同時取得する。
---

# 刑法 第197条(収賄、受託収賄及び事前収賄)

> **v0.2 サンプル** — 前段 + 後段の構造 (1 項に 2 つのルール) の表現例。

---

## 原文 (日本語)

### 第百九十七条第一項

#### 前段
<!-- segment: zen_dan id: keihou-art-197-p1-zen -->
公務員が、その職務に関し、賄賂を収受し、又はその要求若しくは約束をしたときは、五年以下の拘禁刑に処する。

#### 後段
<!-- segment: kou_dan id: keihou-art-197-p1-kou depends_on: keihou-art-197-p1-zen -->
この場合において、請託を受けたときは、七年以下の拘禁刑に処する。

### 第百九十七条第二項
<!-- segment: simple id: keihou-art-197-p2 -->
公務員になろうとする者が、その担当すべき職務に関し、請託を受けて、賄賂を収受し、又はその要求若しくは約束をしたときは、公務員となつた場合において、五年以下の拘禁刑に処する。

---

## 注記 (Notes)

### 構造ポイント

第百九十七条第一項は **1 項に前段 (単純収賄) + 後段 (受託収賄)** を含む典型例。
- 前段: 「賄賂を収受…したとき」→ 5 年以下
- 後段: 「**この場合において、請託を受けたとき**」→ 7 年以下

後段の「この場合」は前段の文脈 (賄賂収受) を引き継ぐ。chunk 化する際は `depends_on` で前段を参照させ、retrieval は両 segment を同時取得する。

### 設計図カテゴリ対応

- **構造パターン 2.2**: 前段/後段 (「。」で区切る、後段は「この場合において」で始まる)
- **モダリティ**: 前段・後段とも「処する」(gimu_kei、義務的刑罰)
- **接続詞階層**: 前段の「賄賂を収受し、**又は** その要求 **若しくは** 約束」が大括り + 小括りの典型

---
# JuriCode-JP v0.2 形式 — 刑法 第 36 条 正当防衛 (golden sample, simple case)
# v0.1 互換フィールド
law_id: 140AC0000000045
law_name_ja: 刑法
law_name_en: Penal Code
article_number: '36'
article_id: keihou-art-36
version_date: '2007-06-12'
source_url: https://laws.e-gov.go.jp/law/140AC0000000045
source_format: e-gov-xml
last_verified: '2026-05-22'
license: MIT
translation_status: draft
machine_translated: false
parent_section:
  hen: 1
  hen_name_ja: 第一編 総則
  shou: 7
  shou_name_ja: 第七章 犯罪の不成立及び刑の減免
paragraphs:
  - number: 1
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
    # v0.2 新規: segments
    segments:
      - id: keihou-art-36-p1
        type: simple
        text: '急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。'
        modality: gimu_negative  # 罰しない
  - number: 2
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
    segments:
      - id: keihou-art-36-p2
        type: simple
        text: '防衛の程度を超えた行為は、情状により、その刑を減軽し、又は免除することができる。'
        modality: kanou_kenri  # することができる
cases: []
amendments: []
tags:
  - phase1-police
  - 刑事法
  - 正当防衛
  - 違法性阻却事由
  - v0.2-sample
notes: |
  v0.2 golden sample (simple case): 2 項とも `type: simple` (段分割なし)。
  segment 数 = 項数 = 2、最も単純な構造例。
---

# 刑法 第36条(正当防衛)

> **v0.2 サンプル** — segment 分割なし (各項とも単一ルール) の最も単純な例。

---

## 原文 (日本語)

### 第三十六条
<!-- segment: simple id: keihou-art-36-p1 -->
急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。

### 第三十六条第二項
<!-- segment: simple id: keihou-art-36-p2 -->
防衛の程度を超えた行為は、情状により、その刑を減軽し、又は免除することができる。

---

## English Translation

> **Status**: `draft` — Pending verification against http://www.japaneselawtranslation.go.jp/

### Article 36 (Paragraph 1)
An act unavoidably performed to protect the rights of oneself or any other person against imminent and unjust infringement shall not be punishable.

### Article 36 (Paragraph 2)
An act exceeding the limits of defense may, in light of the circumstances, be subject to a reduction of punishment or exemption therefrom.

---

## 注記 (Notes)

このサンプルは v0.2 で `type: simple` (項全体が単一ルール、段分割なし) の場合の表現を示す。
modality は p1 が `gimu_negative` (罰しない、否定的義務)、p2 が `kanou_kenri` (することができる、裁量)。

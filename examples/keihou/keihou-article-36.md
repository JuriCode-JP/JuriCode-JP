---
law_id: 140AC0000000045
law_name_ja: 刑法
law_name_en: Penal Code
article_number: "36"
article_id: keihou-art-36
version_date: 2007-06-12
source_url: https://laws.e-gov.go.jp/law/140AC0000000045
source_format: e-gov-html
last_verified: 2026-05-14
license: MIT
translation_status: draft
machine_translated: false
parent_section:
  hen: 1
  hen_name_ja: 第一編 総則
  hen_name_en: Part I General Provisions
  shou: 7
  shou_name_ja: 第七章 犯罪の不成立及び刑の減免
  shou_name_en: Chapter VII Non-Establishment of Crime and Reduction or Remission of Punishment
paragraphs:
  - number: 1
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
  - number: 2
    has_proviso: false
    has_items: false
    is_added_by_amendment: false
cases:
  - case_id: scj-1969-12-04-keishu-23-12-1573
    court: 最高裁判所第一小法廷
    court_en: Supreme Court of Japan, First Petty Bench
    decision_date: 1969-12-04
    citation: 刑集23巻12号1573頁
    case_name_ja: 急迫不正の侵害の意義(例示)
    case_name_en: "Meaning of 'imminent and unjust infringement' (sample)"
    url: https://www.courts.go.jp/app/hanrei_jp/detail2?id=PLACEHOLDER
    relevance: high
    relevant_paragraph: 1
    summary_ja: |
      正当防衛の成立要件である「急迫不正の侵害」の意義について判示した有名判例。
      ※ この記載はフォーマット参照用のサンプルです。実データとして引用する前に、
      裁判所Webサイトおよび判例集で出典・本旨を必ず確認してください。
    summary_en: |
      A leading Supreme Court decision on the meaning of "imminent and unjust
      infringement" as an element of self-defense under Article 36(1) of the Penal Code.
      Note: This entry is a format sample. Verify the citation and URL on the official
      court website before treating it as canonical data.
    tags:
      - 正当防衛
      - 急迫性
amendments: []
tags:
  - phase1-police     # カテゴリA: フェーズ
  - 刑事法            # カテゴリB: 法分類 (必須)
  - 正当防衛          # カテゴリC: 概念
  - 違法性阻却事由    # カテゴリC: 概念
  - sample
notes: |
  これはJuriCode-JPの法令データフォーマットを示すサンプルファイルです。
  Phase 1着手時には、e-Gov法令API・日本法令外国語訳DB・裁判所Webサイトから
  再取得・再検証したうえで data/phase1-police/keihou/ 配下に正式版を配置してください。
---

# 刑法 第36条(正当防衛)

> **このファイルはフォーマット参照用のサンプルです。** 法令本文、英訳、判例リンクのいずれも、Phase 1着手時に公式情報源から再取得・再検証してから `data/phase1-police/` に正式版を配置してください。

---

## 原文 (日本語)

### 第三十六条

急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。

### 第三十六条第二項

防衛の程度を超えた行為は、情状により、その刑を減軽し、又は免除することができる。

---

## English Translation

> **Translation source**: Draft based on the Ministry of Justice "Japanese Law Translation" database style. Verify against the official translation at http://www.japaneselawtranslation.go.jp/ before publication.
>
> **Status**: `draft` — Pending verification.

### Article 36 (Paragraph 1)

An act unavoidably performed to protect the rights of oneself or any other person against imminent and unjust infringement shall not be punishable.

### Article 36 (Paragraph 2)

An act exceeding the limits of defense may, in light of the circumstances, be subject to a reduction of punishment or exemption therefrom.

---

## 判例リンク (Case Law)

> **注**: 以下の判例リンクはフォーマット参照用の例示です。実データとして用いる前に、裁判所Webサイトおよび判例集で出典・本旨を必ず確認してください。

### 最高裁判所第一小法廷 1969年12月4日(刑集23巻12号1573頁)

- **case_id**: `scj-1969-12-04-keishu-23-12-1573`
- **該当**: 第1項
- **関連度**: high
- **要旨**: 正当防衛の成立要件である「急迫不正の侵害」の意義について判示した有名判例。
- **URL**: https://www.courts.go.jp/app/hanrei_jp/detail2?id=PLACEHOLDER (要確認)

---

## 改正履歴 (Amendments)

第36条本文は、刑法現代語化(平成7年法律第91号、平成7年6月1日施行)以降、内容的な改正はない。

- **2007-06-12** — 平成19年改正において、関連規定の整理が行われたが本条への影響なし(参考情報、要確認)
- **2025-06-01** — 令和4年法律第67号(懲役・禁錮の拘禁刑への統一)。本条は刑罰部分を含まないため文言変更なし。

---

## 注記 (Notes)

### 学説・実務上の論点(参考)

- **正当防衛の3要件**: 急迫性、防衛の意思、相当性
- 第1項は違法性阻却事由としての正当防衛、第2項は責任阻却・違法性減少事由としての過剰防衛を規定する
- 「やむを得ず」の解釈、「防衛の程度」の判断基準は判例の蓄積が厚い

### このサンプルの目的

このファイルはJuriCode-JPの法令データフォーマットの**参照実装**です。具体的には以下を示します:

1. **YAML frontmatter** の必須・推奨フィールド構成
2. **2項構造の条文**の Markdown 表現
3. **判例リンク**の構造(frontmatter + 本文双方への記載)
4. **改正履歴**の表現
5. **draft 英訳**の取り扱い方(`translation_status: draft` + source note)
6. **注記セクション**での学説・補足情報の配置

実データを `data/phase1-police/keihou/keihou-article-36.md` として配置するときは、このサンプルを**コピーして使うのではなく**、フォーマットだけを参考に、本文と判例を公式情報源から取得して新規作成してください。

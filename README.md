<div align="center">

# JuriCode-JP

### A LegalTech initiative by CHOKAI Co.,Ltd.

*日本の法令をAI時代に最適化する*  
*Making Japanese legislation AI-ready for the age of AI.*

[![CI](https://github.com/JuriCode-JP/JuriCode-JP/actions/workflows/ci.yml/badge.svg)](https://github.com/JuriCode-JP/JuriCode-JP/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-46%20passing-brightgreen)](./tools/shared/tests)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![Pydantic v2](https://img.shields.io/badge/pydantic-v2-e92063)](https://docs.pydantic.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Status: Phase 1 / v0.2.0](https://img.shields.io/badge/status-Phase%201%20%2F%20v0.2.0-brightgreen)](./docs/strategy.md)
[![Articles: 11,758](https://img.shields.io/badge/articles-11%2C758-blue)](./data/)
[![Statutes: 43](https://img.shields.io/badge/statutes-43-blue)](./data/)
[![Segments: 63,246](https://img.shields.io/badge/segments-63%2C246-blueviolet)](./docs/format-spec-v0.2.md)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

</div>

---

## 🚀 v0.2.0 リリース / Release (2026-05-22)

**JuriCode-JP v0.2.0** は、日本法令を AI/LLM の RAG (Retrieval-Augmented Generation) で扱いやすい **segment-aware 構造化コーパス** に変換した初のリリースです。

| 項目 | v0.1 | **v0.2.0** |
|---|---:|---:|
| 法令数 | 30 | **43** |
| 条文数 | 8,022 | **11,758** |
| Retrieval chunks | 11,758 (条単位) | **63,246 (segment 単位)** |
| 自治体 RAG R@1 (35Q) | 65.7% | **68.6%** (v0.1 baseline 超え) |
| 自治体 RAG R@3 (35Q) | 88.6% | 85.7% (1 query 差) |
| 各号 (kou) 構造化 | parser bug で欠落 | **14,868 chunks 復元** |
| 附則 (SupplProvision) | 未取り込み | **~5,000 chunks + metadata** |
| 設計図カテゴリ自動検出 | なし | **にかかわらず 504 / 準用 523** |
| 構造化 metadata | parser bug あり | **完全 (topic / target_main_articles / modality 等)** |

### 主な特徴

- **Segment-aware**: 1 条文を本文/ただし書/前段/後段/柱書/各号/特則/準用 に分割
- **附則対応**: 各 SupplProvision を Article/Paragraph 単位で chunk 化、`topic` (経過措置/施行期日/罰則の適用/etc) と `target_main_articles` (参照先本則条文) を自動抽出
- **元号→西暦変換**: AmendLawNum 「昭和二二年一〇月二六日法律第一二四号」を `enforcement_date: 1947-10-26` に正規化
- **Parent-Child 構造**: 子 chunk (検索用) + rollup chunk (LLM コンテキスト用) の二層設計
- **設計図 4 層責任分界**: L1 前処理 / L2 metadata / L3 retrieval / L4 prompt の分離
- **MIT ライセンス**: 公的データ (e-Gov 法令 API v2) ベース + MIT 構造化レイヤー

詳細仕様: [docs/format-spec-v0.2.md](docs/format-spec-v0.2.md)

---

## 日本語

### このプロジェクトについて

**JuriCode-JP** は、株式会社CHOKAIによる、AI時代の日本法令インフラを目指すLegalTechイニシアティブです。

構造化された法令データ、判例リンク、英訳併記を通じて、警察・企業・市民・行政・国際社会の全ステークホルダーに役立つ法令基盤を構築します。

### ミッション

- 🤖 AI/LLM向け法令データの提供
- ⚖️ 判例リンクによる立体的な法令理解
- 🌏 英訳併記による国際的アクセシビリティ
- 🌱 オープンソースによる持続可能な発展

### 段階的なフォーカス

| フェーズ | 重点領域 | 解決する課題 |
|---------|---------|-------------|
| Phase 1 | 刑事手続関連法令 | 刑事司法の透明性、現場業務の効率化 |
| Phase 2 | 民事・商事法令 | 中小企業の法務コンプライアンス |
| Phase 3 | 全法令網羅 | 市民・行政・国際社会への展開 |

現在は **Phase 1 — v0.2.0 リリース済** の段階です。Phase 1 の戦略 target (自治体・警察・税理士・法律実務家) のうち、自治体ドメインで v0.1 baseline を超える retrieval 精度を達成しました。

---

## English

### About

**JuriCode-JP** is a LegalTech initiative by CHOKAI Co.,Ltd., aiming to build the legal infrastructure of Japan in the AI era.

Through structured legal data, case law links, and bilingual annotation, we serve all stakeholders: police, businesses, citizens, government, and the international community.

### Mission

- 🤖 Providing AI/LLM-ready legal data
- ⚖️ Three-dimensional law understanding through case law links
- 🌏 International accessibility through English annotations
- 🌱 Sustainable growth through open source

### Phased Focus

| Phase | Focus Area | Problems Addressed |
|-------|-----------|---------------------|
| Phase 1 | Criminal procedure | Transparency and efficiency in criminal justice |
| Phase 2 | Civil & commercial laws | SME legal compliance |
| Phase 3 | Full coverage | Citizens, government, international |

Currently in **Phase 1 — v0.2.0 released**. Among the Phase 1 strategic targets (municipal, police, tax accountant, legal practitioner), we have achieved retrieval accuracy exceeding the v0.1 baseline in the municipal domain.

---

## Phase 1 ロードマップ / Phase 1 Roadmap

### 期間 / Timeline
**2026 — 2027**:刑事手続関連法令(criminal procedure law)の構造化を完了させる。

### 成果物 / Deliverables
- 警察関連法令 + 自治体関連法令 + 民法 + 税法 6 法令 + 商法・会社法・独禁法・金商法 + 労働基準法 + 薬機法 等 計 **43 法令 / 11,758 条** を 1 条 = 1 ファイルの YAML frontmatter + Markdown 形式で構造化 (2026-05-22 v0.2.0 リリース時点)
- **v0.2.0**: segment-aware 構造化により **63,246 retrieval-ready chunks** に拡張 (本文/ただし書/前段/後段/柱書/各号/特則/準用 + 附則 + rollup)
- 日本語原文と公定英訳の併記、最高裁判例リンク(出典 URL 付き)を各条文に統合
- e-Gov 法令 API v2 からの自動取得・スキーマ検証・中間表現(IR)変換の完全パイプライン
- JSON Schema による機械検証 + Pydantic IR による型安全なデータアクセス
- **設計図 4 層責任分界** (L1 前処理 / L2 metadata / L3 retrieval / L4 prompt) に基づく Japanese-legal RAG 設計

### 現在の実装状況 / Current Implementation Status
| 項目 | 状況 |
|---|---|
| データフォーマット仕様 v0.1 | ✅ [docs/format-spec.md](docs/format-spec.md) |
| アーキテクチャ全体像 | ✅ [docs/architecture.md](docs/architecture.md) |
| 中間表現(IR)仕様 | ✅ [docs/ir-spec.md](docs/ir-spec.md) |
| メタタグ標準語彙 | ✅ [docs/tag-vocabulary.md](docs/tag-vocabulary.md) |
| 正規参考例(刑法 36 条) | ✅ [examples/keihou/keihou-article-36.md](examples/keihou/keihou-article-36.md) |
| Pydantic IR パッケージ | ✅ [tools/shared/](tools/shared/) (41+ tests passing) |
| 検証 CLI | ✅ [tools/validate/](tools/validate/) (8 tests passing) |
| JSON Schema 自動生成 | ✅ [schema/juricode-article.schema.json](schema/juricode-article.schema.json) ([export-schema.py](tools/shared/scripts/export-schema.py)) |
| GitHub Actions CI | ✅ [.github/workflows/ci.yml](.github/workflows/ci.yml) (lint + pytest + validate + schema drift check) |
| e-Gov 法令 API v2 クライアント + bulk-ingest | ✅ [tools/fetch-egov/](tools/fetch-egov/)(30 法令 ingest 実績)|
| 第二参考例(刑訴法 198 条) | ✅ [examples/keiji-soshou-hou/keiji-soshou-hou-article-198.md](examples/keiji-soshou-hou/keiji-soshou-hou-article-198.md) |
| Phase 1 法令スコープ(警察・行政・民事・税・商事・労働・薬機 = **43 法令**) | ✅ [data/](data/) |
| データ本体(条文構造化) | ✅ **11,758 条 / 43 法令** 投入済(2026-05-22 v0.2.0、当初 Phase 1 約束 75 条比 **約 157 倍**)|
| **v0.2.0 segment-aware corpus** | ✅ **63,246 chunks** (各号 14,868 + 附則 ~5,000 + rollup 6,948 + segments) |
| **v0.2.0 仕様書** | ✅ [docs/format-spec-v0.2.md](docs/format-spec-v0.2.md) |
| **附則 (SupplProvision) 抽出** | ✅ [tools/parse/v0.2/extract_supplproviso_from_xml.py](tools/parse/v0.2/extract_supplproviso_from_xml.py) (topic 分類 + target_main_articles 抽出 + 元号→西暦変換) |
| **各号 (kou) 復元** | ✅ [tools/parse/v0.2/extract_kou_from_xml.py](tools/parse/v0.2/extract_kou_from_xml.py) |
| **本則 rollup chunks** | ✅ [tools/parse/v0.2/add_rollup_chunks.py](tools/parse/v0.2/add_rollup_chunks.py) |
| **自治体 RAG benchmark R@1 = 68.6%** | ✅ v0.1 baseline (65.7%) を超え達成 |

### ドキュメント / Documentation
- **[docs/format-spec-v0.2.md](docs/format-spec-v0.2.md)** — **v0.2 仕様書** (segment-aware + 附則 + rollup、2026-05-22)
- [docs/format-spec-v0.2.html](docs/format-spec-v0.2.html) — v0.2 仕様書 HTML 版
- [docs/format-spec.md](docs/format-spec.md) — v0.1 法令データフォーマット仕様
- [docs/architecture.md](docs/architecture.md) — 全体アーキテクチャ(6 段階パイプライン)
- [docs/ir-spec.md](docs/ir-spec.md) — 中間表現(IR)詳細仕様
- [docs/tag-vocabulary.md](docs/tag-vocabulary.md) — メタタグ標準語彙
- [docs/strategy.md](docs/strategy.md) — 段階戦略
- [docs/differentiation.md](docs/differentiation.md) — 先行 OSS との関係
- [docs/follow-ups.md](docs/follow-ups.md) — 既知の改善余地・将来タスク

---

## 関連プロジェクト / Related Projects

このプロジェクトは、日本の優れた先行プロジェクトを尊重し、その上に構築されています。  
This project builds upon excellent existing Japanese projects:

- [gitlaw-jp](https://github.com/aluqas/gitlaw-jp) by aluqas
- [Lawtext](https://github.com/yamachig/Lawtext) by yamachig
- [ja-law-parser](https://github.com/takuyaa/ja-law-parser) by takuyaa
- [e-Gov MCP](https://github.com/ryoooo/e-gov-law-mcp) by ryoooo

また、国際的な [legalize.dev](https://legalize.dev) コミュニティとの連携を視野に入れています。  
We also aim to join the international [legalize.dev](https://legalize.dev) community.

---

<div align="center">

**CHOKAI Co.,Ltd.** — Tokyo, Japan

*Treating legislation as code. One commit at a time.*

</div>

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
[![Status: Phase 0](https://img.shields.io/badge/status-Phase%200-orange)](./docs/strategy.md)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

</div>

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

現在は **Phase 0 — プロジェクト設計とコミュニティ調査** の段階です。

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

Currently in **Phase 0 — Project design and community research**.

---

## Phase 1 ロードマップ / Phase 1 Roadmap

### 期間 / Timeline
**2026 — 2027**:刑事手続関連法令(criminal procedure law)の構造化を完了させる。

### 成果物 / Deliverables
- 刑法・刑事訴訟法・警察法・警察官職務執行法・道交法など警察 9 法令 + 自治体 9 法令 + 民法 + 税法 6 法令 + 商法・会社法・独禁法 + 労働基準法 計 30 法令を 1 条 = 1 ファイルの YAML frontmatter + Markdown 形式で構造化(2026-05-21 時点 8,022 条 投入済)
- 日本語原文と公定英訳の併記、最高裁判例リンク(出典 URL 付き)を各条文に統合
- e-Gov 法令 API v2 からの自動取得・スキーマ検証・中間表現(IR)変換の完全パイプライン
- JSON Schema による機械検証 + Pydantic IR による型安全なデータアクセス

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
| Phase 1 法令スコープ(警察 9・行政 9・民事 1・税 6・商事 3・労働 1 = **30 法令**) | ✅ [data/](data/) |
| データ本体(条文構造化) | ✅ **8,022 条 / 30 法令** 投入済(2026-05-21、当初 Phase 1 約束 75 条比 約 107 倍)|

### ドキュメント / Documentation
- [docs/format-spec.md](docs/format-spec.md) — 法令データフォーマット仕様
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

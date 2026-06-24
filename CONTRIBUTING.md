# コントリビューションガイド (CONTRIBUTING)

JuriCode-JP への協力をありがとうございます。日本の法令を AI/LLM 時代に最適化された形式で構造化するオープンプロジェクトです(MIT・株式会社CHOKAI 主催)。
*English contributors welcome — this guide is JA-first because the source material is Japanese law; feel free to open issues/PRs in English.*

> 人間のコントリビューター向けガイドです(AI アシスタント向けは `CLAUDE.md`)。

## 1. はじめに読むもの
- `README.md` — プロジェクト概要
- `docs/format-spec-v0.2.md` — 法令データの**正規フォーマット仕様**(最重要)
- `examples/keihou/` — フォーマットの正規参考例(刑法)
- `docs/follow-ups.md` — 既知の改善余地・タスク一覧(FU-xxx)

## 2. 貢献の種類(得意分野で選べます)
| 種類 | 内容 | 出発点 |
|---|---|---|
| **法令データ追加** | 新しい法令を format-spec に沿って構造化 | Issue「new-law-request」/ `examples/keihou` を雛形に |
| **データ修正** | 誤字・条文・メタデータの訂正 | Issue「data-correction」 |
| **英訳の改善** | 公定訳の併記・draft 訳の改善(由来明示) | Issue「translation-fix」/ `docs/licensing.md` |
| **判例リンク** | 出典付きの判例リンク追加(推測厳禁・URL 実在確認) | format-spec §判例 |
| **コード/ツール** | parser・validate・CI の改善 | `docs/follow-ups.md` の FU 項目から軽めを選ぶ |

迷ったら、まず Issue を立てて「これをやりたい」と相談してください。

## 3. 進め方(fork + PR)
1. このリポジトリを **fork** する。
2. ブランチを切る: `data/<law>/article-<N>`(データ)/ `feature/<topic>`(機能)/ `fix/<topic>`(修正)。
3. 変更する。**法令本文は e-Gov 公式テキストの完全コピー**(句読点・送り仮名・漢字いずれも改変禁止)。構造化のための情報は本文ブロックの外に置く。
4. コミットは [Conventional Commits](https://www.conventionalcommits.org/): `data(keihou): add article 36` のように `type(scope): subject`。1コミット1論理単位。
5. **PR を出す**。CI(下記)が緑になることを確認。レビュー後にマージされます。

## 4. 絶対に守ること
- **法令本文の改変・要約・読みやすさ調整は禁止**(原典どおり)。
- **判例は推測・記憶から追加しない**。出典(URL or 掲載誌・巻号)を確認してから。URL は実在確認。
- **私的解釈は本文・英訳に混ぜない**。注記セクションに出典付きで。
- **出典明示**: 法令は `source_url`(e-Gov)、判例は永続 URL。
- ライセンス: 構造化レイヤーは MIT。法令本文・判例は引用範囲。各ソースのライセンスは `docs/licensing.md` 参照。
- **PR・コミットメッセージに個人名・内部ツール名・非公開プロセス名を書かない**。公開リポの履歴と PR は誰でも読めるため、レビュー担当者の個人名、社内のアドバイザ/自動化ツール名、社内レビュー工程名などは中立な技術ラベルに置き換える。
  - 例: 「(担当者)目視ロック」→「source-locked against the official source」/「(ツール名)独立検証」→「independent verification」/「(担当者)裁定」→「scoped decision」/「title ↔ source verification」。
  - 出典・検証手段は**何を**確認したか(一次資料・round-trip・テスト)で書き、**誰が/どのツールで**は書かない。
  - English contributors: do not put personal names or internal/private tool or process names in public PR titles, PR bodies, or commit messages; use neutral technical labels instead.

## 5. 検証(PR 前にローカルで)
このリポの CI が以下を自動チェックします。PR 前にローカルで通すとスムーズです:
- `ruff check tools/` / `ruff format --check tools/`(コード)
- `python tools/validate/validate-all.py`(全データのスキーマ検証)
- `python tools/parse/verify.py --path data/v0.2`(**法令本文の原典一致を機械照合**=round-trip)
- (詳細な検証コマンドは `CLAUDE.md` §8 を参照)

## 6. 困ったら
- Issue で質問してください(日本語/英語どちらでも)。
- 大きな変更は、着手前に Issue で方針を相談すると手戻りが少ないです。

ありがとうございます。*Treating legislation as code. One commit at a time.*

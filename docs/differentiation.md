# 先行OSSとの差別化と関係

JuriCode-JPは**車輪の再発明ではなく、既存基盤の上に独自レイヤーを積む**ことで価値を出す。本ドキュメントは、各先行プロジェクトとの関係と、JuriCode-JPの独自貢献を整理する。

---

## 先行OSSの概観

### 個人・コミュニティ系OSS

| プロジェクト | 主体 | 主な機能 | ライセンス | 関係性 |
|---|---|---|---|---|
| [gitlaw-jp](https://github.com/aluqas/gitlaw-jp) | aluqas氏 | 法令のGit管理(変更履歴の可視化) | OSS | 設計思想の参考 |
| [Lawtext](https://github.com/yamachig/Lawtext) | yamachig氏 | 法令テキストフォーマット仕様 + 変換ツール | OSS | フォーマット参考、変換ツール候補 |
| [ja-law-parser](https://github.com/takuyaa/ja-law-parser) | takuyaa氏 | e-Gov XMLパーサー | OSS | 取得・解析処理での活用予定 |
| [e-Gov MCP](https://github.com/ryoooo/e-gov-law-mcp) | ryoooo氏 | LLM向け法令データMCPサーバー | OSS | 補完関係(リアルタイム取得 vs 構造化済みデータセット) |

### 政府公式プロジェクト

| プロジェクト | 主体 | 主な機能 | ライセンス | 関係性 |
|---|---|---|---|---|
| **[源内 (GENAI)](https://www.digital.go.jp/en/policies/genai)** | **デジタル庁** | 全府省庁(約18万人)向け生成AI利用基盤 + 行政実務用AIアプリ群(法制度AIアプリ Lawsy-Custom-BQ 含む) | **MIT** | **JuriCode-JPデータの最有力ダウンストリーム消費者**。源内のRAGデータ層として直接接続可能 |
| [e-Gov 法令API](https://laws.e-gov.go.jp/) | デジタル庁 | 法令データのXML/HTML配信API | 政府データ | JuriCode-JPの一次データソース |

源内のGitHub: https://github.com/digital-go-jp/ (genai-web / genai-ai-api)

---

## JuriCode-JPの独自貢献(4本柱)

### 1. AI/LLM最適化フォーマット
- **1条文=1ファイル**の単位設計でLLMチャンク最適化
- YAML frontmatterに条文メタ・判例リンク・改正履歴をまとめ、単一チャンクで文脈を完備
- 既存OSSはテキスト変換や履歴管理に強みがあるが、「LLM向け構造化」の観点は明示されていない

### 2. 警察関連法令への戦略的深掘り
- Phase 1で警察関連法令にフォーカスし、社会課題への直接的貢献を打ち出す
- 既存OSSは普遍的・全領域指向で、特定領域の深掘りはない
- 警察調書作成AIなど、具体的応用シーンとの距離が近い

### 3. 判例リンクによる立体的法令理解
- 条文⇔判例のリンク構造を構造化データとして保持
- 既存OSSの多くは条文テキストの構造化に留まる
- LegalRAGでの参照精度向上に直結

### 4. 英訳併記による国際アクセシビリティ
- 政府公定訳(日本法令外国語訳DB)の取り込みと、不足部分のコミュニティ訳
- legalize.dev(31カ国の法令Markdown化プロジェクト)との接続を見据えた多言語拡張性
- 既存OSSで多言語対応を主目的とするものはない

---

## 連携ポリシー

### 利用させてもらう
- `ja-law-parser`: e-Gov XML解析の処理コードとして直接依存することを検討
- `Lawtext`: 既存変換ツールチェーンの活用
- `e-Gov MCP`: ユーザがリアルタイム法令を取得する用途は e-Gov MCP に誘導

### 連携を提案する
- `gitlaw-jp`(aluqas氏): Git管理設計の知見共有、初期段階でコンタクト予定
- `Lawtext`(yamachig氏): フォーマット相互変換、双方向データ提供
- `legalize.dev`: 32カ国目としての参加表明、JP仕様の提案
- **源内 (デジタル庁 GENAI)**: 法制度AIアプリ(Lawsy-Custom-BQ)のRAGデータ層として JuriCode-JP を提供。e-Gov 生データ単独 vs JuriCode-JP 構造化データの A/B 検証ベンチマークを作成し、回答精度向上のエビデンスをデジタル庁 note 公式アカウントに発信

### 重複を避ける
- 単純な法令テキスト変換は再実装しない(`Lawtext`等を活用)
- リアルタイム取得MCPは作らない(`e-Gov MCP`との重複を避ける)
- Git管理ワークフローの再発明はしない

---

## 互換性方針

JuriCode-JPの構造化データは、以下との相互変換が可能な設計とする(将来実装)。

- **e-Gov XML** ← `tools/fetch-egov/`、`tools/parse/`
- **Lawtext形式** ↔ `tools/convert/lawtext/`(検討)
- **JSON-LD / Schema.org Legislation** → 国際的に流通可能(将来検討)
- **源内 Lawsy-Custom-BQ 取り込み形式**(BigQuery + Gemini ベクトル検索)→ `tools/export/lawsy-bq/`(検討、Phase 1 早期に着手したい優先タスク)

---

## ライセンス整合

| 部分 | ライセンス |
|---|---|
| 構造化レイヤー(YAML schema, 変換コード) | MIT |
| 法令本文 | パブリックドメイン(著作権法第13条) |
| 政府公定英訳 | 政府提供範囲のライセンス(出典明記が要件) |
| コミュニティ英訳 | CC BY 4.0 を推奨(寄稿規約で明示予定) |
| 判例本文 | 引用に留め本文転載は行わない、リンクのみ |

詳細は `LICENSE` および各データファイル冒頭のfrontmatter `license` フィールド参照。

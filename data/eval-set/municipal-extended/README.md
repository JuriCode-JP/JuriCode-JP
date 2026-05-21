# JuriCode-JP Municipal Practice Eval-Set v0.3-beta (2026-05-21)

**国内初の公開自治体 RAG 評価データセット**。総務省 R7.12 自治体 AI 活用・導入ガイドブック準拠の 35 問。

## ライセンスと出典

- **ライセンス**: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- **作成者**: 株式会社CHOKAI (JuriCode-JP プロジェクト)
- **作成日**: 2026-05-21
- **バージョン**: 0.3-beta
- **作問方法**: Claude AI による R7.12 ガイドブック等の公開資料からの作問。法律実務家による検証前のため**ベータ版**扱い

## このデータセットの位置付け

**lawqa_jp(デジタル庁、企業法務向け)を補完する自治体実務向け公開ベンチマーク**。

| 評価データ | 対象ユーザー | 規模 |
|---|---|---:|
| デジタル庁 lawqa_jp(2025-11) | 大企業法務部・規制業種コンプラ | 140 問 |
| JBE-QA(学術、2025-11) | 司法試験対策・LLM 能力評価 | 3,464 問 |
| COLIEE Task 3 | 民法限定の retrieval 研究 | 996 問 |
| **JuriCode-JP v0.3-beta(本データ)** | **自治体職員・市民・小規模法律事務所** | **35 問** |

## カバー領域(7 領域 × 5 問 = 35 問)

| ファイル | 領域 | 主な対象法令 |
|---|---|---|
| `governance.jsonl` | 自治体ガバナンス(住民監査請求・議決事件・直接請求等) | 地方自治法 |
| `admin-procedure.jsonl` | 行政手続(審査基準・意見陳述・行政指導等) | 行政手続法 |
| `admin-appeals.jsonl` | 行政不服審査(請求期間・教示・審理員等) | 行政不服審査法 |
| `records-disclosure.jsonl` | 公文書管理・情報公開 | 公文書管理法、情報公開法 |
| `personal-info.jsonl` | 個人情報保護 | 個人情報保護法 |
| `civil-service.jsonl` | 公務員制度(守秘義務・信用失墜・服務等) | 地方公務員法、国家公務員法 |
| `digital-society.jsonl` | デジタル社会形成基本法 | デジタル社会形成基本法 |

## エントリスキーマ

```jsonc
{
  "id": "eval-municipal-governance-001",
  "category": "municipal-governance",
  "question": "住民が自治体の財務運営に違法な支出があると考えた場合、...",
  "expected_article_ids": ["chihou-jichi-hou-art-242"],
  "relevance": "high",
  "difficulty": "easy",                    // easy / medium
  "topic_tags": ["住民監査請求", "地方自治法"],
  "notes": "(問題の解説)",
  "source": "JuriCode-JP self-authored",
  "source_basis": "総務省 R7.12 ガイドブック §X.Y",
  "source_license": "CC BY 4.0",
  "authoring_method": "Claude AI による R7.12 ガイドブック等の公開資料からの作問。法律実務家による検証前のため beta 版扱い",
  "legal_disclaimer": "本問題は AI システムの retrieval 性能評価用であり、個別事案への法的助言ではない",
  "version": "0.3-beta",
  "version_date": "2026-05-21",
  "review_status": "unreviewed (Claude AI authored)"
}
```

## 使い方

### retrieval ベンチマーク

```powershell
python tools/embed/retrieve.py `
  --embedded build/juricode-bq-embedded `
  --eval-set data/eval-set/municipal-extended/*.jsonl `
  --top-k 10 --show-per-query
```

### 既存 137 件 + 新規 35 件の統合ベンチ

```powershell
python tools/embed/retrieve.py `
  --embedded build/juricode-bq-embedded `
  --eval-set `
    data/eval-set/police.jsonl `
    data/eval-set/municipal.jsonl `
    data/eval-set/practitioner.jsonl `
    data/eval-set/tax.jsonl `
    data/eval-set/lawqa-jp/commercial-kinsho.jsonl `
    data/eval-set/lawqa-jp/pharma.jsonl `
    data/eval-set/lawqa-jp/real-estate.jsonl `
    data/eval-set/municipal-extended/*.jsonl `
  --top-k 10 --show-per-query
```

## バージョン履歴

| バージョン | 日付 | 内容 |
|---|---|---|
| 0.3-beta | 2026-05-21 | 初版公開、35 問、Claude AI 作問、未レビュー |
| 0.3-stable(予定) | 2026-06 末 | 弁護士アドバイザーレビュー反映 |
| 0.4(予定) | 2026-Q3 | 警察・税理士領域追加(余合氏ヒアリング後) |

## 免責事項

本データセットは AI システムの retrieval 性能評価を目的とします。**個別事案への法的助言ではありません**。法令改正により正解条文が変更される可能性があります。最新の法令は [e-Gov 法令検索](https://laws.e-gov.go.jp/) でご確認ください。

## 引用

```
JuriCode-JP Municipal Practice Eval-Set v0.3-beta (2026-05-21)
Author: CHOKAI Co.,Ltd.
License: CC BY 4.0
URL: https://github.com/JuriCode-JP/JuriCode-JP
```

## フィードバック

問題の妥当性・正解条文・改善提案は GitHub Issues へ:
https://github.com/JuriCode-JP/JuriCode-JP/issues

---

*作成: 2026-05-21 / 株式会社CHOKAI / CC BY 4.0*

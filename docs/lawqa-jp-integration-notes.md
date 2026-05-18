# lawqa_jp 統合設計ノート

**バージョン**: v0.1 (2026-05-18 初版)
**位置づけ**: デジタル庁公開 QA データセット `lawqa_jp` を JuriCode-JP の検証ベンチマークとして取り込む設計
**関連**: [architecture.md](./architecture.md) §7 テスト戦略、[ir-spec.md](./ir-spec.md)

---

## 1. lawqa_jp とは

- **正式名称**: 日本の法令に関する多肢選択式 QA データセット
- **公開元**: デジタル庁(digital-go-jp/lawqa_jp)
- **公開時期**: 2025 年 10 月
- **ライセンス**: 公共データ利用規約(Public Data License v1.0)
- **規模**: 12 commits(現状)、★ 265
- **GitHub**: https://github.com/digital-go-jp/lawqa_jp

### 1.1 想定活用例(公式)

- 法令分野における多肢選択 Q&A システムの学習・評価
- **法令文書に対する RAG パイプラインの検証** ← JuriCode-JP の主要用途
- 複数 LLM による正解生成・集約手法の研究

---

## 2. データ構成

### 2.1 data/ ディレクトリ

| ファイル | 内容 |
|---|---|
| `law_list.json` | 設問で参照されている法令の一覧(法令名・出典条文) |
| `selection.json` | **元データ**。各問題のコンテキスト・設問・選択肢・正答を構造化 JSON で |
| `selection.csv` | 同内容の CSV 版 |
| `selection_randomized.json` | 選択肢 a〜d を 4 通りにランダマイズ(順序依存性評価用) |
| `selection_with_reference_randomized.json` | 外部法令参照を含む設問のみ + ランダマイズ |

### 2.2 各エントリの構造

```json
{
  "ファイル名": "金商法_第2章_選択式_関連法令_問題番号57",
  "回答オーダーマップ番号": "1",
  "コンテキスト": "## 金融商品取引法\n### 第5条\n#### 第6項\n...",
  "指示": "<following_context>以下の問題文に対する回答を,選択肢a,b,c,dの中から1つ選んでください.",
  "問題文": "金融商品取引法第5条第6項により,...",
  "選択肢": "a ~\nb ~\nc ~\nd ~",
  "output": "c",
  "references": ["https://laws.e-gov.go.jp/law/323AC0000000025"]
}
```

### 2.3 コンテキストの Markdown 構造

```
## 法令名(例: 金融商品取引法)
### 第N条
#### 第N項
##### 第N号
```

これは **JuriCode-JP の格納フォーマットと階層構造が一致**する(完全な相互運用性あり)。

---

## 3. JuriCode-JP との接続点

### 3.1 直接マッピング可能なフィールド

| lawqa_jp フィールド | JuriCode-JP の対応 |
|---|---|
| `references[]` の URL | `JuriCodeArticle.source_url`(完全一致でルックアップ可能) |
| コンテキストの `## 法令名` | `law_name_ja` |
| コンテキストの `### 第N条` | `article_number`(漢数字 → 算用数字変換が必要) |
| コンテキストの `#### 第N項` | `paragraphs[N].number` |
| コンテキストの `##### 第N号` | `paragraphs[N].items[M].number` |

### 3.2 Phase 1(警察関連法令)の対象

lawqa_jp は法分野横断的だが、`law_list.json` の中に Phase 1 法令(刑法・刑訴法・警察法・警職法)を含む問題があれば、JuriCode-JP の評価データとして直接使える。

**確認すべきこと**(取り込み実装時):
- `law_list.json` 内に `140AC0000000045`(刑法)、`323AC0000000131`(刑訴法)、`329AC0000000162`(警察法)、`323AC0000000136`(警職法)が含まれているか
- 含まれていない場合、Phase 2 以降(金融商品取引法・民法等が中心)で活用

---

## 4. 評価フレームワーク設計

### 4.1 評価モード(3 種類)

公式は 3 つの評価軸を想定:

| モード | 内容 | JuriCode-JP との関係 |
|---|---|---|
| **A. 知識テスト** | コンテキストなしで LLM の既存知識を測定 | JuriCode-JP は不使用(LLM 単体評価) |
| **B. 読解テスト** | コンテキスト(法令本文)あり、設問に回答 | **JuriCode-JP のコンテキスト品質を測定** |
| **C. 実務応用テスト** | RAG 検索能力を測定 | **JuriCode-JP の検索精度を測定**(最重要) |

### 4.2 A/B 検証設計(JuriCode-JP の付加価値の実証)

**JuriCode-JP がデジタル庁源内 Lawsy への上位データ層になる根拠** = 「e-Gov 生 XML 単独」vs 「JuriCode-JP 構造化データ」の精度差を数値で示すこと。

| 評価ペア | A 群 | B 群 | 期待結果 |
|---|---|---|---|
| **検索精度** | e-Gov XML 全文を embedding | JuriCode-JP の条文単位 IR | B が高 Top-K accuracy |
| **回答精度** | A の検索結果を LLM に渡す | B の検索結果 + 判例リンクを LLM に渡す | B が選択肢正答率向上 |
| **引用精度** | A は条文番号の引用が曖昧 | B は `article_id` で正確に引用 | B が引用検証 100% |

これを NLnet Section H と Tokyo Award で **「JuriCode-JP が源内 Lawsy への上位互換」のエビデンス**として提示できる。

---

## 5. 実装設計

### 5.1 配置場所

```
tools/validate/
├── src/juricode_validate/
│   ├── lawqa_loader.py        ← lawqa_jp data/ を読み込む
│   ├── lawqa_eval.py          ← JuriCode-JP RAG で QA に回答 → 正答率測定
│   └── ab_compare.py          ← e-Gov XML vs JuriCode-JP の比較
└── tests/
    └── test_lawqa_loader.py
```

### 5.2 lawqa_loader.py の設計

```python
from pathlib import Path
from pydantic import BaseModel

class LawqaEntry(BaseModel):
    """lawqa_jp の 1 問を表す."""
    file_name: str             # "金商法_第2章_選択式_..."
    order_map_no: str          # "1"
    context: str               # Markdown context
    instruction: str           # 指示文
    question: str              # 問題文
    choices: str               # "a ~\nb ~\nc ~\nd ~"
    answer: str                # "c"
    references: list[str]      # ["https://laws.e-gov.go.jp/law/..."]

def load_lawqa(data_dir: Path) -> list[LawqaEntry]:
    """data/selection.json を読み込む."""
    ...

def filter_by_law_ids(
    entries: list[LawqaEntry],
    law_ids: list[str],
) -> list[LawqaEntry]:
    """references URL から特定法令の問題だけ抽出.
    
    例: filter_by_law_ids(entries, ["140AC0000000045"]) → 刑法の問題のみ
    """
    ...
```

### 5.3 lawqa_eval.py の評価フロー

```
1. lawqa_loader.load_lawqa() で全問題ロード
2. filter_by_law_ids() で Phase 1 法令の問題に絞る
3. 各問題について:
   a. 問題文を JuriCode-JP コーパスで RAG 検索
   b. Top-K チャンクを LLM(Claude)に渡す
   c. 多肢選択回答を生成
   d. lawqa_jp の output と比較
4. 集計:
   - 正答率(accuracy)
   - 引用精度(検索結果に references[] の URL が含まれる割合)
   - Top-K recall(references[] が Top-K に含まれる割合)
```

### 5.4 ab_compare.py の差分比較

```
1. 同じ問題を 2 つの RAG で解かせる:
   - A 群: e-Gov 生 XML 全文をベクトル化したベースライン
   - B 群: JuriCode-JP 構造化データ(条文単位 + メタタグ + 判例リンク)
2. 両群の正答率・引用精度を比較
3. 差分を JSON でエクスポート → デジタル庁公式 note 用エビデンス
```

---

## 6. 取り込み時の注意点

### 6.1 ライセンス互換性

| 項目 | 確認 |
|---|---|
| lawqa_jp のライセンス | 公共データ利用規約 v1.0 |
| JuriCode-JP のライセンス | MIT |
| 互換性 | **OK**(公共データは MIT プロジェクトでも利用可、出典明記必須) |
| 取り込み方法 | lawqa_jp を JuriCode-JP リポに**含めない**、別途 `git clone` or `pip install` で取得する設計 |

### 6.2 法令番号(law_id)の対応

`references` の URL 形式: `https://laws.e-gov.go.jp/law/323AC0000000025`
→ パスの最終要素が e-Gov 法令 ID。`tools/fetch-egov/law_id_map.py` の `LAW_ID_MAP` と突合可能。

### 6.3 漢数字変換

コンテキストの `### 第5条` は算用数字、`### 第三十六条` は漢数字。JuriCode-JP の `article_number` は算用数字統一(`"36"`)なので、`tools/transform/normalize_article_number()` で正規化してから突合。

### 6.4 機械的に弱い箇所

- `選択肢` フィールドが改行区切り文字列 → パースが必要
- `回答オーダーマップ番号` の意味は要確認(randomized 版との対応?)
- `指示` フィールドは `<following_context>` 等の特殊トークン含む → 解析時に除外

---

## 7. 実装スケジュール(Phase 1 後半に着手)

| 時期 | アクション |
|---|---|
| 2026-08 中旬 | lawqa_jp リポを clone、`law_list.json` を確認して Phase 1 法令の問題数を把握 |
| 2026-09 上旬 | `tools/validate/lawqa_loader.py` 実装 + テスト |
| 2026-09 下旬 | `tools/validate/lawqa_eval.py` 実装、Claude API 経由で初回評価 |
| 2026-10 中旬 | `tools/validate/ab_compare.py` 実装、e-Gov XML vs JuriCode-JP の A/B 検証エビデンス取得 |
| 2026-11 上旬 | デジタル庁公式 note への投稿準備、Phase 1 MVP リリースと同時に発信 |

### 7.1 早期着手のオプション(NLnet 提出前、5/19-27)

- **5/19-22 中**: lawqa_jp リポを `git clone` してデータ確認 → Phase 1 法令の問題数だけでも把握
- **NLnet draft Section B/H に追記**: 「**Validation will use lawqa_jp**(Digital Agency Oct 2025 release)— first benchmark dataset designed specifically for Japanese law RAG. We will publish A/B comparison results (e-Gov raw vs JuriCode-JP) post-MVP.」

---

## 8. 戦略的含意

### 8.1 「デジタル庁の正解データで評価」という強さ

JuriCode-JP の品質を**第三者作成のベンチマークで客観的に評価できる**こと自体が、grant 応募ナラティブで強力。

| 文脈 | 訴求点 |
|---|---|
| NLnet | 「Evaluation against Digital Agency's official QA benchmark, not our own metrics」 |
| Tokyo Award | 「都の課題解決に資する AI 基盤の精度を、国の公式データセットで検証」 |
| デジタル庁 note | 「同じデジタル庁の lawqa_jp でテスト → JuriCode-JP のデータ層が源内 Lawsy 互換」 |

### 8.2 既存プロジェクトとの差別化エビデンス

| プロジェクト | lawqa_jp での評価可能性 |
|---|---|
| gitlaw-jp(aluqas)| 条文構造化なし、RAG 評価不可 |
| Lawtext(yamachig)| プレーンテキスト、RAG 評価可能だがメタタグなし |
| ja-law-parser(takuyaa)| パーサのみ、RAG パイプライン不在 |
| e-Gov MCP(ryoooo)| リアルタイム取得、ベンチマーク評価には不向き |
| **JuriCode-JP** | **lawqa_jp で end-to-end 評価可能、A/B 検証エビデンス取得可能** |

---

## 9. 出典

- [GitHub: digital-go-jp/lawqa_jp](https://github.com/digital-go-jp/lawqa_jp)
- [デジタル庁: 政府等が保有するデータの AI 学習データへの変換に係る調査研究](https://www.digital.go.jp/news/382c3937-f43c-4452-ae27-2ea7bb66ec75)
- [植松 幸生, 大杉 直也, 複数の LLM を用いた法令 QA タスクの Ground Truth Curation, 言語処理学会第31回年次大会(NLP2025)](https://www.anlp.jp/proceedings/annual_meeting/2025/pdf_dir/Q6-3.pdf)
- [デジタル庁公式 note: 日本の法令に関する多肢選択式 QA データセット公開の背景](https://digital-gov.note.jp/n/n6395fb0ad874)
- [デジタル庁の公開 QA データセット lawqa_jp で簡単に RAG 性能を評価できるフレームワークを作った | Zenn](https://zenn.dev/aidemy/articles/8878361e861b99)

---

*最終更新: 2026-05-18 / 作成者: Claude(Cowork セッション)*
*次回更新の目安: 2026-08(`tools/validate/lawqa_loader.py` 実装着手時)*

# Follow-up Tracker — Known Limitations & Future Work

> JuriCode-JP の現バージョン (v0.1, 2026-05-18) で**意図的に未実装としている項目**および**改善余地**を一覧化する。
>
> このファイルは外部コントリビューターと将来の自分への "TODO" 兼 "なぜ今こうなっているか" の説明.
> 完了した項目はチェックを入れて行内に commit hash / PR 番号を残す.
>
> **凡例**:
> - **P0** = Phase 1 ロールアウト成立性に関わる gate-keeper. 5/28 NLnet 提出前は文書/設計面、採択結果が出る ~2026-08 までに 1st pass MVP 必須
> - **P1** = Phase 1 着手前 (〜2026-06 末) に潰したい
> - **P2** = Phase 1 中期 (2026-07〜09) に対応
> - **P3** = Phase 1 後期 (2026-10〜) に対応、または Phase 2 で見直し

---

## P0 — Phase 1 ロールアウト gate-keeper (5/28 提出後すぐ着手)

> 2026-05-19 追加 / 同日に方針調整. NLnet 申請書で約束した Phase 1 deliverable と現状実装の乖離を埋める設計判断.
> 同日, ターゲットを「警察」から「警察 + 自治体 + 法律実務家」へ拡大 ([[project-juricode-target-users]]), 英訳系 (旧 FU-P0-2) は P2 (FU-107) に降格, 代わりに自治体ユース対応の追加法令 (新 FU-P0-2) を P0 に組み入れ.
> 5/28 NLnet 提出までは**設計と着手判断**まで, 採択結果が出る ~2026-08 までに**1st pass MVP**を目標.

### [ ] FU-P0-1: `tools/parse/` MVP の設計と着手 (NLnet M2)

**現状**: `tools/parse/` は README のみ, コードゼロ.

**問題**: NLnet M2 (€7,000) で「e-Gov XML → JuriCode-JP Markdown converter, 刑法 264 条カバー」を約束しているが,
12 ヶ月で 264 条を手作業 Markdown 化することは佐藤さん一人では不可能. 自動 converter が**Phase 1 全体の律速**.

**やること**:

1. 既存 OSS の活用判断: [ja-law-parser (takuyaa)](https://github.com/takuyaa/ja-law-parser) と [Lawtext (yamachig)](https://github.com/yamachig/Lawtext) の AST が JuriCode-JP IR に変換できるか調査. ゼロから書くより wrapper 化を優先
2. 最小動作版: 刑法第 36 条 1 件で round-trip (e-Gov XML → IR → Markdown → IR) が通ることを示す
3. 1st pass MVP: 刑法 1〜10 条が変換できる状態, 残り 254 条は反復で潰す

**スケジュール目処**: 6 月設計, 7 月 MVP, 8〜11 月で 264 条網羅.

**関連**: [[reference-jp-oss-projects]] (OSS 4 名打診戦略, [FU-P0-2] と並列に進める)

---

### [ ] FU-P0-2: 自治体ユース対応の追加法令を Phase 1 スコープに含める (2026-05-19 追加)

**現状**: data/phase1-police/ は警察用法令 (刑法/刑訴法/警察法/警職法) のみを想定. 自治体ユースに必要な法令が Phase 1 スコープ外.

**問題**: 2026-05-19 にターゲットを「警察」から「警察 + 自治体 + 法律実務家」へ拡大決定 ([[project-juricode-target-users]]). 自治体実務で日常的に参照される
**行政手続法 / 地方自治法 / 行政不服審査法** が Phase 1 スコープに入っていないと, 8-9 月の「自治体ユース起動」が成立しない.

**やること**:

1. `data/phase1-police/` を `data/phase1-domestic/` 等にリネーム検討 (もしくは並列に `data/phase1-administrative/` を新設)
2. 追加対象法令の条文インベントリ作成:
   - **行政手続法** (88 条)
   - **地方自治法** (主要条のみ抜粋: 自治体組織・条例制定権・住民監査請求等の核条文)
   - **行政不服審査法** (主要条)
3. 追加法令の `law_id` / 略称 / 英訳 (英訳は枠だけ) を `docs/glossary.md` に登録
4. Phase 1 タイムテーブル更新: 7 月警察, 8-9 月自治体, 10-11 月実務家 (民法主要条 + 検索 UI)

**スケジュール目処**: 6 月中にスコープ確定とインベントリ, 8 月に取得・構造化着手.

**関連**: [[project-juricode-target-users]] — 三本柱の二本目を支える法令データ.

---

### [ ] FU-P0-3: `tools/export/lawsy-bq/` の骨子設計 (NLnet M5)

**現状**: `tools/export/lawsy-bq/` ディレクトリ**未作成**. 設計メモすらない.

**問題**: NLnet M5 (€5,000) で「源内 Lawsy-Custom-BQ exporter + A/B ベンチマーク」を約束. これは JuriCode-JP の対外証明力で
**最も強い deliverable** (政府 OSS との接続を実物で示す). この実装がないと「Phase 0 plumbing は揃ったが downstream への接続は妄想」
と取られる. Anthropic OSS Program 再応募 (2026-09) の hedge clause 主張材料にもなる.

**やること**:

1. 源内 Lawsy-Custom-BQ の BigQuery スキーマ把握 (`digital-go-jp/genai-ai-api` リポを読む)
2. JuriCode-JP Markdown → BigQuery 投入用 JSON-L 変換スクリプト
3. ベンチマーク設計: e-Gov 単体 vs JuriCode-JP 拡張の RAG 回答精度比較プロトコル
4. ローカル / GCP 個人アカウントで Lawsy-Custom-BQ を動かし, 最初の 10 条で A/B 取れる状態

**スケジュール目処**: 7-8 月設計, 9-10 月ベンチマーク, 11 月に Qiita/note で公開.

**関連**: [[reference-gennai-digital-agency]] (源内エコシステムは Phase 1 の最有力ダウンストリーム)

---

### [ ] FU-P0-4: データ source の法的整合性レビュー

**現状**: e-Gov 利用規約 / 法務省「日本法令外国語訳 DB」利用規約 / 裁判所判決要旨の OSS 配布可否を**法務的にレビューしていない**.

**問題**: MIT 公開と上記 source の規約整合に gray zone がある可能性. 法令本文は政府著作物 (著作権法 13 条) で著作権なしだが,
(a) e-Gov 利用規約 (再配布条件・帰属表示要求), (b) 法務省訳の community/draft 取込時のクレジット表記, (c) 裁判所サイトの判決全文・要旨の引用範囲 — 各々が MIT 公開と整合するかを**専門家の判断**を仰ぐ必要. 既に違反していると分かった時点で
Phase 1 deliverable の構成が大きく変わる可能性があり, **Phase 1 着手前に確定**が必要.

**やること**:

1. 松尾研出身 AI 法務弁護士 (5/17 紹介済) にチケット化
2. e-Gov / 法務省 / 裁判所 各々の利用規約原文を整理し相談ペーパーを作成
3. レビュー結果を `docs/legal-review.md` (or 同等) として記録. 必要なら README に "Data Sources & Attribution" セクション追記

**期限**: Phase 1 本格着手 (~2026-07) 前.

**関連**: [[project-juricode-advisory]] (アドバイザー三角形構築中, このタスクは法務弁護士の最初の本気依頼として位置付け)

---

### [ ] FU-P0-5: Phase 1 の人月配分・外注/コントリビューター動員設計

**現状**: 75 条 + tooling 一式を 12 ヶ月 / €30,000 (~480 万円) で仕上げる前提だが, **誰がどれをやるかの内部試算がない**.

**問題**: 佐藤さん一人で全部やる前提だと, CLAUDE.md ポリシー (1 コミット数条 + 検証挟む) で月 6-7 条が上限. 75 条 + parse/translate/lawsy-bq の tooling は破綻する. 一方で 4 名の OSS コントリビューター打診 ([[project-juricode-oss-outreach-strategy]]) や,
翻訳・判例リサーチ外注の検討は今まで「やる」だけで具体的工数試算がない.

**やること**:

1. M1-M6 deliverable ごとの工数試算 (条文整備, parse 実装, translate 実装, lawsy-bq, 判例リサーチ, ドキュメント)
2. 内製 / 外注 / コントリビューター動員の配分マトリクス
3. €30,000 の内訳明細 (外注予算が NLnet 規約上どこまで使えるかの確認含む)
4. コントリビューター打診を「採択前提のスケジュール」に統合 (今は別軸で進行中)

**期限**: NLnet 採択結果が出る ~2026-08 までに完成. 採択された日から逆算して動けるように.

**関連**: [[project-juricode-oss-outreach-strategy]], [[project-juricode-anthropic-oss-program]] (依存実績作りの一環としてもこの設計は重要)

---

## P1 — Phase 1 着手前 (〜2026-06 末)

### [ ] FU-001: `case_id` の命名規約を確定する

**現状**: サンプルファイル内で 2 種類の表記が混在.

- `examples/keihou/keihou-article-36.md` → `scj-1969-12-04-keishu-23-12-1573` (法廷略号なし)
- `tools/shared/tests/test_ir.py` 内のテストデータ → `scj-pb1-1969-12-04-keishu-23-12-1573` (法廷略号 `pb1` あり)
- `tools/shared/src/juricode_shared/ids.py` の `make_case_id()` docstring → 法廷略号あり

**両方とも `CASE_ID_PATTERN` を通る**ため IR validation では落ちないが、コミュニティが追加する判例リンクで規約が拡散する.

**やること**:

1. `docs/ir-spec.md §4.2` (`case_id` セクション) で**正規パターンを明示**
2. 推奨案: 法廷略号は `case_id` に埋め込まず、別フィールド (`bench_abbrev: "first-petty"` 等) で持つ. ID は機械的に決まるべき
3. 既存サンプルとテストデータを統一

**関連**: `docs/glossary.md` (裁判所略号一覧追加検討)

---

### [ ] FU-002: ファイル名規約を `paths.py` に集約する

**現状**: `{law-abbrev}-article-{N}.md` パターンが 3 箇所に重複.

- `tools/shared/src/juricode_shared/paths.py:29` の `article_path()`
- `tools/validate/_validate.py:84-85` の filename mismatch チェック
- `data/phase1-police/*/README.md` の docstring (4 ファイル)

規約変更時に drift しやすい.

**やること**:

```python
# paths.py に追加
def article_filename(law_abbrev: str, article_number: str) -> str:
    return f"{law_abbrev}-article-{article_number}.md"
```

`_validate.py` の該当箇所を `paths.article_filename()` 呼び出しに置き換え.

---

### [ ] FU-003: `Pydantic ValidationError` の structured 出力化

**現状**: `tools/validate/_validate.py:78` で Pydantic の `ValidationError` を文字列化してそのまま users に返している. 技術者には読めるが、新規 contributor には厳しい.

**やること**:

```python
except ValidationError as e:
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = err["msg"]
        errors.append(f"field '{loc}' — {msg}")
```

フィールドパス + 短い説明の形式に整形.

---

### [ ] FU-004: 失敗ケーステスト追加

**現状**: 41 件のテストはあるが、以下の failure path が未カバー.

- 空 frontmatter (`---\n---`)
- frontmatter デリミタ 1 つだけ
- 不正 YAML (`key: : value` 等)
- ParentSection 全 5 レベル (hen/shou/setsu/kan/moku) 同時指定
- `english_translation.paragraphs` の長さが `paragraphs` と異なるケース

**やること**: 上記を `tests/test_ir.py` / `tests/test_frontmatter.py` に追加.

---

### [ ] FU-005: `ir-spec.md §5.3` 警告の実装

**現状**: 仕様にある以下の warning が未実装.

- `translation_status == OFFICIAL` で `english_translation.source` が空 → 警告
- `notes` が 500 字超 → 警告

**やること**: `tools/validate/_validate.py` に warning 出力ロジック追加.

---

### [ ] FU-006: 法令改正の追跡メカニズム設計 (2026-05-19 追加)

**現状**: `JuriCodeArticle.amendments[]` フィールドは IR にあるが, e-Gov 法令 API の change feed を購読して `version_date` を
自動更新する仕組みがない. 現状は「公開時点の現行条文を手動でコピー」している.

**問題**: Phase 1 で「現行条文」を看板にする以上, 改正後 1〜2 週でデータが古くなる構造リスク. Phase 2 (民法 ~1,050 条 + 商法 ~850 条) のスケールでは
手動チェックは破綻する. 月次 diff スクリプトを Phase 1 中期までに用意したい.

**やること**:

1. e-Gov 法令 API の更新通知 / 差分取得手法を調査 (RSS / Atom / API polling)
2. `tools/track-amendments/` (or 同等) スクリプト: 全 JuriCode-JP 条文 vs 最新 e-Gov を月次 diff
3. 改正検知時に GitHub Issue 自動起票 → コントリビューターが PR で `amendments[]` を追記する運用

**関連**: [FU-P0-1] (`tools/parse/`) と base コードを共有できる可能性.

---

## P2 — Phase 1 中期 (2026-07〜09)

### [ ] FU-101: `ARTICLE_ID_PATTERN` の特殊条文対応

**現状**: `r"^[a-z][a-z0-9-]*-art-[0-9]+(-[0-9]+)*$"` は附則・経過措置を弾く.

**やること**: パターンを `r"^[a-z][a-z0-9-]*-art-([a-z0-9]+)(-[a-z0-9]+)*$"` に緩める. または `docs/format-spec.md` に「Phase 1 では本則のみ、附則は Phase 2」と明記.

---

### [ ] FU-102: CLI を `pyproject.toml` の entry point 化

**現状**: `tools/validate/validate-file.py` 等がハイフン命名で Python module としては import できない. `sys.path` パッチで回避.

**やること**: `pyproject.toml` に `[project.scripts]` を追加.

```toml
[project.scripts]
juricode-validate-file = "juricode_validate.cli:validate_file_main"
juricode-validate-all = "juricode_validate.cli:validate_all_main"
```

`pip install -e ".[dev]"` 後にどこからでも `juricode-validate-file path.md` で動く.

---

### [ ] FU-103: `juricode-shared` を proper installable に

**現状**: `tools/validate/_validate.py` に `sys.path.insert` でパス追加. monorepo の構造変更で壊れやすい.

**やること**: workspace 化. uv または pip-tools で `tools/shared`, `tools/validate`, `tools/fetch-egov` を editable install で一括管理.

---

### [ ] FU-104: `source_url` を `pydantic.HttpUrl` 化

**現状**: `str` のみ. URL でない値も通る.

**やること**: `tools/shared/src/juricode_shared/ir.py` の `JuriCodeArticle.source_url` を `HttpUrl` に. 既存サンプルが通るかは事前に検証.

---

### [ ] FU-105: `law_id` フォーマット regex 化

**現状**: `str` のみ. e-Gov 法令 ID 形式 (例: `140AC0000000045` = `[元号略][年]AC[type][番号]`) を強制していない.

**やること**: 正確な形式を `docs/ir-spec.md` に書いた上で regex 化.

---

### [ ] FU-106: 判例リンク取得自動化の方針決定 (2026-05-19 追加)

**現状**: 判例リンクは「裁判所 Web の永続 URL を手動でコピー」する想定. 取得自動化は未設計, 商用 DB との関係も未整理.

**問題**: NLnet M3 (€6,000) で「判例キュレーション・パイプライン」を約束しているが, 実装方針が決まっていない. 選択肢:

- (a) 裁判所サイト (`courts.go.jp`) HTML スクレイピング — permalink あり, ただし全文検索 API なし, スクレイピング規約要確認
- (b) 商用 DB 経由 (LIC 判例秘書, TKC LEX/DB) — メタデータは取れる可能性あるが MIT 公開との整合要レビュー
- (c) 手動キュレーション + コミュニティ動員 — Phase 1 では現実的, ただし Phase 2 でスケールせず

**やること**:

1. 各選択肢の (i) 法的整合性, (ii) スケール, (iii) 工数 を一覧化
2. Phase 1 の方針 (おそらく (c) ベース) と Phase 2 へのスケール戦略を `docs/case-law-strategy.md` (or 同等) に明記
3. FU-P0-4 (法務レビュー) と連動: 判決全文・要旨の OSS 配布範囲の判断材料を法務弁護士に確認

**関連**: [FU-205] (判例 URL 生存確認スクリプト) はこの方針が決まってから設計.

---

### [ ] FU-107: `tools/translate/` MVP (旧 FU-P0-2 から降格, 2026-05-19)

**降格理由**: 2026-05-19 にターゲットを国内三本柱 (警察 + 自治体 + 法律実務家) に再定義 ([[project-juricode-target-users]]).
英訳は国際拡張側の deliverable であり, 国内ユース (源内接続・自治体・法律実務家) には必須でない. NLnet ナラティブには残すが,
実装優先度は Phase 1 中期 (2026-07〜09) に降格. spec の `english_translation` フィールドは枠だけ残し中身は空で運用可能.

**現状**: `tools/translate/` は README のみ, コードゼロ.

**やること**:

1. 法務省「日本法令外国語訳 DB」の取得手法決定 (API か, スクレイピングか, バルクダウンロードか)
2. 公定訳と JuriCode-JP IR のマッピング (Paragraph 単位 / 条文単位の粒度)
3. draft 訳パイプライン: Claude API で生成 → `translation_status: draft` + `machine_translated: true` で書き出し
4. PR レビュー時のチェック: `translation_status: official` 主張なら公定訳 source URL 必須 (FU-005 の warning と統合)

**NLnet M4 (€5,000) との関係**: NLnet 採択時の進捗報告では「英訳パイプラインは Phase 1 中で MVP, 充実化は Phase 2 (2027〜)」と説明可能.

---

## P3 — Phase 1 後期以降 (2026-10〜) / Phase 2 検討

### [ ] FU-201: `ParentSection` を多言語対応構造に変更

**現状**: `hen: int + hen_name_ja + hen_name_en` flat 構造. 中国語・韓国語追加時にフィールドが増殖.

**Phase 2 でやること** (Phase 1 中は不要):

```python
class ParentLevel(BaseModel):
    number: int
    names: dict[str, str]  # {"ja": "第一編 総則", "en": "Part I", ...}

class ParentSection(BaseModel):
    hen: ParentLevel | None
    shou: ParentLevel | None
    ...
```

ただし Phase 1 では JA/EN のみで足りるため、データマイグレーションコストとのトレードオフで判断.

---

### [ ] FU-202: `Paragraph.text` の設計を spec で明文化

**現状**: `text` は frontmatter には含まれず Markdown body から `tools/parse/` で埋める設計だが、ir.py の docstring にしか書かれていない. 外部の IR JSON 利用者は気付けない.

**やること**: `docs/ir-spec.md §3.2` に「frontmatter には text を載せない、body から populate される」を明記. 必要なら `IRMetaOnly` / `IRWithBody` の型分離も検討.

---

### [ ] FU-203: frontmatter ダンプ順序の制御

**現状**: `frontmatter.dump_frontmatter()` は Pydantic model 定義順で出力. canonical sample のキー順と微妙にずれる可能性. round-trip 自体は問題ないが PR diff が肥大化する.

**やること**: 重要度低. canonical なフィールド順序を `_FIELD_ORDER` リストで明示制御.

---

### [ ] FU-204: `field_validator` の `info` を `ValidationInfo` 型に

**現状**: `info: Any` で書いている (Pydantic v2 の型を明示していない).

**やること**:

```python
from pydantic import ValidationInfo

@field_validator(...)
def some_validator(cls, v, info: ValidationInfo):
    ...
```

mypy / pyright で型がより厳密に追える.

---

### [ ] FU-205: 判例 URL 生存確認スクリプト

**現状**: `tools/validate/` の README で予告済みだが未実装.

**やること**: `tools/validate/check-case-urls.py` を実装. `--since-days 30` で過去 30 日以内に未確認の URL を再検証. 503/404 を warning にする.

---

### [ ] FU-206: 条文間クロスリファレンスの IR 拡張 (2026-05-19 追加)

**現状**: Pydantic IR は「1 条」単位での構造化に閉じていて, 条文間の参照 (例: 刑法 36 条 1 項 ↔ 刑法 36 条 2 項, 刑法 36 条 ↔ 刑事訴訟法 198 条) を機械可読に表現する仕組みがない.

**問題**: Phase 1 (4 法令 ~75 条) では影響小. ただし Phase 2 (民法・商法) で他法律への参照が爆発的に増えると, RAG 用途で「関連条文を辿る」探索クエリが弱くなる. 後付け改修は IR 破壊変更で migration コスト大.

**やること** (Phase 2 着手前 or 必要が出たタイミング):

```python
class ArticleReference(BaseModel):
    law_id: str         # 参照先法令ID
    article_id: str     # 参照先 article_id
    paragraph: int | None  # 参照先項番号 (任意)
    relation: Literal["see-also", "supersedes", "supersededby", "implements", ...]

class JuriCodeArticle(BaseModel):
    ...
    references: list[ArticleReference] = Field(default_factory=list)
```

graph traversal を考慮するなら別途グラフ DB (Neo4j 等) への export 検討.

**関連**: [FU-201] (ParentSection 多言語化) と同じく Phase 2 着手時の大きな IR 進化検討.

---

### [ ] FU-207: CI / validate-all.py の差分検証・並列化 (2026-05-19 追加)

**現状**: CI ジョブ "Validate all law data files" は `tools/validate/validate-all.py` で全ファイルを線形ループ. Phase 1 (~75 ファイル) では問題ないが,
Phase 2 (~1,900 ファイル) / Phase 3 (数千ファイル) で PR ごとの CI 時間が膨らむ.

**やること** (Phase 2 着手前):

1. `validate-all.py` に `--changed-since GITREF` 等の差分モードを追加
2. CI 上で `pull_request` イベントの場合は変更ファイルのみ検証, `push to main` のときだけ全件検証
3. 並列化 (Python `multiprocessing` or pytest-xdist 流用)

**関連**: Phase 2 着手前にやらないと, データ追加が増えるほど PR レビューの待ち時間が増える.

---

## 完了済み

完了した項目はここに timestamp 付きで移動する.

### 2026-05-18

- ✅ **P0-1: `SourceFormat` を 4 値に拡張** — `docs/ir-spec.md §3.1` で `e-gov-html` 追加 + 各値の使い分けガイド付記
- ✅ **P0-2: IR integrity rule 3 件追加** — `cases_relevant_paragraph_exists`, `english_translation_implies_status`, `machine_translated → DRAFT` 推奨警告
- ✅ **P0-3: canonical サンプルのタグを vocabulary 準拠に** — `刑事法` を必須カテゴリ B として追加

---

## 関連

- 内部レビュー文書 (gitignored): `business/code-reviews/2026-05-18-tools-and-schema-review.md`
- 仕様書: [docs/ir-spec.md](./ir-spec.md), [docs/format-spec.md](./format-spec.md), [docs/tag-vocabulary.md](./tag-vocabulary.md)
- 検証ツール: [tools/validate/README.md](../tools/validate/README.md)

---

*Last updated: 2026-05-19 (2回目) / Maintained by: CHOKAI Co.,Ltd. / Status: v0.3 — 国内三本柱ターゲット (警察 + 自治体 + 法律実務家) 確定に伴う組み替え. 旧 FU-P0-2 (translate MVP) を FU-107 へ降格, 新 FU-P0-2 「自治体用追加法令の Phase 1 スコープ追加」を P0 に組入れ*

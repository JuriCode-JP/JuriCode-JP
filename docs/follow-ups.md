# Follow-up Tracker — Known Limitations & Future Work

> JuriCode-JP の現バージョン (v0.2.1, 2026-05-22) で**意図的に未実装としている項目**および**改善余地**を一覧化する。
>
> このファイルは外部コントリビューターと将来の自分への "TODO" 兼 "なぜ今こうなっているか" の説明.
> 完了した項目はチェックを入れて行内に commit hash / PR 番号を残す.
>
> **凡例**:
> - **P0** = Phase 1 ロールアウト成立性に関わる gate-keeper. 5/28 NLnet 提出前は文書/設計面、採択結果が出る ~2026-08 までに 1st pass MVP 必須
> - **P1** = Phase 1 着手前 (〜2026-06 末) に潰したい
> - **P2** = Phase 1 中期 (2026-07〜09) に対応
> - **P3** = Phase 1 後期 (2026-10〜) に対応、または Phase 2 で見直し
>
> **FU 番号体系**:
> - `FU-001..006` / `FU-101..108` / `FU-201..207` / `FU-P0-1..5` — 初期 + 2026-05-19/20 追加分
> - `FU-301..321` — 2026-05-24 v0.2 parser pipeline + shared レビュー由来 (`business/code-reviews/2026-05-24-v02-parser-pipeline-review.md`)
> - `FU-401..431` — 2026-05-24 tools/ フルレビュー由来 (`business/code-reviews/2026-05-24-full-tools-review.md`)
> - `FU-501..503` — 2026-05-26 FU-415 sweep + embed corpus 再構築で発覚した stale 経路・CI 統合余地

---

## P0 — Phase 1 ロールアウト gate-keeper (5/28 提出後すぐ着手)

> 2026-05-19 追加 / 同日に方針調整. NLnet 申請書で約束した Phase 1 deliverable と現状実装の乖離を埋める設計判断.
> 同日, ターゲットを「警察」から「警察 + 自治体 + 法律実務家」へ拡大 ([[project-juricode-target-users]]), 英訳系 (旧 FU-P0-2) は P2 (FU-107) に降格, 代わりに自治体ユース対応の追加法令 (新 FU-P0-2) を P0 に組み入れ.
> 5/28 NLnet 提出までは**設計と着手判断**まで, 採択結果が出る ~2026-08 までに**1st pass MVP**を目標.
>
> 2026-05-24 追加: 2 本のコードレビューで判明した「再現性ある事故源」8 件を FU-301..304 / FU-401..404 として追加. NLnet 5/28 提出までの 4 日間スプリントで全件解消予定. 詳細計画は `business/code-reviews/2026-05-24-fix-plan.md`.

### [x] FU-P0-1: `tools/parse/` MVP の設計と着手 (NLnet M2) — ✅ 完了 2026-05-19

`tools/parse/parse-egov.py` (18KB) + `verify.py` + `_canonicalize.py` を実装. Phase 1 警察 1,118 条 + 自治体 651 条 = **1,769 条を ingest 済み** (NLnet M2 約束 264 条の 6.7 倍).

詳細は本ファイル末尾「完了済み」セクション 2026-05-19 参照. 完成度検証 (全件 round-trip / コーナーケース) は P2 [FU-108] に移管.

---

### [x] FU-P0-2: 自治体ユース対応の追加法令を Phase 1 スコープに含める (2026-05-19 追加) — ✅ 完了 2026-05-19

`data/phase1-administrative/` を新設し, **地方自治法 516 条 + 行政不服審査法 87 条 + 行政手続法 48 条 = 651 条** を ingest 済み (commit 6ed72d7).

詳細は本ファイル末尾「完了済み」セクション 2026-05-19 参照. 要検証項目 (行政手続法の想定 88 条 vs 実装 48 条の差, 地方自治法の本則全文 vs 主要条抜粋の方針確定) は P2 [FU-108] に移管.

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

### [x] FU-301: PARAGRAPH_HEADING_PATTERN の 2 重定義集約 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `bf773b58` + test `1861d26b`)

`tools/parse/v0.2/segment_parser.py` の paragraph 見出し regex 2 重定義を module-level `PARAGRAPH_HEADING_PATTERN` に集約。枝番条網羅テスト `tests/test_paragraph_heading_pattern.py` を新規追加 (`第三条` / `第三条の二` / `第百九十七条の三第二項` / `第三条第一項` をカバー)。

詳細は本ファイル末尾「完了済み」セクション 2026-05-25 参照.

---

### [x] FU-302: 全 parser に write 後 sanity check を追加 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `094fcfdd` + `bf773b58`)

`tools/shared/src/juricode_shared/safe_write.py` を新設 (atomic write + NUL/末尾改行/UTF-8/JSONL 各行 json.loads 可を assert) + `tools/shared/tests/test_safe_write.py` で 17 件 unit test 全 pass. 5 parser の write 経路を `safe_write_text` / `safe_write_jsonl` / `safe_append_jsonl_records` に置換.

詳細は本ファイル末尾「完了済み」セクション 2026-05-25 参照.

**場所**: `tools/parse/v0.2/{segment_parser,extract_kou_from_xml,extract_supplproviso_from_xml,add_rollup_chunks}.py` および `tools/parse/parse-egov.py` の write_text / fh.write 直後.

**問題**: 既知事故 (a) WSL ruff corruption / (b) Edit/Write NUL padding / (c) cat heredoc 二重貼り付け のいずれも parser 側に検知機構がない. 静かに壊れた `.md` / `.chunks.jsonl` が増産される.

**やること**: 共有ヘルパー `tools/shared/src/juricode_shared/safe_write.py` を新設.

- `safe_write_text(path, content)`: NUL バイト不在 / 末尾改行 / UTF-8 valid を assert
- `safe_write_jsonl(path, records)`: 各行 `json.loads` 可を assert
- 違反時は `.tmp` を残して元ファイル維持 (atomic write パターン)

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §D-02 / Day 3.A

---

### [x] FU-303: segment marker `replace(..., 1)` のスコープ限定 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `bf773b58` + test `1861d26b`)

paragraph 見出し直下から「次の paragraph 見出しまたは `## ` まで」のスコープに限定して挿入。失敗時は `parsing_warnings: list[str]` に記録 (silent fail 阻止). `tests/test_render_v02_md_scope.py` 7 件 PASS。

詳細は本ファイル末尾「完了済み」セクション 2026-05-25 参照.

---

### [x] FU-304: AmendLawNum regex を literal alternation 化 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `50b9408a` + test `1861d26b`)

`AMEND_LAW_NUM_PATTERN` を greedy match `(?:[^第]*第N号)?` から literal alternation `(?:(?:法律|政令|規則|省令|府令|告示|条約)第N号)?` に置換。「雑種」等未対応 prefix は law_num=None として下流で安全に弾けるように。Why コメント 6 行追加. `tests/test_amend_law_num_pattern.py` 10/10 PASS.

詳細は本ファイル末尾「完了済み」セクション 2026-05-25 参照.

---

### [x] FU-401: parse-egov.py phase tag のハードコード解消 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `787203e8`)

`parse-egov.py` に `--phase-tag` を必須引数として追加 (default なし、未指定で argparse exit 2)。`article_to_markdown` / `_emit_article` / `main` の call chain で `phase_tag` を透過。`bulk-ingest.py:171-183` の subprocess cmd 構築に `["--phase-tag", phase]` を追加 (PHASE_MAP の既存値を渡す).

副次発見: 既存 corpus に `tag[0] = phase1-police` のままになっているファイルが多数 (phase2-commercial/* 全件、phase1-tax/chihou-zei-hou ほか). sweep は FU-415 (P1, 6 月集中) で別途対応.

詳細は本ファイル末尾「完了済み」セクション 2026-05-25 参照.

---

### [x] FU-402: retrieve.py `settings = []` 2 重代入を削除 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `b091c3e7`, Day 1.A push)

`tools/embed/retrieve.py:774-775` の `settings = []` 2 重代入 (dead code) を削除. 詳細は本ファイル末尾「完了済み」セクション 2026-05-25 (P0 sprint Day 1.A) 参照.

**場所**: `tools/embed/retrieve.py:774-775`. `settings = []` が 2 行連続. dead code.

**問題**: レビューを通過した証拠 (品質意識への直接の信号). ruff F841 でも引っかかる可能性.

**やること**: 1 行削除. CI の ruff check を強制 (現状 follow-up 中).

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §D-01 / Day 1.A

---

### [x] FU-403: validate-all.py に argparse 追加 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `2150bd89`)

`tools/validate/validate-all.py` を argparse 化 (`--path`, `--verbose` を `verify.py` と命名揃え, 旧 REPO_ROOT 固定を解除). `--path /tmp/empty_dir` で「0 files」エラー化 (silent ignore 解消, exit 1). `tools/fetch-egov/bulk-ingest.py:209` の subprocess.run 呼び出しを `--data-root` から `--path` に追従修正済.

詳細は本ファイル末尾「完了済み」セクション 2026-05-25 参照.

**場所**: `tools/validate/validate-all.py` は argparse なし、`sys.argv` を読まず `REPO_ROOT` 固定. `tools/fetch-egov/bulk-ingest.py:209` が `--data-root` 引数を渡すが silently 無視.

**問題**: 非標準 data-root での bulk-ingest 検証は「実は何も検証していない」状態. 偽の green CI が出る.

**やること**:
1. `validate-all.py` に argparse を追加 (`--path`, `--verbose` を `verify.py` と命名揃え)
2. `bulk-ingest.py:209` を `--path str(data_root)` に修正
3. 検証: `python validate-all.py --path /tmp/empty_dir` で「0 files」エラー (silent ignore でない)

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §D-02 / Day 3.B

---

### [x] FU-404: search-ui/server.py の `with_suffix()` バグ修正 (2026-05-24 追加) — ✅ 完了 2026-05-25 (commit `b091c3e7`, Day 1.A push)

`tools/search-ui/server.py:46-48` の 3 行を `prefix.with_suffix(".npy")` パターンから文字列連結に修正. 詳細は本ファイル末尾「完了済み」セクション 2026-05-25 (P0 sprint Day 1.A) 参照.

**場所**: `tools/search-ui/server.py:46-48`. `prefix.with_suffix(".npy")` 等 3 行が、ドット入り prefix (`v0.2-gemini-17967`) で `build/v0.npy` に化ける.

**問題**: `tools/embed/embed.py` と `tools/embed/retrieve.py` は既に「文字列連結」パターンに修正済. search-ui のみ取り残し. v0.2 corpus で検索 UI を立ち上げた瞬間 silent fail.

**やること**: 3 行を embed.py/retrieve.py と同じ `prefix.parent / (prefix.name + ".npy")` パターンに置換.

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §D-03 / Day 1.A

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

### [ ] FU-305: segment_parser.py を 5 module に分割 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py` (644 行). detector regex / kansuji / Segment dataclass / paragraph 分割 / md レンダ / chunks レンダ / CLI が同居.

**やること**: `detectors.py` / `splitter.py` / `renderer_md.py` / `renderer_chunks.py` / `cli.py` に分割. Segment dataclass は `tools/shared` の Pydantic Segment と統合.

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §A-01 / 計画 §4 Week 1

---

### [ ] FU-306: `make_chunk` 17 引数を context dataclass に (2026-05-24 追加)

**場所**: `tools/parse/v0.2/extract_supplproviso_from_xml.py:436-497`. 引数 17 個 (位置/キーワード混在).

**やること**: `SupplProvisionContext` dataclass (law_id, law_abbrev, law_name_ja, sp_idx, sp_label, amend_*, enforcement_date, effective_status) を導入し `make_chunk(ctx, chunk_id, text, ...)` に集約.

**関連**: §A-02 / 計画 §4 Week 1

---

### [ ] FU-307: `build_law_abbrev_to_id_phase` 重複排除 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/extract_kou_from_xml.py:64-86` と `extract_supplproviso_from_xml.py:406-426` でほぼ同一定義.

**問題**: 既知事故 (d) と同型. 片方を直して片方忘れる risk.

**やること**: `tools/shared/src/juricode_shared/law_index.py` に `build_law_index(data_dir) -> dict[abbrev, LawIndexEntry]` を一本化. `LawIndexEntry` に law_id / phase / law_name_ja を持たせる.

**関連**: §A-03 / 計画 §4 Week 1

---

### [ ] FU-308: parser dataclass → Pydantic Segment 統合 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py:135-165` (dataclass) と `tools/shared/src/juricode_shared/ir.py:61-85` (Pydantic) で同概念二重定義.

**問題**: IR を「正規」にしたい意図と矛盾. parser 出力が `extra="forbid"` Pydantic で validate されない → 型ドリフトが入り放題.

**やること**: parser dataclass を Pydantic `Segment` に置換、`Segment(...).model_dump(exclude_none=True)` で `to_dict` を完全置き換え.

**関連**: §B-01 §B-03 / 計画 §4 Week 2

---

### [ ] FU-309: ET element の None ガード統一 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/extract_kou_from_xml.py:89, 122` で `elem` 型注釈なし. None を受けると AttributeError.

**やること**: 型を `xml.etree.ElementTree.Element | None` と明示、冒頭 `if elem is None: return ""` を追加 (supplproviso 側と一貫化).

**関連**: §B-02 / 計画 §4 Week 2

---

### [x] FU-310: modality 優先順位 Why コメント追加 (2026-05-24 追加) — ✅ 完了 2026-05-31 (commit 695e6a11, main 4582a6ed)

**場所**: `tools/parse/v0.2/segment_parser.py:48-79`. `MODALITY_PATTERNS` の優先順位コメントが「より specific を先に」のみで根拠なし.

**問題**: 法令言語ルールの根幹なのに Why が `business/japanese-law-rag-design-blueprint-2026-05-22.md` まで飛ばないと分からない. AI 修正で順序を崩しても気付けない.

**やること**: 各 modality 行に「例: 〜の限りでない (刑法第N条) — 但書は最初に検出すべき (本文 modality を上書きするため)」等の 1 行根拠コメント.

**関連**: §C-01 §C-02 / 計画 §4 Week 3

---

### [ ] FU-311: `MAX_TEXT_LEN` を shared 定数化 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/extract_supplproviso_from_xml.py:433` `MAX_TEXT_LEN = 6000`. Gemini model 切替時の紐付けが弱い.

**やること**: `tools/shared/src/juricode_shared/embedding_limits.py` に `GEMINI_EMBEDDING_001_MAX_CHARS = 6000  # 8192 token を日本語 1.35 token/char で逆算、20% 安全マージン` として移し、各 parser から import.

**関連**: §C-03 / 計画 §4 Week 3

---

### [ ] FU-312: v0.2 parser まとめ系修正 (2026-05-24 追加)

**場所**: 複数箇所をまとめて 1 PR で対応:

1. `segment_parser.py:370-377` `parse_v01_md` の off-by-one ガード追加 + `parsing_warnings` 戻り値 (§C-06)
2. `extract_kou_from_xml.py:294-315` `chunk_file.open()` 3 回を 1 回 open に削減 (§D-05)
3. `extract_*.py` の `except Exception` を具体例外に分割 (§D-06)
4. `examples/v0.2/keihou-article-36.md` の paragraph 見出し統一 (§D-07)
5. `extract_*.py` の `ET.parse(xml_path)` への law_id path traversal 防御 (§D-08)

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §C-06 §D-05〜D-08 / 計画 §4 Week 4

---

### [ ] FU-405: PARAGRAPH_HEADING_RE / 漢数字変換を shared 化 (2026-05-24 追加)

**場所**: `tools/parse/verify.py:38-46`, `tools/export/lawsy-bq/export-jsonl.py:119-123` 等で同種 regex が複数ファイル別実装、枝番条対応有無で乖離.

**やること**: `tools/shared/src/juricode_shared/markdown_regex.py` に `PARAGRAPH_HEADING_PATTERN`, `kansuji_to_int` を共通化、全ファイルから import. FU-301 完了後に着手.

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §D-05 / 計画 §4 Week 3

---

### [x] FU-406: retrieve.py main を RetrievalPipeline クラスに分解 (2026-05-24 追加) — ✅ 完了 2026-05-31 (柱1-A, commit 6a5d39c2, main c8399333)

**場所**: `tools/embed/retrieve.py:577-787` (main 211 行で 4 つの責務同居).

**やること**: `RetrievalPipeline` クラスに `dense_retrieve / hybrid_combine / dedup_by_article / rerank / aggregate_metrics` を分割. main は CLI parsing + pipeline 実行のみ (50 行以下).

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §A-01 / 計画 §4 Week 1

---

### [x] FU-407: `dedup_by_article` の unit test 追加 (2026-05-24 追加) — ✅ 完了 2026-05-31 (柱1-A, test_retrieve.py 17 tests, commit 6a5d39c2, main c8399333)

**場所**: `tools/embed/retrieve.py:542-574`. 既知事故 (f) の修正は入っているが test 0 件.

**やること**: `tools/embed/tests/test_retrieve.py` を新設、`article_ids = ["A", "A", "B", "C", "C", "D"]` 等の fixture で純関数 unit test.

**関連**: §7 (事故 f 残存リスク) / 計画 §4 Week 1

---

### [ ] FU-408: `parse_egov_xml` 戻り値を dataclass 化 (2026-05-24 追加)

**場所**: `tools/parse/parse-egov.py:110-164`. `dict` (Any) を返し下流が `article["paragraphs"]` 等にキーアクセス.

**やること**: `@dataclass` で `ParsedLaw / ParsedArticle / ParsedParagraph` を定義. Pydantic IR と二重化を避けるため `tools/shared` に置く判断もあり.

**関連**: §B-01 / 計画 §4 Week 2

---

### [ ] FU-409: embed.py state を Union 型化 (2026-05-24 追加)

**場所**: `tools/embed/embed.py:71, 132, 222` の `state: dict` が provider 別 schema を持つが型不明.

**やること**: `TfidfState / OpenAIState / GeminiState` の `@dataclass`、`Union` で型付け. pickle の schema バージョンも frontmatter に記録.

**関連**: §B-02 / 計画 §4 Week 2

---

### [ ] FU-410: parse-egov.py `warnings.warn` → `logger.warning` (2026-05-24 追加)

**場所**: `tools/parse/parse-egov.py:231-236, 239-242`. bulk-ingest 経由で stderr が膨大化、本物のエラーが埋もれる.

**やること**: `logger.warning` に置換 + `--strict-paragraphs` flag で error 化を選択可能に.

**関連**: §D-08 / 計画 §4 Week 3

---

### [ ] FU-411: Gemini `except Exception` 分割 (2026-05-24 追加)

**場所**: `tools/finetune/generate-training-data.py:68, 89, 224`. retry すべき例外と即 fail すべき例外を区別していない.

**やること**: `RateLimitError / InvalidArgumentError / RetryableError` 等を handler 別に分ける.

**関連**: §D-06 / 計画 §4 Week 3

---

### [ ] FU-412: BM25 index pickle キャッシュ (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:670-677`. `--hybrid-bm25` 時に毎回 full rebuild、17,967 segments で数十秒〜分.

**やること**: `.bm25.pkl` でキャッシュ、mtime 比較で再構築判定.

**関連**: §D-07 / 計画 §4 Week 4

---

### [ ] FU-413: `_extract_law_name` を defusedxml ElementTree.find に (2026-05-24 追加)

**場所**: `tools/fetch-egov/src/fetch_egov/client.py:239-245`. 文字列 find で `<LawTitle>` を抜くため、属性付きや empty タグで破綻.

**やること**: `defusedxml.ElementTree.fromstring(xml).find(".//LawTitle")` 化.

**関連**: §D-09 / 計画 §4 Week 3

---

### [x] FU-414: search-ui に `--allow-external` flag (2026-05-24 追加) — ✅ 完了 2026-05-30 (柱5 Phase E、commit 3ce19b2c。_check_host で loopback 以外は --allow-external 必須 + fail-fast + WARNING)

**場所**: `tools/search-ui/server.py:1-30`. CORS / auth なし、`--host 0.0.0.0` で誤公開リスク.

**やること**: `--host` を 127.0.0.1 で hard pin、`--allow-external` 明示同意時のみ 0.0.0.0 許可 + warning ログ.

**関連**: §D-10 / 計画 §4 Week 3

---

### [x] FU-415: phase tag sweep script (FU-401 完了後) (2026-05-24 追加) — ✅ 完了 2026-05-26 (Cowork セッション、commit hash は push 後追記)

`tools/scripts/fix-phase-tags.py` (driver) + `juricode_shared/phase_tag.py` (純関数) + 37 unit tests を新設. v0.2 corpus 11,758 ファイル中 7,468 ファイル (64%) の `tags[0]` を path-derived phase に書き換え完了.

検証:
- `verify.py --path data/v0.2`: **11,758 / 0 fail** across 43 manifests (manifest hash 完全に不変、計画書 §1.5 の主張が実証)
- `pytest tools/shared/tests/`: 92 件 PASS (既存 55 + 新規 phase_tag 37)
- `ruff check`: All checks passed
- NUL byte sanity: 0 files
- 全 8 phase で 100% in-spec を確認 (tags[0] = path-derived)

書き換え内訳 (phase / law / 件数):
- phase1-administrative: chihou-koumuin-hou 106 / digital-shakai-keisei-kihon-hou 40 / jouhou-koukai-hou 27 / kojin-jouhou-hogo-hou 185 / kokka-koumuin-hou 184 / koubunsho-kanri-hou 34 = 576
- phase1-foundational: kenpou 103
- phase1-practitioner: shakuchi-shakka-hou 61
- phase1-tax: chihou-zei-hou 1,313 / souzoku-zei-hou 109 = 1,422
- phase2-commercial: 11 法令 = 4,017
- phase3-labor: roudou-kijun-hou 122
- phase3-pharma: yakkihou 356 / yakkihou-shikoukisoku 811 = 1,167
- **total: 7,468 files written**

副次効果 (本 sweep で初めて正常化された下流):
- `tools/embed/build-v0.2-corpus.py` → `phase_category` フィールドが path-derived な値に揃う (要 corpus 再構築 5-15 分)
- `tools/finetune/generate-training-data.py --phases <X>` 絞り込みが意味を持つ (sweep 前は phase2-commercial 指定で 0 件返り)
- `tools/search-ui/` UI の phase pill 表示が正しくなる
- `tools/export/lawsy-bq/export-jsonl.py` BigQuery export の phase_category が正しくなる (FU-P0-3 lawsy-bq exporter 着手時に活きる)

詳細設計: `business/fu-415-phase-tag-sweep-plan-2026-05-26.md` (v3、設計レビュー 4 ラウンド経由). コミット粒度 3 分割 (shared module + driver + data sweep), 詳細は本ファイル末尾「完了済み」セクション 2026-05-26 参照.

---

## P2 — Phase 1 中期 (2026-07〜09)

### [x] FU-506: heavy import script の Lazy Import 化 (2026-05-27 追加) — ✅ 完了 2026-05-28 (commits 425dde03 / 45743df5)

**場所**: `tools/finetune/train-reranker.py`, `tools/finetune/generate-training-data.py`, `tools/embed/convert-lawqa-to-evalset.py`, `tools/embed/run-ablation.py`, `tools/embed/embed.py` 等の `torch` / `sentence-transformers` / `google-generativeai` 依存 scripts.

**現状**: top-level import のため `--help` 実行時にも重い依存 package を import する. CI smoke test の依存環境が揃っていれば問題ないが、clean install 環境では `ModuleNotFoundError` で `--help` が失敗する.

**やること**: `if TYPE_CHECKING:` / 関数スコープ内 import / `importlib.import_module()` 等の Lazy Import 化で `--help` 時の依存最小化.

**前提**: FU-505 完了 (em dash 置換 + smoke test 確立) 後に着手.

**由来**: 2026-05-27 外部レビューで Lazy Import 化提案あり. FU-505 scope creep 回避のため別 FU 分離 (`business/fu-505-investigation-2026-05-27.md` §14 参照).

**関連**: FU-505 (完了), `business/planning-checklist.md` §1 (依存 call graph 追跡必要)

---

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

### [x] FU-108: parse-egov.py 全件 round-trip 検証 + 自治体法令の条数妥当性 (2026-05-20 追加) — ✅ 完了 2026-05-25 (v0.2 sprint)

`tools/parse/v0.2/manifest/` パッケージ新設 + 全 43 法令で `_source-manifest.json` 生成 (data/v0.2/) + `tools/parse/verify.py --path data` を CI に組込み済。**全 11,758 条 (8 phase / 43 manifests) で round-trip 検証 PASS**。

加えて v0.1 corpus (data/phase1-*/ ほか 8 phase) を `archive/v0.1/` に deprecate 完了 (data-quality-finding-2026-05-22 発見 1 (has_proviso/has_items false) と発見 2 (各号 content 欠落) の根本解決)。

詳細は本ファイル末尾「完了済み」セクション 2026-05-25 参照。コミットハッシュは push 後 (Phase 6) に追記。

残課題 (本 FU から独立した別タスクとして follow):
- 行政手続法 88 vs 48 の条数差分原因調査 (Cowork セッション中 v0.2 corpus で 48 条のまま、書誌的根拠未確定) → 別 follow-up に分離
- 附則・経過措置・別表の corpus 取込 (parse-egov.py で削除条文は skip 中、FU-101 ARTICLE_ID_PATTERN 附則対応と連動) → 別 follow-up に分離

---

### [ ] FU-313: `process_file` の parse / write / stats 分離 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py:521-567`. parse → write 2 ファイル → 統計集計を 1 関数で実施、dry_run / test が書きづらい.

**やること**: `parse_file()` (純粋関数、結果 dataclass 返却) と `write_outputs()` を分離.

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §A-04

---

### [ ] FU-314: rollup 生成経路の統合 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/extract_supplproviso_from_xml.py:608-635` の inline rollup と `add_rollup_chunks.py` が別経路で rollup 生成.

**やること**: `add_rollup_chunks.py` で `supplproviso_rollup` も統一処理. 当面は README に「rollup 生成は 2 箇所」を明記.

**関連**: §A-05

---

### [ ] FU-315: `Any` / `dict` 戻り値の TypedDict 化 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py:150, 178`, `add_rollup_chunks.py:41`, `extract_kou_from_xml.py:104`, `extract_supplproviso_from_xml.py:436`. `dict` / `list[dict]` がジェネリック未指定.

**やること**: `ChunkDict / SegmentDict / SupplProvisoChunk` を `TypedDict` で定義、もしくは Pydantic `Chunk` model 化.

**関連**: §B-01 §B-05

---

### [ ] FU-316: `kansuji_to_int` 統一 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py:111-127` (失敗時 0 返却) と `extract_supplproviso_from_xml.py:104-139` (失敗時 None 返却) で挙動差.

**やること**: `tools/shared/src/juricode_shared/kansuji.py` に統一、戻り値を `int | None` に揃え、call site で `or 0` フォールバック.

**関連**: §B-06

---

### [ ] FU-317: BOM / Windows path 対応 (2026-05-24 追加)

**場所**: `tools/shared/src/juricode_shared/frontmatter.py:24` で BOM 付き UTF-8 即 ValueError. `paths.py:23-27` docstring が PosixPath.

**やること**: `text.lstrip("\ufeff")` を冒頭で 1 行追加. paths.py docstring を Path() に.

**関連**: §D-09 §D-10

---

### [ ] FU-318: rollup chunk の retrieval filter 設計 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/add_rollup_chunks.py:79-89`. rollup chunk が `paragraph_number: None` のため、retrieval 側の filter が常に除外/常に含むの二択になる.

**やること**: `is_rollup: True` flag を追加、または `segment_type == "rollup"` を retrieve 側標準 filter に.

**関連**: §D-11

---

### [ ] FU-416: parse-egov.py `article_to_markdown` を IR 経由化 (2026-05-24 追加)

**場所**: `tools/parse/parse-egov.py:272-345`. IR 生成と frontmatter YAML 出力が同関数内.

**やること**: `article_to_ir(article, ...) -> JuriCodeArticle` と `ir_to_markdown(ir) -> (filename, text)` の 2 関数に分割.

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §A-02

---

### [ ] FU-417: bulk-ingest.py を EGovClient + FileCache 利用化 (2026-05-24 追加)

**場所**: `tools/fetch-egov/bulk-ingest.py:115-212`. urllib 直叩きで `EGovClient` を使っていない (両者の挙動 drift).

**やること**: `EGovClient` + `FileCache` を直接利用、urllib コードパスを削除.

**関連**: §A-03

---

### [ ] FU-418: search-ui の検索ロジックを retrieve.py から import (2026-05-24 追加)

**場所**: `tools/search-ui/server.py:45-200`. cosine top-k を retrieve.py と 2 箇所で実装.

**やること**: `retrieve.py` の `_cosine_topk` + `_encode_queries` を共有モジュール化、search-ui はそれを import.

**関連**: §A-04

---

### [ ] FU-419: generate-training-data.py を TrainingDataGenerator に分割 (2026-05-24 追加)

**場所**: `tools/finetune/generate-training-data.py:145-293`. main 内で corpus 読み込み〜Gemini 呼び出しまで直列.

**やること**: `TrainingDataGenerator` クラスに責務分割、CLI から library API を露出.

**関連**: §A-05

---

### [ ] FU-420: retrieve.py / generate-training-data.py の型注釈追加 (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:453-518` (`_encode_queries` 型注釈なし)、`tools/finetune/generate-training-data.py` 全般.

**やること**: `-> np.ndarray` 明示 + shape を docstring に. corpus は `TypedDict` で.

**関連**: §B-03 §B-05

---

### [ ] FU-421: bulk-ingest.py `summary` を IngestionResult dataclass 化 (2026-05-24 追加)

**場所**: `tools/fetch-egov/bulk-ingest.py:268`. `list[tuple[str, str, int, str]]` で 4-tuple ハード.

**やること**: `IngestionResult` dataclass.

**関連**: §B-04

---

### [ ] FU-422: bulk-ingest.py PHASE_MAP の各 phase 定義を docstring 化 (2026-05-24 追加)

**場所**: `tools/fetch-egov/bulk-ingest.py:46-104`. 1 行コメントのみで分類根拠が断片的.

**やること**: 各 phase の定義 (例: `phase3-pharma = 薬機法系の規制業種法令`) をモジュール冒頭 docstring に.

**関連**: §C-03

---

### [x] FU-423: train-reranker.py docstring の `/home/masa/...` を HF model ID に (2026-05-24 追加) — ✅ 完了 2026-05-31 (柱1-C, commit a619bb64)

**場所**: `tools/finetune/train-reranker.py:10`. 環境固有パスを example に残すと AI が hard-code する.

**やること**: HF model ID (例: `hotchpotch/japanese-reranker-cross-encoder-small-v1`) に置換、local path は optional override 扱い.

**関連**: §C-05

---

### [x] FU-424: train-reranker.py で fit 終了後に metrics サマリ出力 (2026-05-24 追加) — ✅ 完了 2026-05-31 (柱1-C, commit a619bb64)

**場所**: `tools/finetune/train-reranker.py:131`. 成功時 save パスのみ表示、metrics サマリなし.

**やること**: `evaluator` の最終スコア (`fit` 戻り値) を必ず print.

**関連**: §D-11

---

### [x] FU-425: retrieve.py hybrid + rerank 連動修正 (2026-05-24 追加) — ✅ 完了 2026-05-31 (柱1-B, commit 6a5d39c2, main c8399333 — ただし ablation で真因は hybrid 品質劣化と判明、FU-512 参照)

**場所**: `tools/embed/retrieve.py:707-716`. `--hybrid-bm25 --reranker` 併用時、rerank が dense top-N しか見ず hybrid の RRF 結果が捨てられる.

**やること**: rerank も `top_idx_wide` (hybrid 後) を candidate にする option を追加.

**関連**: §D-14

---

### [x] FU-501: build-v0.2-corpus.py の stale 経路 + 重複 print + chunk 件数差認識訂正 (2026-05-26 追加) — ✅ 完了 2026-05-26 (Cowork セッション、commit hash は push 後追記)

**場所**: `tools/embed/build-v0.2-corpus.py`.

`tools/embed/build-v0.2-corpus.py` の `--data-dir` デフォルトを `Path("data/v0.2")` に更新 (line 234) + 関連 docstring/コメント (line 31, 50) を v0.2 に揃える + 重複 print bug 削除 (旧 line 307-308). 計画書: `business/fu-501-build-v02-corpus-fix-plan-2026-05-26.md`.

**Issue 3 (42 件差) は認識訂正**: 「`build/chunks/` 配下に corpus 外の古いファイル混入の可能性」と書いていたが、call graph を実コードで追跡した結果 (planning-checklist §1 適用)、**42 件差の正体は v0.2 設計通りの `{law}-supplproviso.chunks.jsonl` × 42** (43 法令 − kenpou 1 = 42) と判明. backup filter (line 257) は適切に機能しており、コード修正不要. follow-ups.md の認識訂正のみ.

**検証コマンド** (Cowork sandbox):
```bash
for d in build/chunks/*/; do
  name=$(basename "$d")
  [ "$name" = "build-chunks-backup" ] && continue
  chunks=$(find "$d" -type f -name "*.chunks.jsonl" | wc -l)
  articles=$(find "data/v0.2" -type d -name "$name" -exec find {} -name "*-article-*.md" \; | wc -l)
  diff=$((chunks - articles))
  [ "$diff" != "0" ] && echo "$name: chunks=$chunks articles=$articles diff=$diff"
done | wc -l   # → 42 法令 (kenpou 以外) で +1
```

詳細は本ファイル末尾「完了済み」セクション 2026-05-26 参照.

**関連**: FU-108 (data/v0.2 移行、本 Issue 1 の遺漏元), FU-415 (sweep 後の確認で顕在化), FU-503 (CI 組込み の前提条件として依然有効), `business/planning-checklist.md` §1 (call graph 追跡の適用事例)

---

### [x] FU-502: fix-phase-tags.py --check-only を CI に追加 (2026-05-26 追加) — ✅ 完了 2026-05-26 (Cowork セッション、commit hash は push 後追記)

**場所**: `.github/workflows/ci.yml`.

`.github/workflows/ci.yml` の `Verify source-manifest hashes` step 直後に `Phase tag consistency check (FU-415 guard, FU-502)` step を追加. `python tools/scripts/fix-phase-tags.py --path data/v0.2 --check-only` を実行し、tags[0] が path-derived な phase と一致しない `.md` ファイルが 1 件でもあれば CI fail.

**前提条件として FU-504 を同 PR で同時に修復** (entry point 欠落 bug). 詳細は本ファイル末尾「完了済み」セクション 2026-05-26 参照.

**関連**: FU-415 (sweep), FU-504 (本 sprint で同時修復された fix-phase-tags.py entry point 欠落 bug), `business/fu-502-investigation-2026-05-26.md` (調査+実装計画書), `business/planning-checklist.md` §1 (false-green guarantee の未然回避事例)

---

### [x] FU-504: fix-phase-tags.py に `__main__` entry point 追加 (2026-05-26 追加) — ✅ 完了 2026-05-26 (Cowork セッション、commit hash は push 後追記)

**場所**: `tools/scripts/fix-phase-tags.py`.

`tools/scripts/fix-phase-tags.py` (FU-415, commit `ea8c6752` で導入) は `if __name__ == "__main__": sys.exit(main())` ブロックを欠いていたため、`python <script>` 経由で実行しても `main()` が呼ばれず silently exit 0 する false guarantee 状態だった. FU-502 (CI ガード) を計画通り追加すると常に PASS を返す step になることが planning-checklist §1 (call graph 追跡) を実コードで適用した結果判明 (2026-05-26 夕方、Cowork セッション中).

**修正**:
- entry point 末尾に `if __name__ == "__main__": sys.exit(main())` 3 行追加
- `main()` の戻り値整備 (apply エラー時 `return 1`、正常完了時 `return 0` を明示)
- subprocess based smoke test `tools/shared/tests/test_fix_phase_tags_cli.py` を新設 (3 件: `--check-only` / `--dry-run` / `--help`) で実 CLI 起動を CI で常時担保

**Why entry point 欠落の発生原因**:
FU-415 sprint で `fix-phase-tags.py` を Cowork sandbox で開発した際の Write/Edit 末尾切断事故 (CLAUDE.md §10.2 既出) が `__main__` ブロックを丸ごと削除したまま commit された. 「Write tool の末尾切断 → bash + Python 経由 atomic write で完全に書き直し」と FU-415 完了 entry に記載されているが、**復旧が不完全だった** ことが判明. unit test は pure functions (`juricode_shared.phase_tag`) のみカバーし、driver の CLI 起動を test していなかったため約 1 ヶ月 silently false-green 状態で潜伏.

**Why FU-415 sweep は 7,468 files 書き換えに成功したのか**:
未解明だが、Cowork セッション中は `__main__` block が存在した(commit 前の Write/Edit 事故で消えた)、または別経路 (`python -c "from importlib.util import ...; mod.main()"`) で main() を直接呼んだ、のどちらか.

**関連**: FU-415 (entry point 欠落の起点), FU-502 (本 fix の動機 = CI ガードの実効性担保), `business/fu-502-investigation-2026-05-26.md` (調査+実装計画書 §1, §5 Phase A/B), `feedback_cli_entry_point_verification` memory (新規追加候補)

---

### [x] FU-503: build-v0.2-corpus.py --validate-only mode + CI 統合 (2026-05-26 追加) — ✅ 完了 2026-05-26 (Cowork セッション、commit hash は push 後追記)

**場所**: `tools/embed/build-v0.2-corpus.py` + `tools/shared/tests/test_build_v02_corpus_cli.py` + `.github/workflows/ci.yml` + `pyproject.toml`.

`build-v0.2-corpus.py` に `--validate-only` mode を追加 (Option α: mapping-only validation). `data/v0.2/` から 43 laws / 8 phases / 9825 captions が抽出できることを CI で機械的に検知. `build/chunks/` は `.gitignore` 対象で CI 不在のため、chunk merge は走らせず mapping check のみに scope を絞る.

外部レビュー指摘により **3 層防御** を導入:
- **Layer 1 (構造)**: `pyproject.toml` の ruff `[tool.ruff.lint] select` に `"RET"` (flake8-return) を追加. RET503 が `main()` の implicit None 戻りを静的検査で検知し、FU-502/504 と同型の false-green guarantee を構造的に防止.
- **Layer 2 (runtime)**: `tools/shared/tests/test_build_v02_corpus_cli.py` に 5 件の subprocess based smoke test を新設. 特に **既存 merge mode の exit 0 を初めて runtime verify** (`test_merge_mode_exits_zero_with_minimal_fixture`).
- **Layer 3 (code review)**: `main()` の全 code path で `return 0`/`return 1` を「意地悪なほど明示的に」書く checklist を Phase A 実装に組み込み.

詳細は本ファイル末尾「完了済み」セクション 2026-05-26 参照.

**関連**: FU-415 (sweep), FU-501 (build-v0.2-corpus.py の `--data-dir` default 修正), FU-502 (CI guard pattern), FU-504 (entry point 修復), `business/fu-503-investigation-2026-05-26.md` (調査+実装計画書 v3, 3 層防御確定), `business/planning-checklist.md` §1 §2 §4 (適用済)

---

### [x] FU-505: project-wide em dash ASCII 置換 + cp932 CI guard (2026-05-27 完了)

**場所**: `tools/` 配下の 15 個の CLI script (`embed/convert-lawqa-to-evalset.py`, `embed/run-ablation.py`, `validate/validate-all.py`, `parse/parse-egov.py`, `parse/verify.py`, `parse/v0.2/add_rollup_chunks.py`, `parse/v0.2/extract_kou_from_xml.py`, `parse/v0.2/extract_supplproviso_from_xml.py`, `parse/v0.2/segment_parser.py`, `parse/v0.2/manifest/cli.py`, `finetune/generate-training-data.py`, `finetune/train-reranker.py`, `fetch-egov/bulk-ingest.py`, `search-ui/server.py`) の docstring 1 行目.

**現状**: FU-502 で `fix-phase-tags.py`、FU-503 で `build-v0.2-corpus.py` の 2 scripts は em dash → `--` 置換済. 残り 15 scripts は project-wide convention として em dash を含んだままで、**Windows cp932 console で `python <script> --help` を実行すると `UnicodeEncodeError` で crash する**.

**問題**: 新規 CLI smoke test (特に `test_help_runs_without_crash` 系) を追加するたびに同じ事故が発生する構造的 bug. FU-502/503 で 24 時間以内に 2 度同じ事故を踏んだ. 個別の smoke test 追加時に都度修復するより、project-wide 一括置換で構造的にゼロ化する方が長期的に効率的.

**やること**:
1. `sed -i 's/— /-- /g'` 相当を全 15 scripts の docstring 1 行目に適用 (line 1 のみ、本文の em dash は touch しない)
2. ruff check + format で構造を verify
3. 各 script の `--help` を一通り実行して exit 0 確認 (もしくは検出 script で project-wide pre-check)
4. CI で全 step が通ることを確認

**実行時間**: 15 file の 1 char 置換 + verify、約 30 分.

**前提**: NLnet 5/28 提出後の sprint で着手 (今は FU-503 の完走優先).

**関連**: FU-502 (fix-phase-tags.py 個別修復), FU-503 (build-v0.2-corpus.py 個別修復), `business/planning-checklist.md` §5 (新規 CLI smoke test の precondition), memory `feedback_windows_cp932_em_dash` (FU-502/503 で 2 度踏んだ事故の教訓)

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

**現状**: Pydantic IR は「1 条」単位での構造化に閉じていて, 条文間の参照を機械可読に表現する仕組みがない.

**問題**: Phase 1 (4 法令 ~75 条) では影響小. ただし Phase 2 (民法・商法) で他法律への参照が爆発的に増えると, RAG 用途で「関連条文を辿る」探索クエリが弱くなる. 後付け改修は IR 破壊変更で migration コスト大.

**やること** (Phase 2 着手前 or 必要が出たタイミング): `ArticleReference` モデルを `JuriCodeArticle.references` に追加. graph traversal を考慮するなら別途グラフ DB (Neo4j 等) への export 検討.

**関連**: [FU-201] (ParentSection 多言語化) と同じく Phase 2 着手時の大きな IR 進化検討.

---

### [ ] FU-207: CI / validate-all.py の差分検証・並列化 (2026-05-19 追加)

**現状**: CI ジョブ "Validate all law data files" は全ファイルを線形ループ. Phase 2 (~1,900 ファイル) / Phase 3 (数千ファイル) で PR ごとの CI 時間が膨らむ.

**やること** (Phase 2 着手前): `--changed-since GITREF` 等の差分モード追加. CI 上で `pull_request` イベントの場合は変更ファイルのみ検証. 並列化.

---

### [ ] FU-319: `SEGMENT_TYPE_ORDER` の Why コメント (2026-05-24 追加)

**場所**: `tools/parse/v0.2/add_rollup_chunks.py:28-38`. tie-breaker の根拠と並びの安定性が不明.

**やること**: 「同一 paragraph 内では honbun → tadashi / zen_dan → kou_dan / hashira → kou1 → kou2 の順を保証. honbun と zen_dan は同 paragraph 共存なしで 0 重複 OK」を明記.

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §C-04

---

### [ ] FU-320: `KOU_DAN_LEADER` anchor 意図明文化 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py:35`. anchor 混在の意図が不明.

**やること**: 意図ありなら「前段の場合において は段落先頭にしか現れない」をコメント、事故ならアンカー削除.

**関連**: §C-05

---

### [ ] FU-321: Penalty model parser 実装 (2026-05-24 追加)

**場所**: `tools/shared/src/juricode_shared/ir.py:43-58` で定義済だが parser で生成箇所なし.

**やること**: 刑罰検出を v0.3+ で実装. それまで IR に枠だけ残す.

**関連**: §D-12

---

### [ ] FU-426: `dedup_by_article` docstring に Why 追記 (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:542-574`. 「v0.1 比較用」のみで「top rank 保持」根拠なし.

**やること**: 「上位 rank の segment が最も relevance 高、後続は同 article 内の関係ない条文の可能性が高い」を docstring に.

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §C-02

---

### [ ] FU-427: retrieve.py rrf_combine の dense 側を candidate_pool で渡す (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:680-685`. dense top が wide_pool で絞られ低 rank dense + 高 rank bm25 が取り逃される.

**やること**: dense 側を `candidate_pool` (= top_k*10) で渡す.

**関連**: §D-12

---

### [ ] FU-428: generate-training-data.py resume の挙動 docstring 明文化 (2026-05-24 追加)

**場所**: `tools/finetune/generate-training-data.py:215-226`. resume 挙動と docstring の一致が曖昧.

**やること**: docstring で resume の単位 (positive_id 単位) を明示.

**関連**: §D-13

---

### [ ] FU-429: retrieve.py rerank candidate に top_idx_wide option (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:707-716`. FU-425 (P2) の P3 fallback 案、option として実装するパターン.

**やること**: `--rerank-candidates {dense,hybrid}` で選べる.

**関連**: §D-14

---

### [ ] FU-430: bulk-ingest.py subprocess の `--quiet` 化 (2026-05-24 追加)

**場所**: `tools/fetch-egov/bulk-ingest.py:185`. 民法 1,165 条等で stdout buffer 膨大化、OOM の可能性.

**やること**: parse-egov.py を `--quiet` 化、または log file redirect.

**関連**: §D-15

---

### [ ] FU-431: parse-egov.py 削除条文範囲を manifest 記録 (2026-05-24 追加)

**場所**: `tools/parse/parse-egov.py:212-218`. `<Article Num="73:76">` 範囲を None で flatten 削除し痕跡を失う.

**やること**: `deleted_articles` リストを `_source-manifest.json` に記録.

**関連**: §D-16

---

## 完了済み

完了した項目はここに timestamp 付きで移動する.

### 2026-05-28 — FU-506 完了: tools/ 配下 全 CLI scripts の top-level heavy import Lazy Import 化

> FU-505 で確立した smoke test + cp932 guard の後続 sprint. numpy / httpx 等 heavy deps の
> top-level import を Lazy Import 化 (TYPE_CHECKING + 関数内 local import) し、minimal install
> 環境 (CI / Windows ユーザ) での `--help` crash を根本解決.

- ✅ **FU-506 hotfix (425dde03)**: FU-505 post-merge で CI #56 fail. 根本原因は 3 scripts の top-level heavy import.
  - `server.py`: `import numpy as np` -> TYPE_CHECKING + 4 関数 local import
  - `generate-training-data.py`: 同上 -> 2 関数 local import
  - `fetch_egov/__init__.py`: top-level re-export 完全削除 (利用側は submodule から直接 import)
- ✅ **FU-506 本体 (45743df5)**: 残対象 4 scripts 完遂.
  - `embed.py`: `import numpy as np` -> 4 関数 local import
  - `retrieve.py`: 同上 -> 10 関数 local import
  - `client.py`: `import httpx` -> TYPE_CHECKING + `__init__` local import
  - `cli.py`: `from fetch_egov.client import EGovClient` -> `get_law` 関数内 local import

**検証**: ruff check / format clean, pytest 214 PASS, cp932-safe 42 files.
**計画書**: `business/fu-506-investigation-2026-05-28.md` (v2、外部レビュー 3 件反映済)

---

### 2026-05-27 — FU-505 完了: project-wide em dash ASCII 置換 + cp932 CI guard + smoke test

> FU-502/503 で 2 度踏んだ Windows cp932 `--help` crash を project-wide に構造的ゼロ化した sprint.
> 17 scripts の em dash/arrow を ASCII 化 + `check-cp932-safe.py` 新設 (CI step 12 追加) + parametrize smoke test 13 件 PASS.
> planning-checklist §5 (新規 CLI smoke test の precondition) を本 sprint で解消し、構造的に再発不可能となった.

- ✅ **FU-505: project-wide em dash ASCII 置換 + cp932 CI guard** — 計画書 `business/fu-505-investigation-2026-05-27.md` v2 (Tier 1-4 = 17 scripts + Phase A-E 5 commits).
  - **Phase A (機械的置換)**: Tier 1+2+3+4 = 17 scripts + 追加発見の module-only ファイル (`phase_tag.py`, `frontmatter.py`, `law_id_map.py`, `canonical_hash.py`, `law_manifest.py`, `article_entry.py`, `__init__.py`, `cli.py` 等) の em dash (U+2014) / arrow (U+2192) / approx (U+2248) / check mark (U+2705) / bidirectional arrow (U+2194) / BOM (U+FEFF) を全件 ASCII 化. `tools/` 配下 42 files cp932-safe.
  - **Phase B (detection script)**: `tools/scripts/check-cp932-safe.py` 新設. `--path tools` で 42 files scan、tests/ / __pycache__ / .venv 等は除外. exit 0 で `=== cp932-safe: N files scanned ===`. 自己 smoke test 3 件 PASS.
  - **Phase C (parametrize smoke test)**: `tools/shared/tests/test_cli_help_smoke.py` 新設. manifest/cli.py (相対 import 制約で直接実行不可) を除く 13 scripts の `--help` を `PYTHONIOENCODING=cp932` + `PYTHONPATH` 設定で runtime verify. 13 tests PASS.
  - **Phase D (CI 統合)**: `.github/workflows/ci.yml` に `Check cp932-safe (FU-505)` step 追加. CI step 総数: 11 -> 12.
  - **Phase E (docs)**: follow-ups.md FU-505 完了化 + FU-506 (Lazy Import 化, P2) 新規登録.

**検証**:
- `python tools/scripts/check-cp932-safe.py --path tools`: `=== cp932-safe: 42 files scanned ===` (exit 0)
- `pytest tools/shared/tests/test_check_cp932_safe.py -v`: 3 passed
- `pytest tools/shared/tests/test_cli_help_smoke.py -v`: 13 passed

---

### 2026-05-26 (夕方 v3) — FU-503 完了: build-v0.2-corpus.py --validate-only + CI 統合 + 3 層防御

> v0.2 corpus 品質改善ラインの本体最終 sprint. レビュアー指摘により 3 層防御を導入し、main() return 忘れによる false-green guarantee を構造的にゼロ化.
> Option α (mapping-only validation) で scope を最小化しつつ、レビュー指摘の Layer 2 (merge mode runtime test) は維持. **計画 v3 通り 5 commits / +約 250 行で完走**.

- ✅ **FU-503: --validate-only mode + CI 統合 + 3 層防御** — 計画書 `business/fu-503-investigation-2026-05-26.md` v3 (Option α + 3 層防御 + smoke test 5 件確定).
  - **Phase A1 (Layer 1 構造防御)**: `pyproject.toml` の `[tool.ruff.lint] select` に `"RET"` (flake8-return) を追加. RET503 が `main()` の implicit None 戻りを lint 段階で検知し、FU-502/504 と同型の false-green を構造的にゼロ化. 既存 codebase に 0 violation 確認済 (migration cost なし).
  - **Phase A2 (--validate-only mode + return 整備)**: `tools/embed/build-v0.2-corpus.py` に以下を追加:
    - argparse に `--validate-only` flag 追加
    - 新規関数 `_run_validate_only(data_dir: Path) -> int` (43 laws / 8 phases / 9000+ captions / 0 dangling を assert、return 0 or 1)
    - 既存 merge mode 末尾に `return 0` を明示 (Layer 3「意地悪なほど明示的に」原則, `business/planning-checklist.md`)
    - `args.chunks_dir.exists() == False` の `sys.exit("ERROR: ...")` も `print(stderr) + return 1` に統一
  - **Phase B (Layer 2 runtime smoke test)**: `tools/shared/tests/test_build_v02_corpus_cli.py` を新設 (5 tests):
    - `test_validate_only_exits_zero_on_clean_corpus` (Core: happy path)
    - `test_validate_only_no_output_file` (副: 副作用なし)
    - `test_validate_only_exits_one_on_missing_data_dir` (Core: error path)
    - `test_help_runs_without_crash` (副: argparse sanity)
    - `test_merge_mode_exits_zero_with_minimal_fixture` (**Core レビュー指摘**: 既存 merge mode の exit 0 を初めて runtime verify、Layer 2 の核)
  - **Phase C (CI 統合)**: `.github/workflows/ci.yml` の `Phase tag consistency check (FU-502)` step の直後に新 step を追加. `python tools/embed/build-v0.2-corpus.py --validate-only` を実行し、mapping 不備 1 件でも exit 1 で CI fail. CI step 総数: 10 -> 11.
  - **Phase D (docs 訂正)**: 本 entry + footer v0.7.3 -> v0.7.4 bump.

**検証** (Cowork sandbox):
- `ast.parse` (build-v0.2-corpus.py): OK
- NUL byte count: 全 4 ファイルで 0
- `ruff check tools/` (RET 有効化後): All checks passed
- `ruff format --check`: all formatted
- `python tools/embed/build-v0.2-corpus.py --validate-only`:
  - `law -> phase mapping: 43 laws, 8 phases`
  - `caption mapping: 9825 captions`
  - `=== Validate OK ===`
  - exit code: 0
  - 実行時間: 13.6 秒 (想定 5 秒よりやや長いが許容範囲)
- `pytest tools/shared/tests/test_build_v02_corpus_cli.py -v`: **5 passed in 27.16s**
- `yaml.safe_load(ci.yml)`: 11 steps、`Validate v0.2 corpus phase mapping (FU-503)` 含む

**Cowork sandbox で踏んだ既知事故 (再発 + 復旧)**:
- `pyproject.toml` の Edit が中途切断 (TOML parse error) -> Python atomic write + tomllib verify で復旧
- `build-v0.2-corpus.py` の Edit 後 ruff format で 1 度整形が必要 -> ruff format で自動修復

**planning-checklist 適用事例**:
- §1 (call graph 追跡 Layer 4): main() return 忘れリスクを事前発見し、レビュー指摘で 3 層防御に拡張
- §2 (post-merge dry-run 自動化): Phase B smoke test 5 件で `--validate-only` / merge mode / error path / help を自動検証
- §4 (主張は控えめ): Option α (mapping-only) で scope を最小化し、「mapping 漏れ検知」と限定表現
- **新 learning**: 外部レビュー由来の「3 層防御」(static lint + runtime test + explicit code review) を memory `feedback_planning_call_graph_audit` に追記候補

**未然回避された潜在影響**:
- 計画 v1 (Layer 2/3 のみ): main() return 漏れがあっても CI が検知できず、運用後に下流で初めて顕在化 -> 訂正 PR + 周辺修正の手戻り
- 計画 v3 (3 層防御): Layer 1 RET503 が lint で即検知、Layer 2 smoke test が runtime で再確認、Layer 3 checklist で実装時の意識付け

**Phase 6 (git commit + push)**: Cowork sandbox の git lock 削除権限なしのため Windows/WSL 側で実行予定. コミット粒度 5 分割:
1. `chore(lint): enable RET503 (flake8-return) for false-green guard`
2. `feat(embed): add --validate-only mode + explicit return at all main paths (FU-503)`
3. `test(shared): add CLI smoke tests for build-v0.2-corpus.py (5 tests)`
4. `ci: add v0.2 corpus phase mapping validation (FU-503)`
5. `docs(follow-ups): mark FU-503 complete + record reviewer feedback`

詳細手順書: `business/fu-503-commit-runbook-2026-05-26.md` (本 sprint 完了時に作成).

ref:
- `business/fu-503-investigation-2026-05-26.md` (調査+実装計画書 v3)
- `business/planning-checklist.md` §1 §2 §4
- 起点: FU-502 完了直後の P2 最後の follow-up 着手

### 2026-05-26 (夕方 v2) — FU-502 + FU-504 完了: fix-phase-tags.py entry point 修復 + CI guard 追加

> FU-501 完了の延長で着手した FU-502 調査中に発覚した **fix-phase-tags.py entry point 欠落 bug** を同 PR で修復し、CI ガードを追加.
> planning-checklist §1 (call graph 追跡) を Layer 4 まで適用したことで、計画通り FU-502 を ship していたら false-green guarantee になっていた状況を **未然回避** できた 2 つ目の事例 (FU-501 Issue 3 に続く).

- ✅ **FU-504: fix-phase-tags.py に `__main__` entry point 追加** — 計画書 `business/fu-502-investigation-2026-05-26.md` §5 Phase A.
  - `tools/scripts/fix-phase-tags.py` 末尾に `if __name__ == "__main__": sys.exit(main())` 3 行追加 + `main()` 戻り値整備 (apply エラー時 `return 1` / 正常時 `return 0`).
  - **Why 必要だった**: FU-415 (2026-05-26 朝、commit `ea8c6752`) で当 script を新設した際、Cowork sandbox の Write/Edit 末尾切断事故で entry point block が丸ごと削除されたまま commit. unit test は pure functions のみカバーし、driver の CLI 起動を test していなかったため、約 1 ヶ月 silently false-green 状態で潜伏 (`python <script> --check-only` 実行で 0.2 秒で exit 0、何も走らない).
  - **発見契機**: FU-502 計画書を書く前に planning-checklist §1 (call graph 追跡) を実コードで Layer 4 まで verify (CI step → script invocation → main 呼出有無 → exit code 評価) した結果、「CI guard が常に PASS を返す」と判明.

- ✅ **FU-502: fix-phase-tags.py --check-only を CI に追加** — 計画書 §5 Phase C.
  - `.github/workflows/ci.yml` の `Verify source-manifest hashes` step 直後に `Phase tag consistency check (FU-415 guard, FU-502)` step を追加.
  - 実行コマンド: `python tools/scripts/fix-phase-tags.py --path data/v0.2 --check-only` (`--data-root` は default が `Path("data/v0.2")` のため省略).
  - mismatch 1 件でも `exit 1` で CI fail. tags[0] 退行 (将来 contributor の手動編集 / 新 ingest tool の遺漏) を機械的に検知.

- ✅ **smoke test 新設** (FU-504 と同 sprint、計画書 §5 Phase B):
  - `tools/shared/tests/test_fix_phase_tags_cli.py` を新設 (3 件: `--check-only` / `--dry-run` / `--help`).
  - subprocess で実 CLI 起動 + exit code + stdout marker を assert. FU-504 entry point 欠落の再発を CI で即検知する仕組み.
  - `--check-only` test は 11,758 files 走査 (16-17 秒) + summary marker assert. `--dry-run` test は idempotent state メッセージ assert. `--help` test は最軽量で entry point sanity check.

**検証** (Cowork sandbox):
- `ast.parse` (fix-phase-tags.py): OK
- NUL byte count: 0 (途中 52 NUL padding 事故あり、atomic rewrite で復旧)
- `ruff check tools/scripts/fix-phase-tags.py`: All checks passed
- `ruff format --check`: already formatted (ruff format で smoke test ファイルを 1 度整形)
- `python3 -m pytest tools/shared/tests/test_fix_phase_tags_cli.py -v`: **3 passed in 33.22s**
- `python tools/scripts/fix-phase-tags.py --path data/v0.2 --check-only`:
  - Scanned: **11,758 files** (修正前: 0 files = 何も走らず)
  - Total in-spec: 11,758 / mismatches: 0 / errors: 0
  - exit code: 0
- `yaml.safe_load(ci.yml)`: 10 steps (修正前 9 + 新規 `Phase tag consistency check`)

**Cowork sandbox で踏んだ既知事故 (再発 + 復旧)**:
- Edit 後の fix-phase-tags.py に末尾 52 NUL byte padding 発生 → Python atomic write で復旧
- Edit/Write が ci.yml と docs/follow-ups.md でディスクに反映されない / トランケート事故が複数回発生 → Python 経由 atomic write で完全に書き直し
- これらは FU-501 で踏んだ事故と同パターン. FU-302 `safe_write_text` を将来 tools/embed/ / tools/scripts/ にも適用する余地あり (本 sprint scope 外)

**Phase 6 (git commit + push)**: Cowork sandbox の git lock 削除権限なしのため Windows/WSL 側で実行予定. コミット粒度 4 分割:
1. `fix(scripts): add __main__ entry point to fix-phase-tags.py (FU-504)`
2. `test(shared): add CLI smoke test for fix-phase-tags.py --check-only`
3. `ci: add phase tag consistency check (FU-502)`
4. `docs(follow-ups): mark FU-502/FU-504 complete + record FU-415 retrospective`

詳細手順書: `business/fu-502-commit-runbook-2026-05-26.md` (本 sprint 完了時に作成予定).

**planning-checklist 適用事例**:
- §1 (call graph 追跡): Layer 4 まで verify することで false-green を未然発見 → FU-504 として scope 内に取り込み → ship 前に修復.
- §2 (post-merge dry-run): Phase B smoke test を Phase A と同時に追加 → CI で自動化、手動 dry-run も Phase A 後に 1 回実行で完走確認.
- §4 (主張は控えめ): 「`tags[0]` 退行を検知する guard」と限定表現. 直接効果 / 副次効果 / 波及的価値を分離記述.

**未然回避された潜在影響**:
- FU-502 を計画通り ship → CI guard が常に PASS = false guarantee → tags[0] 退行が発生しても検知できない → 数週間後に下流 (lawsy-bq exporter 等) で初めて顕在化 → 訂正 PR + tag 修復 sweep の手戻り
- 推定回避コスト: 訂正 PR 1 本 + 周辺メモリ更新 + planning-checklist §1 への新事例追記の手戻り工数

ref:
- `business/fu-502-investigation-2026-05-26.md` (調査+実装計画書)
- `business/planning-checklist.md` §1 §2 §4 (適用済)
- 起点: FU-501 完了直後の P2 follow-up 着手

### 2026-05-26 (夕方) — FU-501 完了: build-v0.2-corpus.py 修正 + Issue 3 認識訂正

> FU-415 post-merge レビューで発覚した 3 件のうち FU-501 を 1 セッションで完走.
> **最大の価値は Issue 3 の認識訂正** — planning-checklist §1 (call graph 追跡) を実コードで適用した結果、「古いファイル混入の可能性」が overstatement だったと判明.

- ✅ **FU-501: build-v0.2-corpus.py 修正 + 認識訂正** — 計画書 `business/fu-501-build-v02-corpus-fix-plan-2026-05-26.md` (gitignored).
  - **Issue 1 (--data-dir default stale)**: `tools/embed/build-v0.2-corpus.py:234` の `default=Path("data")` を `default=Path("data/v0.2")` に修正. FU-108 (2026-05-25 完了) で corpus を `data/v0.2/phase*/` に移動した際の遺漏修復. `build_law_to_phase` 関連 docstring/コメント (line 31, 50) も `v0.1` → `v0.2` に揃え. 呼び出し元 0 件 (CI 未統合 / import 0 件 / README.md 引用なし) のため後方互換破壊リスクなし.
  - **Issue 2 (重複 print)**: `tools/embed/build-v0.2-corpus.py:307-308` の同一 `print(f"  {t:12s}: {c:6d}", file=sys.stderr)` 2 行連続を 1 行に統一. segment type distribution が 2 重出力されなくなった.
  - **Issue 3 (42 件差) — 認識訂正**: 「`build/chunks/` 配下に corpus 外の古いファイル混入の可能性」と書いていたが、call graph 検証 (`for d in build/chunks/*/; do ... done`) の結果、**42 件差の正体は v0.2 設計通りの `{law}-supplproviso.chunks.jsonl` × 42** と判明. 43 法令 − kenpou 1 = 42 で計算完全一致. supplproviso chunks は附則条文を含む正規データ (合計 23,463 chunks). backup filter (line 257) は適切に機能しており、**コード修正不要**.
  - **Phase 6 (git commit + push)**: Cowork sandbox の git lock 削除権限なしのため Windows/WSL 側で実行予定. コミット粒度 3 分割: `fix(embed): default --data-dir to data/v0.2` / `style(embed): remove duplicate segment-type print` / `docs(follow-ups): correct FU-501 Issue 3 misdiagnosis`. 採択後コミットハッシュをここに追記.

**Cowork sandbox で踏んだ既知事故 (再発 + 復旧)**:
- Edit 後の build-v0.2-corpus.py に末尾 48 NUL byte padding が発生 (Cowork sandbox 既知事故、CLAUDE.md §10.2 で既出). bash + Python 経由の atomic write (`.tmp` → `.replace`) + `ast.parse` 事前検証で完全に復旧. 同種事故を 4/24 / 5/25 / 5/26 と 3 度踏んでいるため、FU-302 `safe_write_text` を本ファイルにも将来適用する余地あり (本 sprint scope 外).

**検証** (Cowork sandbox):
- `python3 -c "import ast; ast.parse(open('tools/embed/build-v0.2-corpus.py').read())"`: OK
- NUL byte count: 0 (Python `data.count(b'\x00')`)
- `ruff check tools/embed/build-v0.2-corpus.py`: All checks passed
- `ruff format --check tools/embed/build-v0.2-corpus.py`: already formatted
- CLI smoke test (本 Phase 3): `python tools/embed/build-v0.2-corpus.py --output /tmp/fu501-smoke.jsonl` で `law -> phase mapping: 43 laws` + segment type distribution 単一出力 + 全 chunks に正しい phase_category を確認 (実行ログは本セッション末尾).

**planning-checklist 適用事例**:
- §1 (call graph 追跡): Issue 3 で claim「古いファイル混入」を実コードで verify → overstatement と判明 → 「コード修正不要、認識訂正のみ」にダウングレード. **FU-415 で踏んだ overstatement 失敗を本 sprint では未然回避できた最初の事例**.
- §2 (post-merge dry-run): Phase 3 smoke test で実装後の動作を planning 段階に走らせて期待出力を verify.
- §4 (主張は控えめ): 「下流が直る」とは書かず、「embed corpus 再構築の手動運用が壊れていた状態の修復 + FU-503 (CI ガード) の前提整備」と限定表現.

ref:
- `business/fu-501-build-v02-corpus-fix-plan-2026-05-26.md` (本 sprint 計画書)
- `business/planning-checklist.md` §1 §2 §4 (適用事例として参照)
- `business/fu-415-followup-fixes-plan-2026-05-26.md` §1.2 Problem A/A2/A3 (本 FU の起点)

### 2026-05-26 — FU-415 完了: phase tag sweep (7,468 files rewritten)

> 計画書設計 4 ラウンドレビュー (v0 → v3) を経て 1 セッションで完走.
> Cowork sandbox 既知事故 (Write 末尾切断 + NUL padding) を 2 件踏みつつ FU-302 safe_write_text の assert 機構で検知・復旧.

- ✅ **FU-415: phase tag sweep** — `tools/scripts/fix-phase-tags.py` (driver, 約 350 行) + `juricode_shared/phase_tag.py` (純関数 module 純関数 2 つ + 5 種 ValueError 分類タグ) + `tools/shared/tests/test_phase_tag.py` (37 unit tests) を新設.
  - **Phase 1 (純関数 + tests)**: `resolve_phase_from_path` / `rewrite_tags0_in_text` 2 つの純関数. frontmatter デリミタで text を 3 分割してから regex 適用する設計で body の `notes: \|` 巻き込み事故を構造的にゼロ化. BOM 検知時は `[BOM_DETECTED]` で停止 (FU-317 P2 とスコープ分離、option b). 37 tests PASS (基本動作 13 + frontmatter scope 3 + BOM 1 + CRLF round-trip 2 + safe_write 2 + PHASE_DIR_RE 16).
  - **Phase 2 (driver)**: `tools/scripts/fix-phase-tags.py` を新設. `--dry-run` / `--apply` / `--check-only` の 3 モード, `--max-errors N` ハードリミット, 集計フォーマットで stderr 膨張 (FU-410 系) 防御. `FileResult` (frozen dataclass) + `SweepReport` の責任分離.
  - **Phase 3 (dry-run 検証)**: `data/v0.2/` で 7,468 mismatches / 4,290 in-spec / 0 BOM / 0 errors 検出. 計画書 §1.3 と完全一致.
  - **Phase 4 (apply)**: Cowork sandbox 45s timeout に阻まれ 5 cycles で完走 (冪等設計のため再実行で skip / 続行). 全 7,468 ファイル書き込み完了.
  - **Phase 5 (検証)**: `verify.py --path data/v0.2`: 11,758 / 0 fail across 43 manifests. `pytest tools/shared/tests/`: 92 PASS. `ruff check`: All passed. NUL byte 0 files. 全 8 phase で 100% in-spec.

**検証** (ローカル CI 再現、Cowork sandbox):
- `ruff check tools/shared/src/juricode_shared/phase_tag.py tools/scripts/fix-phase-tags.py tools/shared/tests/test_phase_tag.py tools/shared/src/juricode_shared/__init__.py`: All checks passed
- `pytest tools/shared/tests/ -q`: **92 PASS** (既存 55 + 新規 phase_tag 37)
- `verify.py --path data/v0.2`: **11,758 / 0 fail** across 43 manifests (manifest hash 完全に不変、計画書 §1.5 の主張が実証)
- `validate-file.py` 5-file smoke test (各 phase 代表サンプル): 全 OK
- NUL byte sanity: 0 files in data/v0.2/

**Cowork sandbox で踏んだ既知事故 (再発 + 復旧)**:
- Write tool の末尾切断 (phase_tag.py / fix-phase-tags.py / __init__.py で計 3 回発生) → bash + Python 経由の atomic write で完全に書き直し
- ruff auto-fix が test_phase_tag.py に NUL byte (11 個) 残置 → 専用クリーンアップスクリプトで除去
- FU-302 で導入した `safe_write_text` の post-write verification (NUL byte / 末尾改行 / UTF-8 等) が機能し、本 corpus 側には NUL byte が 1 件も漏れていない (sweep 適用後の全 .md スキャンで 0 件)

**Phase 6 (git commit + push)**: Cowork sandbox の git lock 削除権限なしのため Windows/WSL 側で実行. 詳細手順書: `business/fu-415-commit-runbook-2026-05-26.md` (採択後コミットハッシュをここに追記).

**コミット粒度 3 分割** (計画書 §5.1 準拠、Conventional Commits):
1. `feat(shared): add phase_tag utility module and TDD tests`
2. `feat(scripts): add fix-phase-tags.py sweep driver`
3. `data(v0.2): sweep deprecated phase1-police tags in 7,468 files`

ref:
- `business/fu-415-phase-tag-sweep-plan-2026-05-26.md` (設計 v3)
- `business/fu-415-commit-runbook-2026-05-26.md` (Phase 6 手順書、別ファイルで作成)

**副次効果 (merge 後の運用作業)**:
- `tools/embed/build-v0.2-corpus.py` を 1 回再実行 (5-15 分) — embed corpus JSONL の `phase_category` を新 phase 値で再生成
- search UI の phase pill 表示が正常化
- `generate-training-data.py --phases <X>` 絞り込みが意味を持つ

**訂正 (2026-05-26 夕方追記)**:

本完了エントリの「副次効果」記述および計画書 §1.8
(`business/fu-415-phase-tag-sweep-plan-2026-05-26.md`) で
「下流 5 コンポーネントが正常化される」と記述したが、call graph を
追跡し直した結果、**直接の受益者は `tools/export/lawsy-bq/export-jsonl.py`
1 つのみ** であることが判明.

他 4 コンポーネントの実際の挙動:

| component | phase_category の取得元 | FU-415 sweep の効果 |
|---|---|---|
| `build-v0.2-corpus.py` | ディレクトリ構造 (`data/v0.2/<phase>/<abbrev>/`) | ❌ 影響なし |
| `embed.py` | corpus.jsonl のフィールド (← 上の生成物) | ❌ 影響なし |
| `generate-training-data.py --phases` | corpus.jsonl のフィールド | ❌ 影響なし |
| `search-ui` | corpus.jsonl のフィールド | ❌ 影響なし |
| `lawsy-bq/export-jsonl.py` | **frontmatter の tags[0] を正規表現抽出** | ✅ 影響あり |

FU-415 sweep の依然として正当な価値:

1. **frontmatter 一貫性** — `tags[0] = path-derived phase` が `bulk-ingest.py`
   の PHASE_MAP と一致する schema 適合性
2. **FU-P0-3 (Lawsy-Custom-BQ exporter) の前提条件** — まだ未実装だが、
   実装時に正しい phase で BigQuery export できる
3. **将来 contributor 向け** — frontmatter を直接読むツールを新規に書く際の
   正しい source of truth
4. **`docs/tag-vocabulary.md` カテゴリ A (フェーズ) の準拠**

つまり sweep は依然として正しい作業だが、「副次効果として複数下流が一斉に直る」
という主張は overstatement だった. 計画書テンプレへの学びは
`business/fu-415-followup-fixes-plan-2026-05-26.md` §6 に記録.

ref: `business/fu-415-followup-fixes-plan-2026-05-26.md` §1.2 Problem B

### 2026-05-25 (夕方) — FU-108 完了: v0.2 corpus manifest 生成 + v0.1 archive deprecate

> 当初想定の「e-Gov XML 再取得 sprint (1 週間)」は実は不要だった (実地調査で判明).
> 実態は **1 セッション / 約 5 時間で完了**.

- ✅ **FU-108: parse-egov.py 全件 round-trip 検証 + CI 組込み** (Phase 1〜7) — 詳細は本ファイル「P2」セクションの FU-108 [x] 完了マーク参照。コミットハッシュは Phase 6 push 完了後に追記。
  - **Phase 1 影響範囲確認**: tools/embed/retrieve.py / tools/search-ui / tools/parse/v0.2/extract_*.py 等の実コードで data/phase1-*/ ハードコード参照は **0 件**. 全て `--data-dir default=Path("data")` 形式で v0.2 を自動的にスコープ内に取り込む.
  - **Phase 2 manifest パッケージ新設**: `tools/parse/v0.2/manifest/` 配下に 4 モジュール (canonical_hash / article_entry / law_manifest / cli) + 3 unit test = 9 ファイル. **60 unit tests PASS**. Pydantic v2 BaseModel (`extra="forbid"` + `frozen=True` + pattern 検証) で型ドリフト防御.
  - **Phase 3 全件 manifest 生成**: 全 8 phase × 43 法令で `_source-manifest.json` 生成. verify.py round-trip 検証で **11,758 articles / 0 failed** across 43 manifests.
  - **Phase 4 v0.1 deprecate**: `data/phase1-*/` (8 phase, 11,758 条) を `archive/v0.1/` に mv + README.md で deprecate 理由明記 (has_proviso/has_items false バグ + 各号 content 欠落).
  - **Phase 5 CI 組込み**: `.github/workflows/ci.yml` 更新 (pytest に v0.2 + manifest tests 追加 + コメント整理). `pyproject.toml` 更新 (testpaths + `--import-mode=importlib`).
  - **Phase 7 docs 更新**: 本エントリ追記.

**検証**: ローカル CI 再現 (Cowork sandbox) で全 step 緑:
- `ruff check tools/`: All checks passed
- `ruff format --check tools/`: 56 files formatted
- `pytest tools/shared/tests tools/validate/tests tools/parse/v0.2/tests tools/parse/v0.2/manifest/tests`: **153 PASS**
  (60 manifest 新規 + 30 v0.2 parser + 55 shared + 8 validate)
- `verify.py --path data/v0.2`: **11,758 / 0 fail** across 43 manifests
- `validate-file.py` smoke test 2 件 (民法 770 / 刑法 36): OK

**Phase 6 (git commit + push)**: Cowork sandbox の `.git/index.lock` 削除権限なしのため、Windows/WSL 側で実行. 詳細手順書: `business/v02-sprint-commit-runbook-2026-05-25.md`. 4 commits (feat manifest pkg / data manifest / refactor archive / ci) + 本 FU-108 完了 commit. 採択後コミットハッシュをここに追記.

ref:
- `business/v02-corpus-quality-investigation-2026-05-25.md` (sprint 設計 + 調査結果)
- `business/data-quality-finding-2026-05-22.md` (発見 1 + 発見 2 の原典)
- `business/v02-sprint-commit-runbook-2026-05-25.md` (Phase 6 手順書)

### 2026-05-25 — P0 sprint 8/8 全件完了 (Day 1〜4 を 1 日で消化, NLnet 5/28 提出準備完了)

> 当初 4 日計画 (5/25-28) を 1 日で全消化. 残バッファ 3 日.

- ✅ **FU-301: PARAGRAPH_HEADING_PATTERN 2 重定義集約** (commit `bf773b58` + test `1861d26b`) — segment_parser.py で paragraph 見出し regex を module-level に集約. 枝番条網羅テスト 8 件追加. 既知事故 (g) 4,810 empty chunks の再発条件を構造的に阻止.
- ✅ **FU-302: 全 parser に write 後 sanity check** (commit `094fcfdd` module + `bf773b58` integration) — `tools/shared/src/juricode_shared/safe_write.py` を新設 (atomic write + NUL/末尾改行/UTF-8/JSONL 各行 json.loads 可 を assert). `safe_write_text` / `safe_write_jsonl` / `safe_append_jsonl_records` の 3 関数を 5 parser に適用. 17 件 unit test 全 pass. 既知事故 (a) WSL ruff corruption / (b) NUL padding / (c) heredoc 二重貼り付け の再発検知機構が完成. 本セッション中にも 7 ファイルで Cowork Edit ツールが末尾切断する事故が発生したが、safe_write は今後同種の事故を assert で即停止する設計.
- ✅ **FU-303: segment marker scope 限定** (commit `bf773b58` + test `1861d26b`) — `render_v02_md` の marker 挿入を paragraph 見出し直下スコープに限定. 失敗時に `parsing_warnings: list[str]` に記録 (silent fail 阻止). 7 件 unit test PASS.
- ✅ **FU-304: AmendLawNum regex literal alternation 化** (commit `50b9408a` + test `1861d26b`) — `AMEND_LAW_NUM_PATTERN` を greedy match から `(?:法律|政令|規則|省令|府令|告示|条約)` の 7 種限定 alternation に変更. 「雑種」等未対応 prefix は law_num=None として安全に弾く. 10/10 test PASS.
- ✅ **FU-401: parse-egov.py --phase-tag 必須化** (commit `787203e8`) — P0 sprint 最後の gate-keeper. ハードコード `"phase1-police"` を排除し `--phase-tag` を required 引数化. `article_to_markdown` / `_emit_article` / `main` の call chain で透過. bulk-ingest.py の subprocess cmd にも `["--phase-tag", phase]` を追加. 既存 corpus の sweep は [FU-415] (P1) に分離.
- ✅ **FU-402: settings 重複削除** (commit `b091c3e7`, 5/25 朝 Day 1.A push) — `tools/embed/retrieve.py:774-775` の dead code 削除.
- ✅ **FU-403: validate-all に argparse + bulk-ingest --path 追従** (commit `2150bd89`) — 旧 REPO_ROOT 固定で `--data-root` を silently 無視していた偽 green CI 源を解消. `--path /tmp/empty_dir` で exit 1.
- ✅ **FU-404: search-ui with_suffix bug 修正** (commit `b091c3e7`, 5/25 朝 Day 1.A push) — `tools/search-ui/server.py:46-48` の `prefix.with_suffix(".npy")` を文字列連結に修正.

**検証**: 全件 push 後の GitHub Actions CI が green を維持。`pytest tools/shared/tests + tools/validate/tests` 63 件 PASS、`pytest tools/parse/v0.2/tests` 30 件 PASS (合計 **93 件**)、validate-all (11,758 条 / 23,522 files)、verify.py (source-manifest hash 整合)、schema drift 全て緑。

ref: `business/code-reviews/2026-05-24-fix-plan.md` Day 1〜4 全 batch.

### 2026-05-19

- ✅ **FU-P0-1: `tools/parse/` MVP** (commit 82a4f6d, 6ed72d7) — `tools/parse/parse-egov.py` (18KB) + `verify.py` + `_canonicalize.py` を実装し, e-Gov XML → JuriCode-JP Markdown 変換器として警察 1,118 条 (commit 82a4f6d) + 自治体 651 条 (commit 6ed72d7) = **合計 1,769 条** を ingest. NLnet M2 約束 264 条の **6.7 倍**を 1st pass で達成. round-trip / コーナーケースの完成度検証は [FU-108] へ移管.
- ✅ **FU-P0-2: 自治体ユース対応の追加法令** (commit 6ed72d7) — `data/phase1-administrative/` を新設, 地方自治法 516 / 行政不服審査法 87 / 行政手続法 48 = 651 条を実装. 三本柱ターゲット ([[project-juricode-target-users]]) の二本目 (自治体) を支えるデータ基盤が成立. 行政手続法の条数妥当性 (88 想定 vs 48 実装) と地方自治法の本則全文 vs 抜粋方針の確定は [FU-108] へ移管.

### 2026-05-18

- ✅ **P0-1 (旧番号): `SourceFormat` を 4 値に拡張** — `docs/ir-spec.md §3.1` で `e-gov-html` 追加 + 各値の使い分けガイド付記
- ✅ **P0-2 (旧番号): IR integrity rule 3 件追加** — `cases_relevant_paragraph_exists`, `english_translation_implies_status`, `machine_translated → DRAFT` 推奨警告
- ✅ **P0-3 (旧番号): canonical サンプルのタグを vocabulary 準拠に** — `刑事法` を必須カテゴリ B として追加

---

## 関連

- 内部レビュー文書 (gitignored):
  - `business/code-reviews/2026-05-18-tools-and-schema-review.md` (初回)
  - `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` (v0.2 + shared レビュー, FU-301..321)
  - `business/code-reviews/2026-05-24-full-tools-review.md` (tools/ フルレビュー, FU-401..431)
  - `business/code-reviews/2026-05-24-fix-plan.md` (P0 4 日間スプリント詳細 + P1-P3 概観)
- 仕様書: [docs/ir-spec.md](./ir-spec.md), [docs/format-spec.md](./format-spec.md), [docs/tag-vocabulary.md](./tag-vocabulary.md), [docs/format-spec-v0.2.md](./format-spec-v0.2.md)
- 検証ツール: [tools/validate/README.md](../tools/validate/README.md)

---

## 柱5 (v0.3 pillar5 質問ログ UI) sprint 由来の新規 follow-up (2026-05-30)

### [ ] FU-507: 質問ログ -> 柱1 reranker 学習データ変換 batch (P0)

**やること**: `build/search-ui-logs.db` の questions/results/feedback/clicks から (query, positive=clicked rank, dwell 重み) を抽出し、匿名化サブセットのみ reranker fine-tune 用 jsonl に変換. 柱1 sprint の前提.

**関連**: 柱5 Phase A-F。

### [ ] FU-508: Tier 2 PII check (Claude API、人名 / 住所 / 固有事案名) (P0/P1)

**やること**: Tier 1 正規表現で取れない PII を Claude API で 2 次検出. FU-P0-4 弁護士レビュー後.

**関連**: 柱5 Phase D (Tier 1 のみ実装済)。

### [ ] FU-509: anonymized export を data/eval-set/logs-anonymized/ に公開 (P2)

**やること**: 匿名化済み質問ログが 100 件超で CC BY 4.0 公開を検討.

**関連**: 柱5 Phase D。

### [ ] FU-510: hard-negative dwell 捕捉 (clickless 離脱の検討時間) (P2)

**やること**: クリックせず離脱したユーザの検討時間を捕捉 (clicks.article_id nullable or 別 session-dwell テーブル + JS pagehide 送信). 柱1 reranker の hard negative 精度向上.

**関連**: 柱5 Phase C (per-click dwell のみ、clickless は現 schema 上不可)。

### [ ] FU-511: per-result feedback (FeedbackEntry に rank / article_id 拡張) (P3、任意)

**やること**: 現状 feedback は per-question. per-result 評価が必要なら FeedbackEntry に rank/article_id を追加 (schema 拡張).

**関連**: 柱5 Phase C/D。

### [x] FU-512: hybrid(BM25 char-ngram + RRF) 品質劣化が R@3 regression の真因 (2026-05-31 追加, P2) — ✅ 結論 2026-05-31 (Phase A ablation): hybrid は全 RRF k で dense に -10pt・逐語型 (kinsho) も悪化 → **dense-only 正式既定で close**。BM25/正規化の抜本是正による hybrid 再評価は FU-513 へ委譲。詳細 `business/v03-fu512-hybrid-bm25-plan-2026-05-31.md` §9。Phase D 追加知見 (2026-06-02): 表クエリでも dense>hybrid 逆転を確認 (dense R@3=83.3% vs hybrid R@3=50.0%、R@10 両者 83.3%)。RRF が BM25 ノイズで正解条文を top-3 外へ押し出す同一パターン。

**場所**: `tools/embed/retrieve.py` の hybrid 経路 (BM25 char 2-3gram + dense の RRF k=60)。

**問題**: 柱1-B ablation (2026-05-31, 172 queries) で dense-only R@3=72.7% に対し hybrid 57.6% / hybrid+rerank 57.6% と劣化。R@10 はほぼ不変 (79.1%→76.2%) なのに R@1/R@3 が崩壊 = BM25 ノイズが RRF 融合で正解条文を降格させ、cross-encoder reranker でも回復しない。R@3 regression の真因は FU-425 の受け渡しバグではなく hybrid 品質。

**やること**: (a) 当面 hybrid/reranker を既定オフ維持 (dense-only 推奨)。(b) BM25 トークナイザ (char-ngram → 形態素/別 n-gram) / RRF 融合比・k の是正を検討し、hybrid が dense を上回るか再 ablation。

**関連**: 柱1-B / `business/v03-pillar1-B-ablation-findings-2026-05-31.md` (gitignored)。

### [x] FU-513: 正準テキスト正規化を juricode_shared に集約 (2026-05-31 追加, P2) — ✅ 完了 2026-06-01 (commit C1/C2/C3: `juricode_shared/text_norm.py` 新設 + `retrieve.py` import 置換。manifest hash 不変・R@3=72.7% 不変・337 tests PASS。D2 defer: corpus/parser 経路は FU-405 で別途)

**場所**: クエリ側 `tools/embed/retrieve.py` (`normalize_legal_query`/`_tokenize_chargram`) / corpus 側 `tools/embed/build-v0.2-corpus.py` (`make_augmented_text`) / parser 側 (FU-205/405 の markdown_regex)。

**問題**: テキスト正規化が各所でバラバラ (クエリ/corpus/書込/parser) で、新検索コンポーネント (dense→BM25→reranker→形態素) を足すたびに「テキストが汚い」を再発見する**再発クラス** (FU-512 §10)。dense は改行/空白ノイズを吸収するが BM25 char-ngram は吸収せず、同一 `text` を共有するため BM25 でのみ顕在化。

**やること**: 正準正規化契約 (改行/空白/全角半角/漢数字/BOM 等) を `tools/shared/src/juricode_shared/` に1箇所定義し、クエリ側・BM25 側・(将来) 形態素側が同一契約を使う。FU-205/405 (markdown_regex 共有化) と統合検討。

**破壊的変更注意**: corpus の canonical text を変える場合、現 dense 埋め込み (`build/*.npy`) とベンチ結果は現テキストに紐づくため**再埋め込み + ベンチ再測定が必須**。

**関連**: FU-512 §10 / FU-205 / FU-405 / `business/v03-fu512-hybrid-bm25-plan-2026-05-31.md` (gitignored)。

> 備考: FU-418 (cosine top-k 共通化、search-ui が retrieve.py から import) は柱5 sprint では未実施 (open のまま). search-ui の _topk は retrieve.py と重複するが機能影響なし、refactor 案件.

### [ ] FU-514: 法人税基本通達 (Directive) を Pydantic IR 化 (2026-06-02 追加, P2)

**場所**: `tools/parse/parse-nta-tsutatsu.py` (dict 実装) / `tools/shared/src/juricode_shared/ir.py` (Directive モデル未定義)。

**問題**: PR #15 (commit `dc00d9e8`) で取込した通達チャンクは dict のまま出力しており、Pydantic バリデーションを通っていない。PR #16 で TaxAnswerChunk を Pydantic IR 化したが、Directive は同じパターンで未対応 (PR #15 は merge 済のため別 sprint)。

**やること**: `tools/shared/src/juricode_shared/ir.py` に `DirectiveChunk` モデル (+ `DirectiveRelatedArticleRef` 等サブモデル) を追加。TaxAnswerChunk と共通化できるフィールド (source_url / license / attribution) は `ExternalSourceChunkBase` に括る検討 (P6b・FU-514)。`parse-nta-tsutatsu.py` を `DirectiveChunk.model_dump()` 経由に移行。`juricode-directive.schema.json` を生成・CI drift gate 対象に追加。

**関連**: FU-512 (TaxAnswer Pydantic IR, PR #16 commit `8ebb7589`) / PR #15 (通達取込).

---

### [x] FU-515: 本則条文の TableStruct (税率表等) が md/chunks に取りこぼし (2026-06-08 追加, P1)

**DONE 2026-06-17** — Phase A-C (PR #19 `82156f7a`): 本則 table chunks 0→296・走査 data/v0.2 化・newline 根治・312/180 golden ロック。Phase D-a (PR #20 `dc086a9e`): 新規196本則 table を増分embed (corpus 92,486→92,682)・全eval PASS (G1 v5==v6/G2 R@3=0.833/G3 312・180 rank1)。Cowork が PR diff + 実artifact独立検証。

**Phase D-b (附則700) = REJECT (2026-06-21・PR #23 `1795df4c`)**: 附則 (SupplProvision) table 700 件を aug-v6 に増分embed (実Gemini・有料/aug-v7 93,382) し採否を測定。**退行ゼロ** (G1 集計 v7==v6 完全一致・G1-local 10本則 primary の rank 不変=`shotoku-zei-hou` 445集中の**検索ジャック懸念を否定**・G2 R@3=0.833維持) だが、**附則 value 未達** (G3-sp 実rank: A-straight rank2 hit のみ・口語パラフレーズ rank11/17・B-straight rank6 → exact-match残響でなく真の semantic は引けない) → **aug-v7 非昇格・附則既定OFF・aug-v6 据え置き** (事前承認済の正当 REJECT)。G1-local 母数は実 **N=10** (計画 §2 の N=16=既存6+新規10 は誤記: 実 eval-set の本則参照は shotoku 1件のみ・chihou本則0件。REJECT基準は絶対数≥2でN非依存ゆえ無傷)。ロック golden (`data/eval-set/tax-honbun-local/` + `tax-supplproviso-probe/`) + reward-hacking checksum ゲート (`tools/scripts/verify-eval-set-checksum.py`・期待SHA256はrepo variable `EVALSET_GOLDEN_SHA256`=agent書込スコープ外・正当更新は人間限定 `approve-eval-set.sh`) を追加。

**場所**: `tools/parse/v0.2/segment_parser.py` (本則パース経路) / `tools/parse/v0.2/extract_table_from_xml.py` (表抽出モジュールは実在するが本則未適用・標準パイプライン未統合) / `data/v0.2/**` + `build/chunks/**`。

**現状 (2026-06-08 grep 実測)**:

- 地方税法 **52条 (道府県民均等割) / 312条 (市町村民均等割) / 72条の24の7 (事業税標準税率)** の `<TableStruct>` 内の税率表 (例: 312条 均等割 5万〜300万円の9区分) が、`data/v0.2/phase1-tax/chihou-zei-hou/chihou-zei-hou-article-312.md` の segment にも `build/chunks/` にも**存在しない**。md は表のリード文 (「次の表の上欄に掲げる…額とする。」) で途切れ、**表本体が欠落**。
- `build/chunks` の `.table.chunks.jsonl` は **施行令/施行規則系で 82 件、本則系は 0 件**。
- 表抽出モジュール `extract_table_from_xml.py` は実在するが production の呼び出し元が無く (module 単体 + tests のみ)、本則には未適用 (施行令分は ad-hoc 実行で生成された模様)。

**問題**: 税率表・別表など `<TableStruct>` は条文の**実体的な法令内容**。本則で欠落すると「現行条文を構造化」の看板に対しデータが不完全。とくに税法 (52/312/72の24の7) は表が税率そのものであり、retrieval で条文を引いても税率値が得られない。

**やること**:

1. corpus 全体で本則 TableStruct の取りこぼし範囲を棚卸し (e-Gov XML に `<TableStruct>` を持つ本則条文を列挙し、対応 md/chunks に表があるか突合)。
2. `extract_table_from_xml.py` を本則パース経路 (segment_parser / manifest cli) に統合し、標準パイプラインで本則表も pipe 直列化 + `.table.chunks.jsonl` 生成。
3. 影響条文の md/chunks/manifest を再生成 (round-trip hash 再検証)。
4. 本則表の round-trip 検証を CI に追加 (表欠落の再発防止)。

**検証元**: e-Gov 法令 API v2 (`?elm=MainProvision-Article_312` 等) で本則 `<TableStruct>` の存在を確認済。下流の税法ユース検証中に発見 (2026-06-08)。

**関連**: FU-108 (round-trip 検証) / FU-318 (rollup chunk filter) / `extract_table_from_xml.py` (既存の表抽出資産)。

**残課題 (FU-515 派生)**: (a) **D-b = 完了 (REJECT, 上記 2026-06-21・PR #23)**。附則700の embed 是非は「退行ゼロだが value 未達」で aug-v6 据え置きに決着。再投入の余地は下記 **D-c** に継承。(b) **Phase E — 表本体の md への反映 + manifest 再生成 (round-trip hash 再検証)** (P2)。現状 D-a は `build/chunks` (gitignored) のみへの反映で、canonical な `data/v0.2/**` md には表本体が未収録。**別 GO 必須** (md/manifest は locked corpus のため独立計画書 + user GO)。

---

### [ ] FU-516: data/phase1-tax と data/v0.2/phase1-tax の二重 git 管理・divergent (2026-06-17 追加, P2)

**場所**: `data/phase1-tax/**` (旧 top-level layout) と `data/v0.2/phase1-tax/**` (canonical layout)。

**問題 (発見A)**: FU-515 の走査 default を `data/` → `data/v0.2` に是正した過程で発覚。税法 corpus が `data/phase1-tax` と `data/v0.2/phase1-tax` の **2 箇所で git 管理されており内容が divergent** (旧 layout は extract_table の旧 default が拾っていた経路)。canonical は `data/v0.2`但し、旧 `data/phase1-tax` が残存し二重管理・乖離リスク。

**やること**: (1) 両者の diff を棚卸しし canonical (`data/v0.2`) を確定。(2) 旧 `data/phase1-tax` の deprecate/削除 or `archive/` 退避 (v0.1 同様)。(3) CI / 各 tool の走査 root が `data/v0.2` に統一されているか call graph 確認 (FU-307 の scan 統一と併せて検討)。

**スコープ精密化 (2026-06-23 実測)**: ファイル単位 diff = only_old 12（全部 施行令/施行規則の
`_source-manifest.json`）/ only_new 2,266 / common 3,167（全件 v0.1↔v0.2 形式違いで sha 差分）。
**重要発見**: この 12 施行令 manifest は Phase 5b（`dd875322` 2026-06-01
"index 12 tax enforcement orders/regulations"）で**旧 layout にのみ生成**され、v0.2 は施行令 .md は
在るが `_source-manifest.json` が **0 個 = round-trip 未検証**。⇒ **単純削除不可**（12 施行令の
round-trip 接地を失う）。正しい解消 = (a) v0.2 形式 manifest を 12 施行令/施行規則に生成（`manifest.cli`）
→ (b) round-trip 緑 → (c) 旧 `data/phase1-tax` 撤去 → (d) CI 緑。**副産物**: v0.2 税施行令の
round-trip 未検証ギャップを修復。**FU-515 Phase E の Entry Criteria**（locked corpus 変更につき独立 GO 必須）。

**関連**: FU-515 (走査 default 是正) / FU-307 (kou/supplproviso/add_rollup の `_SHARED_SRC` + scan 統一) / FU-108 (v0.1 → archive deprecate の前例)。

---

### [ ] FU-517: corpus に 716 件の pre-existing 重複 chunk_id (2026-06-17 追加, P3)

**場所**: `build/corpus-v0.2-augmented-*.jsonl` / `build/embeddings/*.meta.jsonl` (生成元は `build/chunks/**` の各 chunk ファイル)。

**問題**: FU-515 Phase D-0 整合 pre-check で発覚。corpus に **716 件の重複 chunk_id** が存在 (例: `chihou-jichi-hou-art-1-p1-kou-N` 等の kou チャンク)。aug-v5 自体が同一 716 件を持って構築済 (embed は positional に重複許容のため meta が 92,486 行 / unique 89,389)。**table chunk 由来の重複はゼロ** (1,342 件すべて unique)・FU-515 は新規重複を導入していない。resume は重複 id を既 embed として skip するため当面の retrieval 健全性に実害は無いが、corpus の data hygiene として要 de-dup。

**やること**: (1) 716 件の重複の生成元 chunk ファイルを特定 (どの抽出経路が同一 id を二重出力しているか)。(2) chunk id 採番 or merge ロジックを修正し dedupe。(3) 再 embed 時に重複ゼロを assert する guard 追加。

**関連**: FU-515 (Phase D-0 pre-check で検知) / `build/_fu515_phase_d_precheck.py` (検知ハーネス・gitignored)。

---

### [ ] FU-515 D-c: 附則 table の paraphrase recall 改善 → 再投入 (2026-06-21 追加, P3)

**経緯**: FU-515 Phase D-b (PR #23) で附則 (SupplProvision) table 700 件の増分embed は **退行ゼロ** を確認したが、**口語パラフレーズでの retrieval が弱い** (G3-sp: A-straight rank2 hit に対し A-paraphrase rank11・B-straight rank6・B-paraphrase rank17) ため canonical 昇格を見送り (aug-v6 据え置き・附則既定OFF)。noise 懸念 (`shotoku-zei-hou` 445集中による既存劣化) は否定済 = **再投入は安全側**。

**やること**: 附則 table の semantic (paraphrase) recall を上げる手段を検討し、value がロック基準 (G3-sp straight+paraphrase 両方 rank≤5) を満たせば aug-v7 を再評価・昇格。候補: (1) **reranker** (柱1) で附則 table 候補の rank を持ち上げる。(2) **附則専用 prefix / augmentation 見直し** (現状 prefix が附則の文脈 [読替表・経過措置] を表現しきれていない可能性)。(3) **chunk 設計の見直し** (親条文 prose と table chunk の結合度)。

**流用可能資産**: 本 D-b の eval-set (`data/eval-set/tax-honbun-local/g1-local.jsonl` G1-local + `tax-supplproviso-probe/g3-sp.jsonl` G3-sp・**LOCKED**) と checksum ゲート (`tools/scripts/verify-eval-set-checksum.py` + `approve-eval-set.sh`) はそのまま再利用可能。増分embed 手順 (pre-check → tripwire → 実Gemini → vector health → eval gate) も `build/_fu515_phase_db_*.py` を雛形にできる。

**関連**: FU-515 D-b (PR #23 `1795df4c`・REJECT 由来) / 柱1 reranker / `benchmarks/results/2026-06-21-aug-v7-fu515-supplproviso.json` (eval 記録)。

---

*Last updated: 2026-06-21 — FU-515 D-b 完了マーク (REJECT, PR #23 `1795df4c`: 退行ゼロだが附則 value 未達→aug-v7 非昇格) + FU-515 D-c 登録 (附則 paraphrase recall 改善→再投入, P3). 前回: 2026-06-17 FU-515 Phase A-D (PR #19+#20) + FU-516/517 登録. 起票・完了マークは Cowork、commit/push は Claude Code (tools/data/build 管轄). / Maintained by: CHOKAI Co.,Ltd. / Status: v0.7.9*

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

### [ ] FU-301: PARAGRAPH_HEADING_PATTERN の 2 重定義集約 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py:87-89` と `:370-374` で同じ paragraph 見出し regex を 2 重定義.

**問題**: 既知事故 (g) 4,810 件 empty chunks bug と完全に同型の再発条件. AI が「regex を直して」と指示されたとき片方しか直さない事故が確実に起きる.

**やること**: 1 つの module-level `PARAGRAPH_HEADING_PATTERN` に集約 + `tests/test_paragraph_heading_pattern.py` で枝番条網羅テスト (`第三条` / `第三条の二` / `第百九十七条の三第二項` / `第三条第一項`).

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §D-01 / `business/code-reviews/2026-05-24-fix-plan.md` Day 1.B

---

### [~] FU-302: 全 parser に write 後 sanity check を追加 (2026-05-24 追加, 2026-05-25 実装完了・commit 待ち)

**実装状況**: `tools/shared/src/juricode_shared/safe_write.py` を新設 (89 行) + `tools/shared/tests/test_safe_write.py` で **17 件 unit test 全 pass**. 5 parser (`segment_parser.py` / `extract_kou_from_xml.py` / `extract_supplproviso_from_xml.py` / `add_rollup_chunks.py` / `parse-egov.py`) の write 経路を `safe_write_text` / `safe_write_jsonl` / `safe_append_jsonl_records` に置換済. `tools/shared` 全 55 件 PASS / `tools/parse/v0.2/tests` 29/30 PASS (残 1 件は FU-304 未実装が要因, 別件).

**場所**: `tools/parse/v0.2/{segment_parser,extract_kou_from_xml,extract_supplproviso_from_xml,add_rollup_chunks}.py` および `tools/parse/parse-egov.py` の write_text / fh.write 直後.

**問題**: 既知事故 (a) WSL ruff corruption / (b) Edit/Write NUL padding / (c) cat heredoc 二重貼り付け のいずれも parser 側に検知機構がない. 静かに壊れた `.md` / `.chunks.jsonl` が増産される.

**やること**: 共有ヘルパー `tools/shared/src/juricode_shared/safe_write.py` を新設.

- `safe_write_text(path, content)`: NUL バイト不在 / 末尾改行 / UTF-8 valid を assert
- `safe_write_jsonl(path, records)`: 各行 `json.loads` 可を assert
- 違反時は `.tmp` を残して元ファイル維持 (atomic write パターン)

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §D-02 / Day 3.A

---

### [ ] FU-303: segment marker `replace(..., 1)` のスコープ限定 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/segment_parser.py:461-463`. `body.replace(seg.text[:20], MARKER, 1)` で「## English Translation」セクションにも誤置換 / `\n` を含むと no-hit でサイレント失敗.

**問題**: 静かに壊れたサンプル (英訳セクションが marker で破損) が release に紛れ込む.

**やること**: paragraph 見出し直下から「次の paragraph 見出しまたは `## ` まで」のスコープに限定して挿入. 失敗時は `parsing_warnings: list[str]` に記録.

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §D-03 / Day 2.B

---

### [ ] FU-304: AmendLawNum regex を literal alternation 化 (2026-05-24 追加)

**場所**: `tools/parse/v0.2/extract_supplproviso_from_xml.py:148`. `r"(?:[^第]*第([零〇一二三四五六七八九十百千万\d]+)号)?"` の greedy match で「規則」「告示」等の前置にも誤検出.

**問題**: 附則 metadata の `amend_law_num` フィールドに誤った法令種別が記録される.

**やること**: `r"(?:(?:法律|政令|規則|省令|府令|告示|条約)第([零〇一二三四五六七八九十百千万\d]+)号)?"` に置換. Why コメント追加.

**関連**: `business/code-reviews/2026-05-24-v02-parser-pipeline-review.md` §D-04 / Day 2.A

---

### [ ] FU-401: parse-egov.py phase tag のハードコード解消 (2026-05-24 追加)

**場所**: `tools/parse/parse-egov.py:339`. `"tags": ["phase1-police", "auto-generated"],` で固定. 既知事故 (d) bulk-ingest phase tag bug の**真因**.

**問題**: bulk-ingest.py の `PHASE_MAP` は出力ディレクトリ決定にしか使われず、生成 .md の `tags` には届かない. つまり `phase1-tax/` 配下の .md にも `tags: [phase1-police, ...]` が記録される潜伏 bug 状態. 単独実行や外部寄稿者の手元実行で再発確実.

**やること**:
1. `parse-egov.py` に `--phase-tag` を必須引数として追加 (default なし、未指定でエラー化)
2. L339 を `args.phase_tag` 参照に変更
3. `tools/fetch-egov/bulk-ingest.py:171-183` の subprocess cmd 構築に `["--phase-tag", phase]` を追加
4. 既存 30 法令の sweep は別途 FU-415 で対応

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §C-01 / §7 (事故 d 真因) / Day 4.A

---

### [ ] FU-402: retrieve.py `settings = []` 2 重代入を削除 (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:774-775`. `settings = []` が 2 行連続. dead code.

**問題**: レビューを通過した証拠 (品質意識への直接の信号). ruff F841 でも引っかかる可能性.

**やること**: 1 行削除. CI の ruff check を強制 (現状 follow-up 中).

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §D-01 / Day 1.A

---

### [~] FU-403: validate-all.py に argparse 追加 (2026-05-24 追加, 2026-05-25 実装完了・commit 待ち)

**実装状況**: `tools/validate/validate-all.py` を argparse 化 (`--path`, `--verbose` を `verify.py` と命名揃え, 旧 REPO_ROOT 固定を解除). `--path /tmp/empty_dir` で「0 files」エラー化 (silent ignore 解消, exit 1). `tools/fetch-egov/bulk-ingest.py:209` の subprocess.run 呼び出しを `--data-root` から `--path` に追従修正済.

**場所**: `tools/validate/validate-all.py` は argparse なし、`sys.argv` を読まず `REPO_ROOT` 固定. `tools/fetch-egov/bulk-ingest.py:209` が `--data-root` 引数を渡すが silently 無視.

**問題**: 非標準 data-root での bulk-ingest 検証は「実は何も検証していない」状態. 偽の green CI が出る.

**やること**:
1. `validate-all.py` に argparse を追加 (`--path`, `--verbose` を `verify.py` と命名揃え)
2. `bulk-ingest.py:209` を `--path str(data_root)` に修正
3. 検証: `python validate-all.py --path /tmp/empty_dir` で「0 files」エラー (silent ignore でない)

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §D-02 / Day 3.B

---

### [ ] FU-404: search-ui/server.py の `with_suffix()` バグ修正 (2026-05-24 追加)

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

### [ ] FU-310: modality 優先順位 Why コメント追加 (2026-05-24 追加)

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

### [ ] FU-406: retrieve.py main を RetrievalPipeline クラスに分解 (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:577-787` (main 211 行で 4 つの責務同居).

**やること**: `RetrievalPipeline` クラスに `dense_retrieve / hybrid_combine / dedup_by_article / rerank / aggregate_metrics` を分割. main は CLI parsing + pipeline 実行のみ (50 行以下).

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §A-01 / 計画 §4 Week 1

---

### [ ] FU-407: `dedup_by_article` の unit test 追加 (2026-05-24 追加)

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

### [ ] FU-414: search-ui に `--allow-external` flag (2026-05-24 追加)

**場所**: `tools/search-ui/server.py:1-30`. CORS / auth なし、`--host 0.0.0.0` で誤公開リスク.

**やること**: `--host` を 127.0.0.1 で hard pin、`--allow-external` 明示同意時のみ 0.0.0.0 許可 + warning ログ.

**関連**: §D-10 / 計画 §4 Week 3

---

### [ ] FU-415: phase tag sweep script (FU-401 完了後) (2026-05-24 追加)

**場所**: FU-401 で `--phase-tag` 必須化した後、既存 `data/**/*.md` の `tags[0]` が古い `phase1-police` のままになっている可能性. path-based phase で書き換えるバッチ.

**やること**: `scripts/fix-phase-tags.py` を新設、`--dry-run` mode で diff 確認後に apply. 失敗時は `git checkout HEAD -- data/` で revert (既知事故 (d) で実証済).

**関連**: `business/code-reviews/2026-05-24-full-tools-review.md` §7 (事故 d) / 計画 §4 Week 4

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

### [ ] FU-108: parse-egov.py 全件 round-trip 検証 + 自治体法令の条数妥当性 (2026-05-20 追加)

**現状**: FU-P0-1 (parse MVP) と FU-P0-2 (自治体法令) を 2026-05-19 に 1st pass 完了. 以下が未検証として残る.

**やること**:

1. **全 1,769 条で round-trip 検証**: `tools/parse/verify.py` を全件適用し, e-Gov XML → IR → Markdown → IR の循環が `_source-manifest.json` と整合するかを CI に組み込む
2. **行政手続法の条数妥当性**: 旧 FU-P0-2 想定の「88 条」と実装 48 条の差分原因を調査. e-Gov 一次資料との照合 (枝番条・附則を含めた網羅範囲を文書化)
3. **地方自治法の方針確定**: 実装 516 条は本則全文相当. 旧 FU-P0-2 で「主要条のみ抜粋」と書いた方針との整合を `docs/strategy.md` 等で明文化
4. **コーナーケース coverage**: 附則・経過措置・別表 (parse-egov.py が現状扱わない領域) の整理. [FU-101] (ARTICLE_ID_PATTERN 附則対応) と連動

**関連**: FU-P0-1 / FU-P0-2 の completeness check として位置付け. NLnet M2 進捗報告 (2026-08 採択結果後) の品質エビデンスとしても使える.

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

### [ ] FU-423: train-reranker.py docstring の `/home/masa/...` を HF model ID に (2026-05-24 追加)

**場所**: `tools/finetune/train-reranker.py:10`. 環境固有パスを example に残すと AI が hard-code する.

**やること**: HF model ID (例: `hotchpotch/japanese-reranker-cross-encoder-small-v1`) に置換、local path は optional override 扱い.

**関連**: §C-05

---

### [ ] FU-424: train-reranker.py で fit 終了後に metrics サマリ出力 (2026-05-24 追加)

**場所**: `tools/finetune/train-reranker.py:131`. 成功時 save パスのみ表示、metrics サマリなし.

**やること**: `evaluator` の最終スコア (`fit` 戻り値) を必ず print.

**関連**: §D-11

---

### [ ] FU-425: retrieve.py hybrid + rerank 連動修正 (2026-05-24 追加)

**場所**: `tools/embed/retrieve.py:707-716`. `--hybrid-bm25 --reranker` 併用時、rerank が dense top-N しか見ず hybrid の RRF 結果が捨てられる.

**やること**: rerank も `top_idx_wide` (hybrid 後) を candidate にする option を追加.

**関連**: §D-14

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

*Last updated: 2026-05-25 (Day 3: FU-302 + FU-403 実装完了, commit 待ち) / Maintained by: CHOKAI Co.,Ltd. / Status: v0.5 — 2026-05-24 の 2 本のレビュー (v0.2 parser pipeline + tools フル) で計 **52 件** の指摘を P0×8 / P1×19 / P2×16 / P3×9 として追加. NLnet 5/28 提出までに P0 8 件を `business/code-reviews/2026-05-24-fix-plan.md` の 4 日間スプリント計画で消化予定. 残既存 P0: FU-P0-3 (Lawsy-Custom-BQ exporter), FU-P0-4 (法的整合性レビュー), FU-P0-5 (人月配分・外注設計)*

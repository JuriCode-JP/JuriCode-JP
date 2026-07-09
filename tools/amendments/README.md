# tools/amendments — 改正履歴 populate

条文 md frontmatter の `amendments[]`(改正履歴)を、e-Gov 法令API v2 の改正版チェーンの
**版間 diff** から機械生成する。案B(条文単位帰属)。config 駆動で複数税法に対応
(`LAW_CONFIGS`: 消費税法パイロット + 相続税法 横展開①)。

## 何をするか

1. `get_revisions(law_id)` で全改正版を取得し、**施行済(Previous/CurrentEnforced)版**を
   API の native 順(施行日降順)を反転した**真の昇順チェーン**に並べる。
2. `CurrentEnforced` がちょうど1件かつチェーン最終リンク・施行日が単調非減少であることを
   **fail-loud で assert**(順序推論が崩れたら黙って誤帰属せず raise)。
3. 直近 5 年目安(施行日 ≥ 2020-04-01)の各版を、その predecessor と
   **本則条(`MainProvision//Article`)単位**で diff。
4. 変化した条を、その版(`effective_date` / `law_num` / `law_name`)に帰属し、
   `description` を版間 diff の要点(改正ラベル + 先頭 diff 断片)として機械生成する。
5. 本文実 diff が空の版(附則のみの omnibus)は付与しない。
6. 各条 md の frontmatter に `amendments:` を **byte 保存で splice**(本文・`version_date`・
   他フィールド非改変、べき等)。

出力フィールドは IR の `Amendment` モデル(`juricode_shared.ir`、`extra="forbid"`)に一致:
`effective_date` / `law_num` / `law_name` / `description` / `source_url`。

## 使い方

`--law`(既定 `shouhi-zei-hou`)で対象法令を選ぶ(`LAW_CONFIGS` の登録キー)。

```bash
# dry-run(書込なし・実測サマリ + サンプル表示。既定は消費税法)
python tools/amendments/extract_amendments.py --samples 6

# 相続税法を dry-run
python tools/amendments/extract_amendments.py --law souzoku-zei-hou --samples 6

# 書込(条 md に amendments を splice。べき等)
python tools/amendments/extract_amendments.py --law souzoku-zei-hou --write

# cache のみで再現(ネットワーク非依存。先に一度 online 実行が必要)
python tools/amendments/extract_amendments.py --law souzoku-zei-hou --offline --write
```

改正版の全文 XML は `cache/revisions/{law_revision_id}.xml`(`.gitignore` で除外)にキャッシュ。
per-law の revisions 一覧は `cache/revisions/_revisions_{law_id}.json`。

## データ契約

`amendments[]` は当該条文に**本文の実質的変化**をもたらした改正のみを収録する
= 改正の完全な一覧ではない(附則のみ・omnibus 付随改正は含まない)。網羅的な改正沿革は
e-Gov `GET /law_revisions/{law_id}` を一次情報として参照する。詳細は
[`docs/format-spec.md` §4.5](../../docs/format-spec.md)。

**章単位の大改正で現行 corpus に残らない条の改廃は出ない**(スコープ = 本則現行条)。
案B は現行 corpus に実在する条 (`@Num`) にのみ帰属するため、章ごと廃止・番号振替で
現行版に残らなくなった条の改廃は `amendments[]` に記録されない。例: 法人税法の
連結納税制度 → グループ通算制度移行 (2022-04-01・令和二年法律第八号) で消滅した旧
第81条系枝番 (81-2〜81-31) は現行 corpus 非在ゆえ非付与。一方、削除後も番号が
プレースホルダとして現行 corpus に残る条 (例 法人税法 15-2) は現行条ゆえ「本条を削除」
として正しく付与される。これは決定論的忠実性を優先した設計上の非網羅性であり、
網羅的沿革は上記 e-Gov 一次情報を参照する。

## 横展開時の注意

条ずれ・番号振り直し・削除の有無は**法令依存**(消費税法・相続税法ともに枝番挿入のみだった)。
他税法へ広げる際は法令ごとに版間 diff の性質を再確認(probe)してから `LAW_CONFIGS` に追加する。

**range Num ガード(共通防御)**: e-Gov は連続削除条を 1 つの `Article @Num="N:M"`
(例 相続税法の `56:57` = 第五十六条及び第五十七条削除)に畳み込む。この range Num は単一の
corpus 条にマップできず案B の安定キー前提が崩れるため、`article_text_map` が diff 対象外に
**skip + log** する(fail-safe)。相続では inert(corpus 非在)だが法人税/所得税の削除条にも効く。

テスト: `tools/amendments/tests/`(committed 成果物 + revisions fixture を読む hermetic 検証)。
新法令を追加したら test を新設し **`ci.yml` の pytest 行と `pyproject.toml` の `testpaths` の両所**に
配線する(CI は明示列挙で走るため testpaths だけでは CI 非実走)。

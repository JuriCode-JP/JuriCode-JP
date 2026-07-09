# tools/amendments — 改正履歴 populate

条文 md frontmatter の `amendments[]`(改正履歴)を、e-Gov 法令API v2 の改正版チェーンの
**版間 diff** から機械生成する。案B(条文単位帰属)。パイロット対象は消費税法。

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

```bash
# dry-run(書込なし・実測サマリ + サンプル表示)
python tools/amendments/extract_amendments.py --samples 6

# 書込(条 md に amendments を splice。べき等)
python tools/amendments/extract_amendments.py --write

# cache のみで再現(ネットワーク非依存。先に一度 online 実行が必要)
python tools/amendments/extract_amendments.py --offline --write
```

改正版の全文 XML は `cache/revisions/{law_revision_id}.xml`(`.gitignore` で除外)にキャッシュ。

## データ契約

`amendments[]` は当該条文に**本文の実質的変化**をもたらした改正のみを収録する
= 改正の完全な一覧ではない(附則のみ・omnibus 付随改正は含まない)。網羅的な改正沿革は
e-Gov `GET /law_revisions/{law_id}` を一次情報として参照する。詳細は
[`docs/format-spec.md` §4.5](../../docs/format-spec.md)。

## 横展開時の注意

条ずれ・番号振り直し・削除の有無は**法令依存**(消費税法では枝番挿入のみだった)。
他税法へ広げる際は法令ごとに版間 diff の性質を再確認してから populate する。

テスト: `tools/amendments/tests/`(committed 成果物 + revisions fixture を読む hermetic 検証)。

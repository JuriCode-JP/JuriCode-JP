# NTA 通達パーサ エッジ台帳 (edge_registry)

`parse-nta-tsutatsu.py` で遭遇した構造エッジの軽量レジストリ (FU-519 §15)。
新エッジは末尾に追記し、対応コミット/テストを残す。**parser 修正は data 生成 PR と分離**
し、修正後は過去章ハッシュ差分=0 を計測する (Bug45 / CLAUDE.md §0.2)。

| ID | エッジ | 内容 | 対応 | ガードテスト |
|---|---|---|---|---|
| EDGE-001 | title-lag | flush 時の `current_title` が次項見出しへ進んでおり title が +1 ズレ。削除通達は見出しを持たないのに前項を継承 | 番号検出時に見出しを束縛 (`current_item_title`) + consume-once (`current_title=None`) | `test_shouhi_tsutatsu.py::test_title_not_lagged` / hojin byte 回帰 |
| EDGE-002 | split-strong (CASE B) | 消費税通達は番号が `<strong>1</strong>－3－2` と分割され `<strong>` だけでは番号にならない | CASE A (番号全体が strong) が外れたとき段落先頭テキストから番号を拾う `_LEADING_DIRECTIVE_RE` | `test_shouhi_tsutatsu.py::test_split_strong_sections_present` |
| EDGE-003 | 目 (4 階層) の source_url | 第5/9/12/14章は `<章>/<節>/<目>.htm` (例 `09/01/01.htm`)。旧フラット式 `{base}/{chapter}/{stem}.htm` は目レベルを落とし誤 URL | 多章モードはファイルの cache-root 相対パスから source_url を再構築 (`_build_source_url`, `as_posix`)。HTML 見出し階層は h1/h2 のまま (目は file 分割のみ・新見出しレベルなし) | `test_tsutatsu_multichapter.py::test_moku_subpath_source_url_end_to_end` |
| EDGE-004 | 章プレフィックス数値順 | 多章マージで naive 文字列ソートだと "10" < "2" となり第10章が第2章前に散る | 既存の数値タプルキー (`-`/`の` で分割し int 化) を全体ソートに再利用 | `test_tsutatsu_multichapter.py::test_cross_chapter_numeric_sort` |
| EDGE-005 | 前文/旧版アーカイブ | root 直下 `02.htm` (前文・説明文=制定文) と `20230930/` (令和5年9月30日以前の旧通達) は通達項目でない | 多章 rglob で「章ディレクトリ = 2 桁」のみ採用 (`_CHAPTER_DIR_RE.fullmatch`) | `test_tsutatsu_multichapter.py::test_excludes_preamble_and_archive` |
| EDGE-006 | 削除通達 + 参考注記 | 削除通達は通常 title 空・本文空・「（…課消…により削除）」を amendment_note へ分離。だが廃止に伴う経過措置等で末尾に「（参考）…」が続く稀ケース (例 9-3-7) では削除マーカーが本文先頭=末尾でないため amendment_note に入らず本文に残る | テキストは忠実に保持・title-lag なし・汚染なし=データ損失なし。amendment 正規表現は末尾アンカー (`\s*$`・hojin byte 不変のため維持)。1 record の整形差はコスメティックとして許容 (parser 非変更) | `test_tsutatsu_multichapter.py` 統計ゲート (review flag: empty-title & body>80) |
| EDGE-007 | 削除通達 (タイトル保持型) | 削除通達には2型ある。(a) 見出しごと削除=title 空 (9-3-2 等・EDGE-001 consume-once)。(b) NTA が見出しを残置=title 有・本文空・「（…課消…により削除）」を amendment_note へ分離 (例 13-1-1 / 14-2-2)。いずれも源典に忠実 | title 有 + 本文空は **amendment_note に削除注記がある場合のみ正当** (削除でない本文ドロップは無いことを各バッチで確認)。parser 非変更 | バッチ統計ゲート (title 有 & body 空 → 削除注記の有無を確認) |
| (note) | decode サニティ | 旧チェックは hojin 固有語 (経済的/役員/退職) 依存で他章に無関係な警告を量産しうる | U+FFFD (置換文字) 検出へ一般化 (circular 非依存・出力 byte 不変) | — |

## 既知の amendment_marker 表記揺れ (Bug43 棚卸し・課消)

消費税通達の改正注記は `（…課消…により改正）` 形式。元号・全半角に揺れがあるが正規表現は
`課消` をアンカーにするため全対応 (`（[^）]*課消[^）]*）\s*$`)。確認済みサンプル:
`平9課消2－5` / `平27課消1-17` / `令５課消２－９` (全角) / `令元課消2-18` / `平31課消2-9`。

## スコープ外 (現時点で未遭遇)

- HTML `<table>` による別表/様式: 第1章・サンプリング章 (10/11/12/13/14) で 0 件。出たら
  text 隔離 (クラッシュ/汚染ゼロ) を確認し本台帳に追記。

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
| EDGE-008 | 章・節レベルの「の」枝番 (法人税) | 法人税基本通達は「章の枝番」(第12章の2..の7=`12の2-1-1`・第13章の2=`13の2-1-1`) と節枝番 (第1章第3節の2=`1-3の2-1`) を持ち、番号の**章/節レベル**に「の」が付く。旧文法 `\d+-\d+-\d+(のN)*` は項レベルしか「の」を許さず章/節枝番を 100% 取りこぼす | 3 レベル各々に「の」枝番を許す共通 `_LEVEL=\d+(?:の\d+)*` へ一般化 (番号検出・先頭番号・id 形式ゲート)。多章ディレクトリフィルタも `_N`/`a` 接尾辞 (12_2..12_7・13_2・20a) を章として許可。既存コーパスは byte 不変 (上位互換) | `test_tsutatsu_multichapter.py::test_chapter_level_no_branch_number` / `::test_branch_chapter_numeric_sort` / `::test_chapter_filter_includes_branch_dirs_excludes_preamble` / `::test_directive_id_format_gate_accepts_chapter_branch` |
| EDGE-009 | 平文番号 (CASE C・strong 無し) | 旧い節 (第1章第8節=`1-8-1`・第3節の2=`1-3の2-1`) は番号が `<strong>` でマークアップされず段落先頭の平文にある。strong 必須の旧実装では 0 directive で silent-empty 通過 (空抽出 dry-run で検知) | 先頭番号検出 (`_LEADING_DIRECTIVE_RE`) を strong ブロックの外へ出し、strong 不在でも段落先頭番号を拾う。番号で始まらない段落 (indent 本文・「(1)…」) は非該当のため既存コーパス byte 不変 | `test_tsutatsu_multichapter.py::test_case_c_plain_number_without_strong` |
| EDGE-010 | NTA 原典の閉じ括弧欠落 title | 一部の長い h2 見出しは NTA 原典自体が閉じ括弧「）」を欠く (例 2-3-4の2「（対象配当等の額が…の計算」)。源典に忠実=パーサは補完しない | title は h2 を verbatim 取得 (改変禁止・docs §4.1)。欠落は NTA 側の表記であり parser 非変更 | corpus 再現ゲート (`::test_hojin_corpus_reproduces_from_its_chapter_dirs`) + バッチスポット |
| EDGE-011 | 改正記号「直法」(法人税 旧称) | 法人税は 2001 年 (平成13年) の組織改編で部門記号が「直法」→「課法」に改称。旧章の末尾注記「（昭55年直法2-8「七」により改正）」は課法のみだと amendment_note へ分離されず本文に残る | `amendment_markers` を tuple 化し hojin=`(課法, 直法)` の alternation で末尾注記を抽出。**9-2 sentinel は末尾 直法 ゼロ=byte 不変** (差分0 を回帰ゲートで実証) | `test_tsutatsu_multichapter.py::test_chokuhou_trailing_amendment_extracted` / `test_tsutatsu_byte_regression.py` (9-2 sentinel スライス) |
| (note) | decode サニティ | 旧チェックは hojin 固有語 (経済的/役員/退職) 依存で他章に無関係な警告を量産しうる | U+FFFD (置換文字) 検出へ一般化 (circular 非依存・出力 byte 不変) | — |

## 既知の amendment_marker 表記揺れ (Bug43 棚卸し・課消 / 課法・直法)

- **消費税** (`課消`): `（…課消…により改正）` 形式。元号・全半角に揺れがあるが正規表現は
  `課消` をアンカーにするため全対応 (`（[^）]*課消[^）]*）\s*$`)。確認済みサンプル:
  `平9課消2－5` / `平27課消1-17` / `令５課消２－９` (全角) / `令元課消2-18` / `平31課消2-9`。
- **法人税** (`課法`+`直法`): 現行記号 `課法` (例 `平19年課法2-3`) に加え、2001 年改編前の旧称
  `直法` (例 `昭55年直法2-8`) を併用 (EDGE-011)。正規表現は `(?:課法|直法)` の alternation。
  **本文途中 (末尾でない) の改正注記の抽出はスコープ外** (下記参照)。

## スコープ外 (現時点で未対応・要再ロック判断)

- **本文途中 (末尾でない) の改正注記**: 一部の通達は注記が定義文と列挙項目の間に入る
  (例 9-2-9「…をいう。（平19年課法2-3「二十二」により追加…）(1) 役員等…」)。末尾アンカー
  (`\s*$`) のため現状は本文に残る。中間抽出は **9-2 sentinel の 11/35 を変更する** (= locked
  baseline の差分≠0) ため、再ロックの明示承認が無い限り保留。インライン引用との誤抽出リスクもあり。
- HTML `<table>` による別表/様式: 第1章・サンプリング章で 0 件 (法人税全 25 章でも 0 件)。出たら
  text 隔離 (クラッシュ/汚染ゼロ) を確認し本台帳に追記。

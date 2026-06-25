"""test_tsutatsu_multichapter.py -- 多章マージ orchestration のゲート (FU-519 keystone).

Why this test exists:
    消費税法基本通達は全21章で、retrieval は 1 通達 = 1 統合 JSONL を期待する
    (parse-nta-taxanswer.py:_load_tsutatsu_corpus)。parse-nta-tsutatsu.py の
    --cache-root モードは、章ディレクトリ root を rglob し、各ファイルの相対パスから
    source_url を再構築 (目 4 階層 09/01/01.htm を保持) し、全体を数値キーで並べ替えて
    1 ファイルへマージする。本テストは合成 cp932 fixture (ネットワーク不要・CI-safe) で
    その orchestration の不変条件を pin する:
      - 章跨ぎ数値ソート (査読 5b): "2-x-x" < "10-x-x"・"1-1-9" < "1-1-10"
        (naive 文字列ソートなら "10" < "2" で破綻するのを機械的に落とす)。
      - 目サブパスの source_url 保持 (09/01/01.htm -> .../09/01/01.htm)。
      - 複数章のマージ件数。
      - 章跨ぎ directive_id 重複の fail-loud。
      - 前文 (root 直下 .htm) / 旧版アーカイブ (8 桁ディレクトリ) の除外。
      - directive_id 形式ゲート (_directive_id_ok)。

    **落ちたら直すのはパーサであって期待値ではない**。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CH1_BASELINE = _THIS.parent / "fixtures" / "shouhi-kihon-tsutatsu.tsutatsu.chunks.baseline.jsonl"
# 累積コーパス fixture (全章マージのスナップショット・バッチ毎に更新)。
_CORPUS_BASELINE = _THIS.parent / "fixtures" / "shouhi-kihon-tsutatsu.corpus.chunks.baseline.jsonl"
_SHOHI_CACHE = _REPO_ROOT / "cache" / "tsutatsu" / "shohi"


def _import_parser():
    spec = importlib.util.spec_from_file_location("parse_nta_tsutatsu", _PARSER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass + future annotations need module registered
    spec.loader.exec_module(mod)
    return mod


_PAGE_TMPL = """<html><head><meta charset="shift_jis"></head><body>
<div id="bodyArea">
<h1>節見出し</h1>
{items}
</div></body></html>"""

_ITEM_TMPL = "<h2>{title}</h2>\n<p><strong>{num}</strong>　{body}</p>"


def _page(*items: tuple[str, str, str]) -> bytes:
    """items: (num, title, body) -> cp932 NTA-like HTML bytes."""
    body = "\n".join(_ITEM_TMPL.format(num=n, title=t, body=b) for n, t, b in items)
    return _PAGE_TMPL.format(items=body).encode("cp932")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _run(mod, cache_root: Path, out_dir: Path) -> tuple[int, list[dict]]:
    rc = mod.main(
        [
            "--circular",
            "shouhi",
            "--cache-root",
            str(cache_root),
            "--output-dir",
            str(out_dir),
        ]
    )
    out = out_dir / "shouhi-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


# ===========================================================
# pure-function units
# ===========================================================


def test_build_source_url_preserves_moku_subpath() -> None:
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["shouhi"]
    assert (
        mod._build_source_url(cfg, Path("09") / "01" / "01.htm")
        == "https://www.nta.go.jp/law/tsutatsu/kihon/shohi/09/01/01.htm"
    )
    # backslashes never leak into the URL (as_posix)
    assert "\\" not in mod._build_source_url(cfg, Path("12") / "01" / "03.htm")


def test_directive_id_format_gate() -> None:
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["shouhi"]
    ok = mod._directive_id_ok
    assert ok("shouhi-kihon-tsutatsu-1-1-1", cfg)
    assert ok("shouhi-kihon-tsutatsu-12-1-3", cfg)
    assert ok("shouhi-kihon-tsutatsu-9-2-12の2の3", cfg)
    assert not ok("shouhi-kihon-tsutatsu-1-1", cfg)  # 節欠落
    assert not ok("hojin-kihon-tsutatsu-1-1-1", cfg)  # 通達 prefix 不一致
    assert not ok("shouhi-kihon-tsutatsu-", cfg)


# ===========================================================
# orchestration (synthetic cp932 cache)
# ===========================================================


def test_cross_chapter_numeric_sort(tmp_path: Path) -> None:
    """査読 5b: 章プレフィックスは数値順 ("2-x-x" < "10-x-x"), 文字列順 ("10"<"2") を落とす."""
    mod = _import_parser()
    root = tmp_path / "shohi"
    _write(root / "02" / "01.htm", _page(("2-1-1", "（甲）", "本文甲。")))
    _write(root / "10" / "01.htm", _page(("10-1-1", "（乙）", "本文乙。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    nums = [r["directive_number"] for r in recs]
    assert nums == ["2-1-1", "10-1-1"], f"章跨ぎ数値順が崩れた: {nums}"


def test_within_section_numeric_sort(tmp_path: Path) -> None:
    """ "1-1-9" < "1-1-10" (項番号も数値順)."""
    mod = _import_parser()
    root = tmp_path / "shohi"
    _write(
        root / "01" / "01.htm",
        _page(
            ("1-1-10", "（十）", "本文十。"),
            ("1-1-9", "（九）", "本文九。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["1-1-9", "1-1-10"]


def test_moku_subpath_source_url_end_to_end(tmp_path: Path) -> None:
    mod = _import_parser()
    root = tmp_path / "shohi"
    _write(root / "09" / "01" / "01.htm", _page(("9-1-1", "（目)", "目本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["source_url"].endswith("/09/01/01.htm")


def test_multichapter_merge_and_count(tmp_path: Path) -> None:
    mod = _import_parser()
    root = tmp_path / "shohi"
    _write(root / "02" / "01.htm", _page(("2-1-1", "（a）", "A。"), ("2-1-2", "（b）", "B。")))
    _write(root / "03" / "01.htm", _page(("3-1-1", "（c）", "C。")))
    _write(root / "09" / "01" / "01.htm", _page(("9-1-1", "（d）", "D。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["2-1-1", "2-1-2", "3-1-1", "9-1-1"]


def test_duplicate_directive_id_fail_loud(tmp_path: Path) -> None:
    mod = _import_parser()
    root = tmp_path / "shohi"
    _write(root / "02" / "01.htm", _page(("2-1-1", "（a）", "A。")))
    _write(root / "02" / "02.htm", _page(("2-1-1", "（dup）", "重複。")))
    rc, _ = _run(mod, root, tmp_path / "out")
    assert rc == 1, "章内 directive_id 重複は fail-loud (rc=1) であるべき"


def test_excludes_preamble_and_archive(tmp_path: Path) -> None:
    """root 直下 .htm (前文) と 8 桁ディレクトリ (旧版アーカイブ) を除外する."""
    mod = _import_parser()
    root = tmp_path / "shohi"
    _write(root / "02.htm", _page(("2-9-9", "（前文)", "前文扱い。")))  # root 直下 -> 除外
    _write(root / "20230930" / "01.htm", _page(("2-1-1", "（旧)", "旧版。")))  # 8桁 -> 除外
    _write(root / "03" / "01.htm", _page(("3-1-1", "（実)", "実章。")))  # 採用
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["3-1-1"], (
        f"前文/アーカイブが混入: {[r['directive_number'] for r in recs]}"
    )


# ===========================================================
# 法人税の章の枝番 (第12章の2 = 12の2-1-1) + 章ディレクトリ拡張 (FU-521)
# ===========================================================
#
# 法人税基本通達は「章の枝番」(12_2..12_7 = 第12章の2..の7・13_2・20a) を持ち、
# 番号は **章レベルに「の」** が付く ("12の2-1-1")。消費税通達・法人税 9-2 は項レベル
# だけ ("9-2-12の2")。本セクションは合成 cp932 fixture でこの新形式を pin する。


def _run_hojin(mod, cache_root: Path, out_dir: Path) -> tuple[int, list[dict]]:
    rc = mod.main(
        ["--circular", "hojin", "--cache-root", str(cache_root), "--output-dir", str(out_dir)]
    )
    out = out_dir / "hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


_RAW_PAGE = (
    '<html><head><meta charset="shift_jis"></head><body><div id="bodyArea">\n{inner}\n'
    "</div></body></html>"
)


def test_text_excluding_nested_blocks_fastpath_and_strip() -> None:
    """入れ子ブロック除外ヘルパ: 入れ子なし=get_text 同一 / 入れ子あり=ブロック除外."""
    mod = _import_parser()
    from bs4 import BeautifulSoup

    # fast path: 入れ子ブロックなし -> get_text と完全一致 (byte 不変の核)。
    soup = BeautifulSoup("<p>甲<strong>乙</strong>丙</p>", "html.parser")
    p = soup.find("p")
    assert mod._text_excluding_nested_blocks(p) == p.get_text()
    # strip path: 入れ子 <p>/<table> のテキストは除外し自段落のテキストのみ。
    soup2 = BeautifulSoup(
        "<div><p>own<p>nested</p><table><tr><td>cell</td></tr></table></p></div>", "html.parser"
    )
    outer = soup2.find("p")
    txt = mod._text_excluding_nested_blocks(outer)
    assert "own" in txt and "nested" not in txt and "cell" not in txt


def test_table_captured_as_plaintext_body(tmp_path: Path) -> None:
    """別表 <table> を現在の項のプレーンテキスト本文として取り込む (Bug55・本文非空)."""
    mod = _import_parser()
    root = tmp_path / "hojin"
    inner = (
        "<h2>（表のある通達）</h2>\n"
        '<p class="indent1"><strong>9-3-5の2　</strong>本文。</p>\n'
        "<table><tr><td>資産計上期間</td><td>資産計上額</td></tr>"
        "<tr><td>10年</td><td>当期分の100分の40</td></tr></table>\n"
        "<h2>（次の通達）</h2>\n"
        '<p class="indent1"><strong>9-3-6　</strong>次の本文。</p>'
    )
    _write(root / "09" / "09_03.htm", _RAW_PAGE.format(inner=inner).encode("cp932"))
    rc, recs = _run_hojin(mod, root, tmp_path / "out")
    assert rc == 0
    by = {r["directive_number"]: r for r in recs}
    # 表は表の直前の項 (9-3-5の2) に取り込まれ、非空。
    assert "資産計上額" in by["9-3-5の2"]["text"]
    assert "当期分の100分の40" in by["9-3-5の2"]["text"]
    # 表をまたいでも次項は自分の見出しを失わない。
    assert by["9-3-6"]["title"] == "（次の通達）"


def test_case_a_guard_rejects_nested_strong_number(tmp_path: Path) -> None:
    """CASE-A ガード: 番号 <strong> が段落先頭でない (本文中の参照) なら項開始扱いしない.

    malformed HTML で body 段落が後続通達を吸い込むと find('strong') が入れ子の番号を
    拾い、本文段落を誤って項開始扱いして見出し脱落+重複を招く。番号が段落先頭にないとき
    却下することで、真の通達だけが項になる (重複 fail-loud も回避)。
    """
    mod = _import_parser()
    root = tmp_path / "hojin"
    inner = (
        "<h2>（甲）</h2>\n"
        '<p class="indent1"><strong>9-3-5　</strong>リード甲。</p>\n'
        '<p class="indent2">(1)　本文中に<strong>9-3-6</strong>への参照を含む段落。</p>\n'
        "<h2>（乙）</h2>\n"
        '<p class="indent1"><strong>9-3-6　</strong>本文乙。</p>'
    )
    _write(root / "09" / "09_03.htm", _RAW_PAGE.format(inner=inner).encode("cp932"))
    rc, recs = _run_hojin(mod, root, tmp_path / "out")
    assert rc == 0, "入れ子 strong を誤検出すると 9-3-6 重複で fail-loud (rc=1) になる"
    by = {r["directive_number"]: r for r in recs}
    assert list(by) == ["9-3-5", "9-3-6"], f"想定外の項: {list(by)}"
    # (1) 段落は 9-3-5 の本文に取り込まれる (項開始でない)。
    assert "への参照を含む段落" in by["9-3-5"]["text"]
    # 真の 9-3-6 は自分の見出しを保持。
    assert by["9-3-6"]["title"] == "（乙）"
    assert by["9-3-6"]["text"] == "本文乙。"


def test_chapter_filter_includes_branch_dirs_excludes_preamble() -> None:
    """章ディレクトリフィルタ: 12_2 / 20a を採用, zenbun / fusoku / アーカイブを除外."""
    mod = _import_parser()
    ok = mod._CHAPTER_DIR_RE.fullmatch
    for d in ("01", "09", "12", "12_2", "12_7", "13_2", "20a"):
        assert ok(d), f"内容章ディレクトリ {d!r} が除外された"
    for d in ("zenbun", "fusoku", "20230930", "02.htm"):
        assert not ok(d), f"非内容パス {d!r} が混入した"


def test_chapter_level_no_branch_number(tmp_path: Path) -> None:
    """第12章の2 の番号 "12の2-1-1" が章レベルの「の」付きで正しく抽出される."""
    mod = _import_parser()
    root = tmp_path / "hojin"
    _write(root / "12_2" / "12_2_01.htm", _page(("12の2-1-1", "（通則）", "本文。")))
    rc, recs = _run_hojin(mod, root, tmp_path / "out")
    assert rc == 0, "章レベルの「の」付き番号が parse 失敗"
    assert len(recs) == 1
    assert recs[0]["directive_number"] == "12の2-1-1"
    assert recs[0]["directive_id"] == "hojin-kihon-tsutatsu-12の2-1-1"
    assert recs[0]["source_url"].endswith("/12_2/12_2_01.htm")


def test_branch_chapter_numeric_sort(tmp_path: Path) -> None:
    """章枝番の数値順: 12-1-9 < 12の2-1-1 < 12の7-3-4 < 13-1-1 (章レベルの数値順)."""
    mod = _import_parser()
    root = tmp_path / "hojin"
    _write(root / "12" / "12_01.htm", _page(("12-1-9", "（a）", "A。")))
    _write(root / "12_2" / "12_2_01.htm", _page(("12の2-1-1", "（b）", "B。")))
    _write(root / "12_7" / "12_7_03.htm", _page(("12の7-3-4", "（c）", "C。")))
    _write(root / "13" / "13_01.htm", _page(("13-1-1", "（d）", "D。")))
    rc, recs = _run_hojin(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == [
        "12-1-9",
        "12の2-1-1",
        "12の7-3-4",
        "13-1-1",
    ], f"章枝番の数値順が崩れた: {[r['directive_number'] for r in recs]}"


_ITEM_PLAIN_TMPL = "<h2>{title}</h2>\n<p>{num}　{body}</p>"  # CASE C: 番号が strong 無しの平文


def _page_plain(*items: tuple[str, str, str]) -> bytes:
    """CASE C 用: 番号を <strong> で囲まず段落先頭の平文に置く NTA-like cp932 HTML."""
    body = "\n".join(_ITEM_PLAIN_TMPL.format(num=n, title=t, body=b) for n, t, b in items)
    return _PAGE_TMPL.format(items=body).encode("cp932")


def test_case_c_plain_number_without_strong(tmp_path: Path) -> None:
    """CASE C: 番号が <strong> 無しの平文先頭にある古い節 (1-3の2-1 / 1-8-1) を抽出する.

    法人税 第1章第3節の2 (1-3の2-1) / 第8節 (1-8-1) は番号が strong でマークアップ
    されず段落先頭の平文にある。strong 必須だと 0 directive で silent-empty 通過する
    (P0-4 dry-run で検知) ため、strong 不在でも段落先頭番号を拾う。
    """
    mod = _import_parser()
    root = tmp_path / "hojin"
    _write(root / "01" / "01_08.htm", _page_plain(("1-8-1", "（その他）", "本文八。")))
    _write(root / "01" / "01_03_02.htm", _page_plain(("1-3の2-1", "（支配関係）", "本文三の二。")))
    rc, recs = _run_hojin(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["1-3の2-1", "1-8-1"]
    # 本文は番号自身を含まない (番号は consume される)。
    assert recs[0]["text"].startswith("本文三の二")
    assert recs[1]["text"].startswith("本文八")


def test_chokuhou_trailing_amendment_extracted(tmp_path: Path) -> None:
    """旧称「直法」の末尾改正注記を amendment_note に分離する (課法 と併用).

    法人税基本通達は 2001 年 (平成13年) の組織改編で「直法」→「課法」に改称した。
    旧章は末尾注記が「（昭55年直法2-8「七」により改正）」のように直法で書かれており、
    課法のみだと取りこぼす。9-2 sentinel は末尾 直法 ゼロのため byte 不変 (回帰ゲートで実証)。
    """
    mod = _import_parser()
    root = tmp_path / "hojin"
    _write(
        root / "02" / "02_02.htm",
        _page(
            ("2-2-1", "（甲）", "本文甲。（昭55年直法2-8「七」により改正）"),
            ("2-2-2", "（乙）", "本文乙。（平19年課法2-3「二十二」により追加）"),
        ),
    )
    rc, recs = _run_hojin(mod, root, tmp_path / "out")
    assert rc == 0
    by = {r["directive_number"]: r for r in recs}
    assert by["2-2-1"]["amendment_note"] == "（昭55年直法2-8「七」により改正）"
    assert by["2-2-1"]["text"] == "本文甲。"
    # 課法 (現行記号) も従来どおり分離されることを確認 (回帰)。
    assert by["2-2-2"]["amendment_note"] == "（平19年課法2-3「二十二」により追加）"
    assert by["2-2-2"]["text"] == "本文乙。"


def test_directive_id_format_gate_accepts_chapter_branch() -> None:
    """形式ゲートが章レベルの「の」を受理する (12の2-1-1) / 崩れた番号は拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["hojin"]
    ok = mod._directive_id_ok
    assert ok("hojin-kihon-tsutatsu-12の2-1-1", cfg)  # 章レベルの「の」
    assert ok("hojin-kihon-tsutatsu-1-3の2-1", cfg)  # 節レベルの「の」(第1章第3節の2)
    assert ok("hojin-kihon-tsutatsu-9-2-12の2の3", cfg)  # 項レベルの「の」
    assert ok("hojin-kihon-tsutatsu-20-4-1", cfg)
    assert not ok("hojin-kihon-tsutatsu-12の2-1", cfg)  # 項欠落
    assert not ok("shouhi-kihon-tsutatsu-1-1-1", cfg)  # 通達 prefix 不一致


# ===========================================================
# byte regression: multi-chapter over the real cache (local only)
# ===========================================================


@pytest.mark.skipif(
    not _SHOHI_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/shohi/, gitignored) 不在 -- push 前ローカル",
)
def test_multichapter_over_real_cache_matches_committed_corpus(tmp_path: Path) -> None:
    """--cache-root で実キャッシュをマージした出力が committed corpus fixture と byte 一致.

    キャッシュ (gitignored) はバッチ毎に章が増え、corpus fixture も同時に更新される。
    両者が同一 commit で byte 一致することで、parser の決定性とコーパスの完全性を pin する。
    **落ちたら直すのはパーサ/キャッシュであって corpus fixture ではない**。
    """
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        [
            "--circular",
            "shouhi",
            "--cache-root",
            str(_SHOHI_CACHE),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    produced = out_dir / "shouhi-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists()
    # nesting/別表 修正 (EDGE-012) は消費税 8-1-5の2 の latent な吸い込みバグ
    # (8-1-6/8-1-7 を本文に重複) も是正する。8-1-5の2 の正しい姿への re-lock は別の
    # shohi-corpus 修正 PR で行うため、本 PR では当該 1 行を strict byte 比較から除外し、
    # 残り 660 行が byte 不変であることを確認する。re-lock PR で全行 strict に戻す。
    _RELOCK_PENDING = "shouhi-kihon-tsutatsu-8-1-5の2"
    prod_lines = [
        line for line in produced.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    base_lines = [
        line for line in _CORPUS_BASELINE.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(prod_lines) == len(base_lines), "corpus 行数が変化"
    diffs = [
        i
        for i, (p, b) in enumerate(zip(prod_lines, base_lines))
        if p != b and _RELOCK_PENDING not in p
    ]
    assert not diffs, (
        "8-1-5の2 以外の行が byte 不一致 (整形済みページは不変のはず): "
        f"{[json.loads(prod_lines[i])['directive_id'] for i in diffs[:5]]}"
    )


def test_corpus_fixture_ch1_prefix_matches_sentinel() -> None:
    """corpus fixture の第1章部分が ch1 sentinel fixture と byte 一致 (ch1 不変の番人)."""
    corpus = _CORPUS_BASELINE.read_bytes().splitlines(keepends=True)
    ch1 = _CH1_BASELINE.read_bytes().splitlines(keepends=True)
    assert corpus[: len(ch1)] == ch1, "corpus 先頭の第1章が sentinel と不一致 (ch1 が変化した)"


def _numeric_key(num: str) -> tuple:
    """parser の _sort_key と同等の数値タプルキー (テスト独立コピー)."""
    parts: list[int] = []
    for seg in num.split("-"):
        for sub in re.split("の", seg):
            parts.append(int(sub) if sub.isdigit() else 0)
    while len(parts) < 6:
        parts.append(0)
    return tuple(parts)


def test_corpus_fixture_globally_numeric_sorted_and_unique() -> None:
    """corpus fixture が数値キーで全体ソート済 + directive_id ユニーク (査読 5b・章跨ぎ)."""
    recs = [
        json.loads(line)
        for line in _CORPUS_BASELINE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    keys = [_numeric_key(r["directive_number"]) for r in recs]
    assert keys == sorted(keys), "corpus が数値順に並んでいない"
    ids = [r["directive_id"] for r in recs]
    assert len(ids) == len(set(ids)), "corpus に directive_id 重複"
    # 章プレフィックスは数値昇順 ("10" が "2" より後)。
    chapters = [int(r["directive_number"].split("-")[0]) for r in recs]
    assert chapters == sorted(chapters), "章プレフィックスが数値昇順でない"


# ===========================================================
# 法人税 corpus fixture gates (FU-521 batches)
# ===========================================================

_HOJIN_CACHE = _REPO_ROOT / "cache" / "tsutatsu" / "hojin"
_HOJIN_CORPUS = _THIS.parent / "fixtures" / "hojin-kihon-tsutatsu.corpus.chunks.baseline.jsonl"
_HOJIN_SENTINEL = _THIS.parent / "fixtures" / "hojin-kihon-tsutatsu.tsutatsu.chunks.baseline.jsonl"


def _hojin_corpus_records() -> list[dict]:
    return [
        json.loads(line)
        for line in _HOJIN_CORPUS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_hojin_corpus_globally_numeric_sorted_and_unique() -> None:
    """法人税 corpus fixture が数値キーで全体ソート済 + directive_id ユニーク (章枝番含む)."""
    recs = _hojin_corpus_records()
    keys = [_numeric_key(r["directive_number"]) for r in recs]
    assert keys == sorted(keys), "corpus が数値順に並んでいない"
    ids = [r["directive_id"] for r in recs]
    assert len(ids) == len(set(ids)), "corpus に directive_id 重複"


def test_hojin_corpus_92_sentinel_slice_when_present() -> None:
    """9-2 の 35 sentinel が corpus に揃ったら baseline と byte 一致 (exact-id スライス・Bug53)."""
    base = _HOJIN_SENTINEL.read_bytes().splitlines()
    base_ids = [json.loads(b)["directive_id"] for b in base]
    by_id = {json.loads(b)["directive_id"]: b for b in _HOJIN_CORPUS.read_bytes().splitlines()}
    if not all(i in by_id for i in base_ids):
        pytest.skip("ch09 (9-2) はまだ corpus に未収録")
    assert [by_id[i] for i in base_ids] == base, (
        "9-2 sentinel スライスが baseline と byte 不一致 (直すのはパーサであって baseline ではない)"
    )


@pytest.mark.skipif(
    not _HOJIN_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/hojin/, gitignored) 不在 -- push 前ローカル",
)
def test_hojin_corpus_reproduces_from_its_chapter_dirs(tmp_path: Path) -> None:
    """corpus fixture が「自身が含む章ディレクトリ」を parse した出力と byte 一致.

    fixture の source_url から章ディレクトリ集合を逆算し、その章だけを temp root に集めて
    parse → fixture と byte 一致を検証する。ローカル cache が fixture より多くの章を持って
    いても fixture の章だけで再現性を確認でき、バッチ毎の決定性を pin する。
    **落ちたら直すのはパーサ/キャッシュであって fixture ではない**。
    """
    import shutil

    recs = _hojin_corpus_records()
    dirs = sorted({r["source_url"].split("/kihon/hojin/", 1)[1].split("/", 1)[0] for r in recs})
    root = tmp_path / "cache"
    root.mkdir()
    for d in dirs:
        src = _HOJIN_CACHE / d
        if not src.exists():
            pytest.skip(f"cache dir {d} 不在")
        shutil.copytree(src, root / d)
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(["--circular", "hojin", "--cache-root", str(root), "--output-dir", str(out_dir)])
    assert rc == 0
    produced = out_dir / "hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.read_bytes() == _HOJIN_CORPUS.read_bytes(), (
        "corpus fixture が自身の章 parse 出力と byte 不一致 (cache 更新時は fixture も再生成)"
    )

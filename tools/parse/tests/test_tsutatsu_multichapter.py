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
    assert produced.read_bytes() == _CORPUS_BASELINE.read_bytes(), (
        "実キャッシュのマージ出力が corpus fixture と byte 不一致 "
        "(キャッシュ更新時は fixture も再生成して同一 commit に含める)"
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

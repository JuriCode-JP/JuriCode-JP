"""test_souzoku_corpus.py -- 相続税法基本通達 corpus fixture のゲート (FU-524 Phase 1).

Why this test exists:
    相続税基本通達の committed 実体は build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/souzoku-kihon-tsutatsu.corpus.chunks.baseline.jsonl`
    (hojin/shohi/shotoku と同じ場所・同じ規約)。本テストは確定値 (全 445 件・
    directive_id ユニーク・全体数値ソート済・range 記号正規化済・33 source file を網羅
    = 34 htm 中 fusoku/01.htm 附則のみ通達ゼロ) を fixture に対して pin し、さらに
    cache がある push 前ローカルでは parser が fixture を **byte 再現** することを検証する。

    参照リンクの回帰も pin する: config 駆動 ref 正規表現 (_build_law_ref_re) により
    「措置法第N条」が相続税法 (souzoku-zei-hou) へ **偽リンクしない** こと、通則法が
    kokuzei-tsuusoku-hou へリンクすることを固定 (FU-524 の中核修正)。

    **落ちたら直すのはパーサ/キャッシュであって fixture ではない** (source-locked)。
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
_FIXTURE = _THIS.parent / "fixtures" / "souzoku-kihon-tsutatsu.corpus.chunks.baseline.jsonl"
_SOUZOKU_CACHE = _REPO_ROOT / "cache" / "tsutatsu" / "souzoku"

# LOCKED 確定値 (実パーサ dry-run + 完全性監査で確定・改変は user 明示承認が必須)。
EXPECTED_TOTAL = 445  # dedup 後のユニーク通達数 (num_levels=2, 条-番号)
EXPECTED_SOURCE_FILES = 33  # 通達を持つ source htm 数 (= 34 htm 中 fusoku/01.htm 附則を除く)
EXPECTED_CACHE_HTM = 34  # NTA から取得した htm 総数 (fusoku 附則含む)


def _records() -> list[dict]:
    return [
        json.loads(line)
        for line in _FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _numeric_key(num: str) -> tuple:
    """parser の _sort_key と同等の数値タプルキー (テスト独立コピー)."""
    parts: list[int] = []
    for seg in num.split("-"):
        for sub in re.split("の", seg):
            if sub.isdigit():
                parts.append(int(sub))
            else:
                m = re.match(r"\d+", sub)
                parts.append(int(m.group()) if m else 0)
    while len(parts) < 6:
        parts.append(0)
    return tuple(parts)


def _import_parser():
    spec = importlib.util.spec_from_file_location("parse_nta_tsutatsu", _PARSER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ===========================================================
# fixture 不変条件 (CI-safe: committed fixture のみ参照)
# ===========================================================


def test_fixture_exists() -> None:
    assert _FIXTURE.exists(), f"corpus fixture 不在: {_FIXTURE}"


def test_chunk_count_locked() -> None:
    assert len(_records()) == EXPECTED_TOTAL


def test_directive_id_unique() -> None:
    ids = [r["directive_id"] for r in _records()]
    assert len(ids) == len(set(ids)), "directive_id に重複 (dedup 漏れ)"


def test_id_equals_directive_id() -> None:
    """配管フィールド id と directive_id が一致 (retrieve.py 互換)."""
    for r in _records():
        assert r["id"] == r["directive_id"]


def test_globally_numeric_sorted() -> None:
    """corpus が数値キーで全体ソート済."""
    keys = [_numeric_key(r["directive_number"]) for r in _records()]
    assert keys == sorted(keys), "corpus が数値順に並んでいない"


def test_no_raw_range_separators() -> None:
    """directive_number に生の中点/波ダッシュが残らない (全て "_" 正規化済)."""
    for r in _records():
        num = r["directive_number"]
        assert not any(c in num for c in "・〜～~"), f"生の範囲記号が残存: {num!r}"


def test_all_source_urls_under_sozoku2() -> None:
    """全 source_url が NTA sisan/sozoku2 パスを指す (URL 一次確認済)."""
    for r in _records():
        assert "/law/tsutatsu/kihon/sisan/sozoku2/" in r["source_url"], r["source_url"]


def test_source_file_coverage() -> None:
    """通達は 33 source htm に分布 (34 htm 中 fusoku/01.htm 附則のみ通達ゼロ = 完全性)."""
    files = {r["source_url"].rsplit("/sozoku2/", 1)[-1] for r in _records()}
    assert len(files) == EXPECTED_SOURCE_FILES, f"source file 数: {len(files)}"
    assert not any("fusoku" in f for f in files), "附則に通達が混入 (想定は通達ゼロ)"


def test_all_directive_ids_well_formed() -> None:
    """全 directive_id が souzoku 2 レベル形式ゲートを通る (壊れ番号ゼロ)."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["souzoku"]
    for r in _records():
        assert mod._directive_id_ok(r["directive_id"], cfg), f"形式違反: {r['directive_id']!r}"


def test_sochi_hou_not_false_linked() -> None:
    """措置法参照が相続税法 (souzoku-zei-hou) へ偽リンクしない (FU-524 中核修正)."""
    false_links = [
        r["directive_number"]
        for r in _records()
        for ra in r.get("related_articles", [])
        if ra.get("raw", "").startswith("措置法") and ra.get("law_abbrev") == "souzoku-zei-hou"
    ]
    assert false_links == [], f"措置法->相続税法 の偽リンク: {false_links[:5]}"


def test_tsuusoku_hou_linked() -> None:
    """通則法参照が kokuzei-tsuusoku-hou へ解決 (corpus 実在 -> link)."""
    linked = [
        ra
        for r in _records()
        for ra in r.get("related_articles", [])
        if ra.get("raw", "").startswith("通則法")
    ]
    assert linked, "通則法参照が 1 件も抽出されていない"
    assert all(ra.get("law_abbrev") == "kokuzei-tsuusoku-hou" for ra in linked)
    assert all(ra.get("article_id") for ra in linked), "通則法が unlinked (corpus 実在のはず)"


# ===========================================================
# byte 再現 + セクション数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _SOUZOKU_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/souzoku/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_cache_htm_count() -> None:
    """取得済 htm が 34 (NTA 目次の増減検知)."""
    htm = list(_SOUZOKU_CACHE.rglob("*.htm"))
    assert len(htm) == EXPECTED_CACHE_HTM, f"htm 数が {EXPECTED_CACHE_HTM} でない: {len(htm)}"


@pytest.mark.skipif(
    not _SOUZOKU_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/souzoku/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を **byte 再現** する (決定性 + 完全性)."""
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        ["--circular", "souzoku", "--cache-root", str(_SOUZOKU_CACHE), "--output-dir", str(out_dir)]
    )
    assert rc == 0
    produced = out_dir / "souzoku-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュのマージ出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

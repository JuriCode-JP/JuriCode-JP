"""test_hyoka_corpus.py -- 財産評価基本通達 corpus fixture のゲート (FU-525).

Why this test exists:
    財産評価基本通達の committed 実体は build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/zaisan-hyoka-kihon-tsutatsu.corpus.chunks.baseline.jsonl`
    (hojin/shohi/shotoku/souzoku と同じ場所・同じ規約)。本テストは確定値 (全 313 件・
    base 番号 1..215 完全・directive_id ユニーク・全体数値ソート済・削除 54 件・35 source
    file を網羅 = 37 htm 中 02/07 附表・08/09 別表のみ通達ゼロ) を fixture に対して pin し、
    さらに cache がある push 前ローカルでは parser が fixture を **byte 再現** することを検証する。

    財産評価通達は他の 4 通達と番号体系が異なる (num_style="flat_branch": 章跨ぎの単発通し
    番号 1..215 + 任意の単一ダッシュ枝番 "4-2")。番号が <strong> 内にある段落のみ通達とみなし、
    (注) 注記・別表の平文番号を弾く。本テストは split-strong <strong>4</strong><strong>－2</strong>
    が "4" に切り詰められず "4-2" として取り込まれること (回帰の中核) を pin する。

    参照リンクの回帰も pin する: ref_map は **完全名のみ** ("相続税法"/"所得税法"/"法人税法"/
    "地価税法") で裸 "法" を持たないため、会社法/建築基準法/都市計画法 等の named-law が
    相続税法へ **偽リンクしない** ことを固定 (FU-525 の中核修正)。

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
_FIXTURE = _THIS.parent / "fixtures" / "zaisan-hyoka-kihon-tsutatsu.corpus.chunks.baseline.jsonl"
_HYOKA_CACHE = _REPO_ROOT / "cache" / "tsutatsu" / "hyoka"

# LOCKED 確定値 (実パーサ dry-run + 完全性監査で確定・佐藤ロック 2026-07-01・改変は明示承認必須)。
EXPECTED_TOTAL = 313  # dedup 後のユニーク通達数 (flat_branch, 単発番号 + 任意枝番)
EXPECTED_BASE_MAX = 215  # base 通し番号の最大値 (1..215 が欠落なく全て存在)
EXPECTED_DELETIONS = 54  # 「削除」通達 (本文 == "削除" + 課評/直資 改正注記)
EXPECTED_SOURCE_FILES = 35  # 通達を持つ source htm 数 (= 37 htm 中 02/07 附表・08/09 別表を除く)
EXPECTED_CACHE_HTM = 37  # NTA から取得した htm 総数 (附表・別表含む)


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
    """corpus が数値キーで全体ソート済 (章跨ぎの単発通し番号ゆえ単調)."""
    keys = [_numeric_key(r["directive_number"]) for r in _records()]
    assert keys == sorted(keys), "corpus が数値順に並んでいない"


def test_base_numbers_complete_1_to_215() -> None:
    """base 通し番号 1..215 が欠落なく全て存在する (flat_branch の完全性・サイレント欠落ゼロ).

    Why: 旧モデルは num_levels=2 で ~292 件をサイレントに落としていた。単発番号の
    完全性は「1..MAX の全整数が base として出現」で機械検証する (削除も番号を保持する)。
    """
    bases = {_numeric_key(r["directive_number"])[0] for r in _records()}
    assert max(bases) == EXPECTED_BASE_MAX
    missing = [b for b in range(1, EXPECTED_BASE_MAX + 1) if b not in bases]
    assert missing == [], f"base 番号の欠落 (サイレント drop 疑い): {missing}"


def test_split_strong_branch_not_truncated() -> None:
    """split-strong <strong>4</strong><strong>－2</strong> が "4-2" として取り込まれる.

    Why: 枝番が第2 strong にあるため first-strong だけ見ると "4" に切り詰まる。番号値を
    段落先頭一致から取ることでフル番号を保持する (FU-525 の中核回帰)。4-2 の本文が枝番
    セパレータ "-2" で始まっていないことも確認する (切り詰め時の症状)。
    """
    by_num = {r["directive_number"]: r for r in _records()}
    assert "4-2" in by_num, "枝番通達 4-2 が欠落 (split-strong 切り詰めの疑い)"
    assert not by_num["4-2"]["text"].startswith("-2"), "4-2 の本文が枝番片で始まる (切り詰め)"
    # 枝番通達が複数存在する (単発番号だけでなく枝番も取れている)
    branched = [r["directive_number"] for r in _records() if "-" in r["directive_number"]]
    assert len(branched) > 50, f"枝番通達が少なすぎる (枝番検出漏れ疑い): {len(branched)}"


def test_no_raw_range_separators() -> None:
    """directive_number に生の中点/波ダッシュが残らない (全て "_" 正規化済)."""
    for r in _records():
        num = r["directive_number"]
        assert not any(c in num for c in "・〜～~"), f"生の範囲記号が残存: {num!r}"


def test_deletions_emitted() -> None:
    """「削除」通達が本文 "削除" + 改正注記付きで emit される (番号は保持・完全性)."""
    deletions = [r for r in _records() if r["text"].strip() == "削除"]
    assert len(deletions) == EXPECTED_DELETIONS, f"削除通達数: {len(deletions)}"
    # 削除通達は必ず改正注記 (課評/直資) を持つ (番号消滅の由来が追える)
    assert all(d["amendment_note"] for d in deletions), "改正注記のない削除通達がある"


def test_no_missed_amendment_notes() -> None:
    """本文末尾に 課評/直資 の未抽出改正注記が残っていない (取りこぼしゼロ)."""
    missed = [
        r["directive_number"]
        for r in _records()
        if re.search(r"（[^）]*(?:課評|直資)[^）]*）\s*$", r["text"])
    ]
    assert missed == [], f"改正注記の抽出漏れ: {missed[:5]}"


def test_all_source_urls_under_hyoka_new() -> None:
    """全 source_url が NTA sisan/hyoka_new パスを指す (URL 一次確認済)."""
    for r in _records():
        assert "/law/tsutatsu/kihon/sisan/hyoka_new/" in r["source_url"], r["source_url"]


def test_source_file_coverage() -> None:
    """通達は 35 source htm に分布 (37 htm 中 02/07 附表・08/09 別表のみ通達ゼロ = 完全性)."""
    files = {r["source_url"].rsplit("/hyoka_new/", 1)[-1] for r in _records()}
    assert len(files) == EXPECTED_SOURCE_FILES, f"source file 数: {len(files)}"
    # 附表単独ファイル (02/07.htm) と別表単独ファイル (08/09.htm) は通達を持たない
    assert "02/07.htm" not in files, "附表ファイル 02/07.htm に通達が混入"
    assert "08/09.htm" not in files, "別表ファイル 08/09.htm に通達が混入"


def test_all_directive_ids_well_formed() -> None:
    """全 directive_id が hyoka flat_branch 形式ゲートを通る (壊れ番号ゼロ)."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["hyoka"]
    for r in _records():
        assert mod._directive_id_ok(r["directive_id"], cfg), f"形式違反: {r['directive_id']!r}"


def test_named_laws_not_false_linked() -> None:
    """named-law 参照 (会社法/建築基準法/都市計画法 等) が相続税法へ偽リンクしない (FU-525 中核).

    Why: ref_map に裸 "法" を入れると trailing 法 に誤マッチし named-law を相続税法へ
    偽リンクする。完全名のみの ref_map でこれを構造的に排除したことを pin する。
    """
    false_links = [
        (r["directive_number"], ra.get("raw"))
        for r in _records()
        for ra in r.get("related_articles", [])
        if any(nm in ra.get("raw", "") for nm in ("会社法", "建築基準法", "都市計画法", "農地法"))
    ]
    assert false_links == [], f"named-law の偽リンク捕捉: {false_links[:5]}"


def test_souzoku_hou_linked() -> None:
    """相続税法参照が souzoku-zei-hou へ解決 (評価通達の主法・corpus 実在 -> link)."""
    linked = [
        ra
        for r in _records()
        for ra in r.get("related_articles", [])
        if ra.get("raw", "").startswith("相続税法")
    ]
    assert linked, "相続税法参照が 1 件も抽出されていない"
    assert all(ra.get("law_abbrev") == "souzoku-zei-hou" for ra in linked)
    assert all(ra.get("article_id") for ra in linked), "相続税法が unlinked (corpus 実在のはず)"


def test_chika_zei_hou_unlinked() -> None:
    """地価税法参照は corpus 未収録ゆえ article_id なし (unlinked) で保持される."""
    chika = [
        ra
        for r in _records()
        for ra in r.get("related_articles", [])
        if ra.get("law_abbrev") == "chika-zei-hou"
    ]
    assert chika, "地価税法参照が 1 件も抽出されていない"
    assert all("article_id" not in ra for ra in chika), "地価税法が link されている (未収録のはず)"


# ===========================================================
# byte 再現 + htm 数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _HYOKA_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/hyoka/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_cache_htm_count() -> None:
    """取得済 htm が 37 (NTA 目次の増減検知)."""
    htm = list(_HYOKA_CACHE.rglob("*.htm"))
    assert len(htm) == EXPECTED_CACHE_HTM, f"htm 数が {EXPECTED_CACHE_HTM} でない: {len(htm)}"


@pytest.mark.skipif(
    not _HYOKA_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/hyoka/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を **byte 再現** する (決定性 + 完全性)."""
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        ["--circular", "hyoka", "--cache-root", str(_HYOKA_CACHE), "--output-dir", str(out_dir)]
    )
    assert rc == 0
    produced = out_dir / "zaisan-hyoka-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュのマージ出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

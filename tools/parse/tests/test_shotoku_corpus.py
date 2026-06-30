"""test_shotoku_corpus.py -- 所得税法基本通達 corpus fixture のゲート (FU-523 data).

Why this test exists:
    所得税基本通達の committed 実体は build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/shotoku-kihon-tsutatsu.corpus.chunks.baseline.jsonl`
    (hojin/shouhi と同じ場所・同じ規約)。本テストは確定値 (全 1148 件・directive_id
    ユニーク・全体数値ソート済・条範囲 20 件・62-1/62-2 dedup) を fixture に対して pin し、
    さらに cache がある push 前ローカルでは parser が fixture を **byte 再現** することを検証する。

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
_FIXTURE = _THIS.parent / "fixtures" / "shotoku-kihon-tsutatsu.corpus.chunks.baseline.jsonl"
_SHOTOKU_CACHE = _REPO_ROOT / "cache" / "tsutatsu" / "shotoku"

# LOCKED 確定値 (P0-Phase 2 再実測 + 完全性監査 + 実キャッシュ smoke で確定・改変は user 明示承認が必須)。
EXPECTED_TOTAL = 1227  # dedup 後のユニーク通達数 (共通通達 79 件回復後)
EXPECTED_DOT_RANGE = 20  # 中点「・」条範囲 (74_75 等・非共通) の通達数
EXPECTED_KYO = 79  # 共通通達 (181_223共 / 36_37共 等・中点 or 波ダッシュ範囲 + 共) の数
EXPECTED_UNDERSCORE = 99  # directive_number に "_" を含む数 (= 20 中点範囲 + 79 共通)
EXPECTED_SECTIONS = 134  # 完全列挙した NTA セクション (htm) 数


def _records() -> list[dict]:
    return [
        json.loads(line)
        for line in _FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _numeric_key(num: str) -> tuple:
    """parser の _sort_key と同等の数値タプルキー (条範囲は先頭条番号で代表・テスト独立コピー)."""
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
    """corpus が数値キーで全体ソート済 (条範囲が先頭(0)へ潰れず物理順)."""
    keys = [_numeric_key(r["directive_number"]) for r in _records()]
    assert keys == sorted(keys), "corpus が数値順に並んでいない"


def test_no_raw_range_separators() -> None:
    """directive_number に生の中点「・」/波ダッシュが残らない (全て "_" 正規化済)."""
    recs = _records()
    for r in recs:
        num = r["directive_number"]
        assert not any(c in num for c in "・〜～~"), f"生の範囲記号が残存: {num!r}"


def test_dot_range_directives_counted() -> None:
    """非共通の中点条範囲は確定 20 件 (74_75/124_125/140_141/194_195)."""
    recs = _records()
    dot_ranges = [
        r["directive_number"]
        for r in recs
        if "_" in r["directive_number"] and "共" not in r["directive_number"]
    ]
    assert len(dot_ranges) == EXPECTED_DOT_RANGE, (
        f"中点条範囲 {EXPECTED_DOT_RANGE} 件のはず: {len(dot_ranges)}"
    )
    groups = {n.split("-")[0] for n in dot_ranges}
    assert groups == {"74_75", "124_125", "140_141", "194_195"}, f"中点条範囲群が不正: {groups}"


def test_kyotsu_directives_recovered() -> None:
    """共通通達 (共接尾) が確定 79 件回復され、波ダッシュ範囲も "_" 化されている."""
    recs = _records()
    kyo = [r["directive_number"] for r in recs if "共" in r["directive_number"]]
    assert len(kyo) == EXPECTED_KYO, f"共通通達 {EXPECTED_KYO} 件のはず: {len(kyo)}"
    # 共通通達はすべて範囲 ("_" を含む・例 181_223共-1 / 36_37共-1)。
    assert all("_" in n for n in kyo), "共通通達に範囲正規化漏れ"
    underscore = [r["directive_number"] for r in recs if "_" in r["directive_number"]]
    assert len(underscore) == EXPECTED_UNDERSCORE, (
        f'"_" 含む通達は {EXPECTED_UNDERSCORE} 件 (20 中点 + 79 共通): {len(underscore)}'
    )


def test_62_dedup_applied() -> None:
    """隣接セクション両載の 62-1/62-2 が各 1 件に dedup 済み."""
    nums = [r["directive_number"] for r in _records()]
    assert nums.count("62-1") == 1
    assert nums.count("62-2") == 1


def test_all_directive_ids_well_formed() -> None:
    """全 directive_id が shotoku 2 レベル形式ゲートを通る (壊れ番号ゼロ)."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["shotoku"]
    for r in _records():
        assert mod._directive_id_ok(r["directive_id"], cfg), f"形式違反: {r['directive_id']!r}"


def _import_parser():
    spec = importlib.util.spec_from_file_location("parse_nta_tsutatsu", _PARSER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ===========================================================
# byte 再現 + セクション数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _SHOTOKU_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/shotoku/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_section_count_complete_enumeration() -> None:
    """完全列挙した 134 セクション (htm) が cache に揃う (索引漏れの差分検知)."""
    sections = list(_SHOTOKU_CACHE.glob("*/*.htm"))
    assert len(sections) == EXPECTED_SECTIONS, (
        f"セクション数が {EXPECTED_SECTIONS} でない: {len(sections)} "
        "(NTA がページを増減した可能性 -- 設計再検討が必要)"
    )


@pytest.mark.skipif(
    not _SHOTOKU_CACHE.exists(),
    reason="NTA HTML cache (cache/tsutatsu/shotoku/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を **byte 再現** する (決定性 + コーパス完全性)."""
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        ["--circular", "shotoku", "--cache-root", str(_SHOTOKU_CACHE), "--output-dir", str(out_dir)]
    )
    assert rc == 0
    produced = out_dir / "shotoku-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュのマージ出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

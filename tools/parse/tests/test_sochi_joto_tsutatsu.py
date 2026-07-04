"""test_sochi_joto_tsutatsu.py -- 租税特別措置法関係通達 (山林所得・譲渡所得関係) 取込のゲート (FU-539).

Why this test exists:
    措置法通達(山林所得・譲渡所得編)は所得税分野の個別通達で、法人税編 (sochi-hojin・kan_paren)
    と違い款括弧を持たず、番号は条-番号の 2 レベル (hierarchical・num_levels=2)。条跨ぎ共通は
    所得税型の 中黒「・」+ 共 (31・32共-1) で書かれ、既存 _LEVEL の (?:共)? 接尾 + _FIRST_LEVEL の
    中点 range + _RANGE_SEP_RE の ・->_ 正規化により追加コードなしで 31_32共-1 へ畳まれる (P0-2)。
    sochi-hojin (法人税編) の byte 回帰と対をなし、本ファイルは譲渡編側の構造健全性 +
    hierarchical/中点・共の取込を保証する。

    3 層構成:
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・
          directive_id ユニーク・件数 420・参照母集団 (linked 751 / unlinked 0) を pin。
      (2) hierarchical 固有ユニット (パーサ import・合成 HTML): 中点 条-join (31・32共->31_32共)・
          二重枝番 (33の4-2の4)・削除条。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-joto で subprocess 実行し baseline と byte 一致を assert。

    **落ちたら直すのはパーサ/データであって期待値ではない** (期待値変更は人間承認)。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
_BASELINE = _THIS.parent / "fixtures" / "sochi-joto-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_ROOT = _REPO_ROOT / "cache" / "tsutatsu" / "sochi-joto"

DIRECTIVE_KEY_ORDER = [
    "id",
    "directive_id",
    "law_name_ja",
    "law_abbrev",
    "directive_number",
    "title",
    "text",
    "amendment_note",
    "related_articles",
    "source_url",
    "license",
    "segment_type",
    "article_id",
    "law_name_ja_display",
]
LINKED_REF_KEYS = {"raw", "law_abbrev", "article_number", "article_id"}
UNLINKED_REF_KEYS = {"raw", "law_abbrev", "article_number", "unlinked_reason"}

# P0-3 実測・佐藤ロック (2026-07-04)。leaf 52 (soti30..41 + fusoku 除外) から 420 directive。
_LOCKED_COUNT = 420
_LOCKED_LINKED = 751  # 措置法系 + 所得税法系 + 通則法 は全件 corpus 実在 -> 全 link
_LOCKED_UNLINKED = 0
_SOURCE_PREFIX = "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/710826/sanrin/sanjyou/"


def _import_parser():
    spec = importlib.util.spec_from_file_location("parse_nta_tsutatsu", _PARSER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass + future annotations need module registered
    spec.loader.exec_module(mod)
    return mod


def _read_baseline() -> list[dict]:
    return [
        json.loads(line)
        for line in _BASELINE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ===========================================================
# (1) 構造監査 (CI-safe: committed baseline のみ参照)
# ===========================================================


def test_baseline_fixture_exists() -> None:
    assert _BASELINE.exists(), f"baseline fixture 不在: {_BASELINE}"


def test_all_chunks_have_locked_key_order() -> None:
    records = _read_baseline()
    assert records, "baseline が空"
    for i, rec in enumerate(records):
        assert list(rec.keys()) == DIRECTIVE_KEY_ORDER, (
            f"chunk[{i}] (id={rec.get('id')!r}) のキー順/集合が不一致: {list(rec.keys())}"
        )


def test_related_article_refs_match_disjoint_forms() -> None:
    for rec in _read_baseline():
        for ref in rec["related_articles"]:
            keys = set(ref.keys())
            assert keys in (LINKED_REF_KEYS, UNLINKED_REF_KEYS), (
                f"id={rec['id']!r} の ref が disjoint 2 形のいずれにも一致しない: {sorted(keys)}"
            )


def test_directive_id_unique() -> None:
    ids = [r["directive_id"] for r in _read_baseline()]
    assert len(ids) == len(set(ids)), "directive_id に重複がある (fail-loud 対象)"


def test_chunk_count_locked() -> None:
    assert len(_read_baseline()) == _LOCKED_COUNT, (
        f"措置法通達 (山林所得・譲渡所得編) の chunk 数は {_LOCKED_COUNT} (fusoku 除外・soti30..41)"
    )


def test_ref_population_all_linked() -> None:
    """措置法系 + 所得税法系 + 通則法 は全件 corpus 実在 (data/v0.2/phase1-tax) -> 全 link."""
    linked = unlinked = 0
    abbrevs: set[str] = set()
    for rec in _read_baseline():
        for ref in rec["related_articles"]:
            if set(ref.keys()) == LINKED_REF_KEYS:
                linked += 1
                abbrevs.add(ref["law_abbrev"])
            elif set(ref.keys()) == UNLINKED_REF_KEYS:
                unlinked += 1
    assert (linked, unlinked) == (_LOCKED_LINKED, _LOCKED_UNLINKED), (
        f"ref 母集団が変化: linked={linked} unlinked={unlinked}"
    )
    assert abbrevs <= {
        "sochi-hou",
        "sochi-hou-shikkourei",
        "sochi-hou-shikoukisoku",
        "shotoku-zei-hou",
        "shotoku-zei-hou-shikkourei",
        "shotoku-zei-hou-shikoukisoku",
        "kokuzei-tsuusoku-hou",
    }, f"想定外の参照先 law_abbrev: {abbrevs}"


def test_pipeline_fields_are_sochi_joto() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "租税特別措置法関係通達（山林所得・譲渡所得関係）"
        assert rec["law_abbrev"] == "sochi-joto-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith(_SOURCE_PREFIX)


def test_directive_id_all_pass_format_gate() -> None:
    """全 directive_id が hierarchical 形式ゲート (num_levels=2・共/の 枝番許容) を通る."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-joto"]
    for rec in _read_baseline():
        assert mod._directive_id_ok(rec["directive_id"], cfg), (
            f"directive_id が形式ゲート違反: {rec['directive_id']!r}"
        )


def test_cross_article_naka_kyo_marker_present() -> None:
    """条跨ぎ共通が 中点「・」+ 共 で畳まれた id が存在する (31・32共-1 -> 31_32共-1)."""
    ids = {r["directive_id"] for r in _read_baseline()}
    assert "sochi-joto-tsutatsu-31_32共-1" in ids, "中点 条-join + 共 の畳み込み id が欠落"


def test_double_branch_and_edatsu_present() -> None:
    """二重枝番 (条・番号とも「の」枝番) と 条枝番 が保持される."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert "30の2-1" in nums, "条枝番 (30の2-1) が欠落"
    # 二重枝番 (条=33の4, 番号=2の4) — 実在すれば の が両側で保持される
    assert any("の" in n and n.count("-") == 1 for n in nums), "の枝番を持つ番号が無い"


# ===========================================================
# (2) hierarchical (中点・共) 固有ユニット (パーサ import)
# ===========================================================


def test_circular_config_sochi_joto() -> None:
    mod = _import_parser()
    assert "sochi-joto" in mod.CIRCULAR_CONFIGS
    cfg = mod.CIRCULAR_CONFIGS["sochi-joto"]
    assert cfg.law_abbrev == "sochi-joto-tsutatsu"
    assert cfg.law_name_ja == "租税特別措置法関係通達（山林所得・譲渡所得関係）"
    # 法人税編 (kan_paren) と違い hierarchical・2 レベル (条-番号)。款括弧なし (P0-2)。
    assert cfg.num_style == "hierarchical"
    assert cfg.num_levels == 2
    assert cfg.corpus_unregistered == frozenset()
    assert cfg.exclude_files == frozenset()
    # ref_map は実本文の表記 (probe-don't-guess・P0-2): 所得税分野ゆえ裸「法」= 所得税法。
    assert cfg.ref_map["措置法"] == "sochi-hou"
    assert cfg.ref_map["措置法令"] == "sochi-hou-shikkourei"
    assert cfg.ref_map["措置法規則"] == "sochi-hou-shikoukisoku"
    assert cfg.ref_map["法"] == "shotoku-zei-hou"
    assert cfg.ref_map["令"] == "shotoku-zei-hou-shikkourei"
    assert cfg.ref_map["所得税法"] == "shotoku-zei-hou"
    assert cfg.ref_map["通則法"] == "kokuzei-tsuusoku-hou"


def test_directive_id_ok_hierarchical_forms() -> None:
    """hierarchical 形式ゲート (num_levels=2): 条-番号・共・の 枝番を受理・裸番号を拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-joto"]
    ok = mod._directive_id_ok
    assert ok("sochi-joto-tsutatsu-33-31", cfg)  # 条-番号
    assert ok("sochi-joto-tsutatsu-30の2-1", cfg)  # 条枝番
    assert ok("sochi-joto-tsutatsu-33の4-2の4", cfg)  # 二重枝番 (の 保持)
    assert ok("sochi-joto-tsutatsu-31_32共-1", cfg)  # 中点 条-join + 共
    assert not ok("sochi-joto-tsutatsu-31", cfg)  # 裸番号 (番号レベル欠落)
    assert not ok("sochi-hojin-tsutatsu-33-31", cfg)  # prefix 不一致


# --- 合成 HTML による抽出パス (中点・共・二重枝番) ---

_PAGE_TMPL = """<html><head><meta charset="shift_jis"></head><body>
<div id="bodyArea">
<h1>節見出し</h1>
{items}
</div></body></html>"""


def _page(*items: tuple[str, str, str]) -> bytes:
    body = "\n".join(f"<h2>{t}</h2>\n<p><strong>{n}</strong>　{b}</p>" for n, t, b in items)
    return _PAGE_TMPL.format(items=body).encode("cp932")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _run(mod, cache_root: Path, out_dir: Path) -> tuple[int, list[dict]]:
    rc = mod.main(
        ["--circular", "sochi-joto", "--cache-root", str(cache_root), "--output-dir", str(out_dir)]
    )
    out = out_dir / "sochi-joto-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


def test_naka_kyo_directive(tmp_path: Path) -> None:
    """中点 条-join + 共 番号が範囲末尾へ畳まれて取込まれる (31・32共-1 -> 31_32共-1)."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "soti31" / "01.htm", _page(("31・32共－1", "（共通）", "共通本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_id"] == "sochi-joto-tsutatsu-31_32共-1"


def test_double_branch_directive(tmp_path: Path) -> None:
    """二重枝番 (条=33の4・番号=2の4) が の 保持で取込まれる."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "soti33" / "01.htm", _page(("33の4－2の4", "（甲）", "本文甲。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_number"] == "33の4-2の4"


def test_fusoku_dir_excluded(tmp_path: Path) -> None:
    """附則 (fusoku/) は章フィルタ非マッチで自然除外される (soti 章のみ取込)."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "soti30" / "01.htm", _page(("30-1", "（本則）", "本則本文。")))
    _write(root / "fusoku" / "01.htm", _page(("1-1", "（附則）", "附則本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    nums = [r["directive_number"] for r in recs]
    assert nums == ["30-1"], f"附則が取込まれた (soti 章のみのはず): {nums}"


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_ROOT.exists(),
    reason="NTA HTML cache (cache/tsutatsu/sochi-joto/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "sochi-joto",
            "--cache-root",
            str(_CACHE_ROOT),
            "--output-dir",
            str(out_dir),
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, f"parser 失敗 (rc={result.returncode}):\n{result.stderr}"
    produced = out_dir / "sochi-joto-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

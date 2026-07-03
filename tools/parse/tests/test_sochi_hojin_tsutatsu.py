"""test_sochi_hojin_tsutatsu.py -- 租税特別措置法関係通達 (法人税編) 取込のゲート (FU-536).

Why this test exists:
    措置法通達は parse-nta-tsutatsu.py に新 num_style "kan_paren" を足して取込む
    (条と項の間に款マーカー (N)/（N） を持つ 62の3（1）－1・条跨ぎ共通 （共） を持つ
    42の5～48（共）－1)。既存 5 通達の byte 回帰と対をなし、本ファイルは措置法通達側の
    構造健全性 + kan_paren 固有ロジックを保証する。

    3 層構成:
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・
          directive_id ユニーク・件数 933・参照母集団 (linked 1185 / unlinked 0) を pin。
      (2) kan_paren 固有ユニット (パーサ import・合成 HTML): 款畳み込み (の 保持)・可変
          レベル (2/3)・項必須 (裸号番号を通達開始と誤検出しない)・（共）・旧 02_57_4.htm 除外。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-hojin で subprocess 実行し baseline と byte 一致を assert。

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
_BASELINE = _THIS.parent / "fixtures" / "sochi-hojin-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_ROOT = _REPO_ROOT / "cache" / "tsutatsu" / "sochi-hojin"

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

# P0-3 実測・佐藤 v7 ロック (2026-07-03)。
_LOCKED_COUNT = 933
_LOCKED_LINKED = 1185
_LOCKED_UNLINKED = 0
_SOURCE_PREFIX = "https://www.nta.go.jp/law/tsutatsu/kobetsu/hojin/sochiho/750214/"


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
        f"措置法通達 (法人税編) の chunk 数は {_LOCKED_COUNT} (旧 02_57_4.htm 除外・bessi/zenbun 除外)"
    )


def test_ref_population_all_linked() -> None:
    """措置法系 (措置法/措置法令/措置法規則) + 法人税法系 (法/令) は全件 corpus 実在 -> 全 link."""
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
        "houjin-zei-hou",
        "houjin-zei-hou-shikkourei",
        "houjin-zei-hou-shikoukisoku",
    }, f"想定外の参照先 law_abbrev: {abbrevs}"


def test_pipeline_fields_are_sochi_hojin() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "租税特別措置法関係通達（法人税編）"
        assert rec["law_abbrev"] == "sochi-hojin-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith(_SOURCE_PREFIX)


def test_directive_id_all_pass_format_gate() -> None:
    """全 directive_id が kan_paren 形式ゲート (可変 2/3 レベル) を通る."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-hojin"]
    for rec in _read_baseline():
        assert mod._directive_id_ok(rec["directive_id"], cfg), (
            f"directive_id が形式ゲート違反: {rec['directive_id']!r}"
        )


def test_kan_folded_and_no_retained_in_baseline() -> None:
    """畳み込み後の directive_id: 括弧なし・の 保持・款は末尾数値レベル."""
    recs = {r["directive_number"]: r for r in _read_baseline()}
    # 款あり (条-款-項 = 3 level): 42の4（1）－1 -> 42の4-1-1 (の 保持)
    assert "42の4-1-1" in recs, "款畳み込み (42の4-1-1) が baseline に無い"
    assert recs["42の4-1-1"]["directive_id"] == "sochi-hojin-tsutatsu-42の4-1-1"
    # 款なし (条-項 = 2 level): 42の3の2-1 (の 保持)
    assert "42の3の2-1" in recs, "款なし条-項 (42の3の2-1) が baseline に無い"
    # 括弧は directive_id に一切残らない
    for r in _read_baseline():
        assert "(" not in r["directive_id"] and "（" not in r["directive_id"], (
            f"款括弧が directive_id に残存: {r['directive_id']!r}"
        )


def test_cross_article_kyo_marker_present() -> None:
    """条跨ぎ共通マーカー （共） が範囲末尾へ畳まれた id が存在する (42の5_48共-1)."""
    ids = {r["directive_id"] for r in _read_baseline()}
    assert "sochi-hojin-tsutatsu-42の5_48共-1" in ids, "（共）畳み込み id が欠落"


def test_old_57_4_excluded_new_kept() -> None:
    """旧 57の4 (原子力発電施設解体準備金) 除外・新 57の4 (炉心等除去準備金) が残る."""
    by = {r["directive_number"]: r for r in _read_baseline()}
    assert "57の4-1" in by and "57の4-2" in by
    # 新版の本文/見出しであること (旧「解体準備金」でない)
    assert "炉心等除去準備金" in by["57の4-2"]["title"] + by["57の4-2"]["text"]
    assert "解体準備金" not in by["57の4-1"]["title"]


# ===========================================================
# (2) kan_paren 固有ユニット (パーサ import)
# ===========================================================


def test_circular_config_sochi_hojin() -> None:
    mod = _import_parser()
    assert "sochi-hojin" in mod.CIRCULAR_CONFIGS
    cfg = mod.CIRCULAR_CONFIGS["sochi-hojin"]
    assert cfg.law_abbrev == "sochi-hojin-tsutatsu"
    assert cfg.law_name_ja == "租税特別措置法関係通達（法人税編）"
    assert cfg.num_style == "kan_paren"
    assert cfg.amendment_markers == ("課法", "直法")
    assert cfg.corpus_unregistered == frozenset()
    assert cfg.exclude_files == frozenset({"02_57_4.htm"})
    # ref_map は実本文の full 形 (probe-don't-guess): 措置法/措置法令/措置法規則 + 裸 法/令/規。
    assert cfg.ref_map["措置法"] == "sochi-hou"
    assert cfg.ref_map["措置法令"] == "sochi-hou-shikkourei"
    assert cfg.ref_map["措置法規則"] == "sochi-hou-shikoukisoku"
    assert cfg.ref_map["法"] == "houjin-zei-hou"
    assert cfg.ref_map["令"] == "houjin-zei-hou-shikkourei"


def test_fold_kan_paren_units() -> None:
    """_fold_kan_paren: 款 (N)/（N）->-N・全角数字 NFKC・（共）->共・の 保持."""
    mod = _import_parser()
    f = mod._fold_kan_paren
    assert f("62の3(1)-1") == "62の3-1-1"  # 半角款
    assert f("42の4（1）-1") == "42の4-1-1"  # 全角款
    assert f("66の4の3（10）-2") == "66の4の3-10-2"  # 多桁款・の 保持
    assert f("42の11の2-1") == "42の11の2-1"  # 款なし (の 保持)
    assert f("42の5_48（共）-1") == "42の5_48共-1"  # （共）-> 共 (範囲末尾)
    assert f("43の２-1") == "43の2-1"  # 全角数字 NFKC・の 保持


def test_directive_id_ok_variable_levels() -> None:
    """kan_paren 形式ゲート: 条-項 (2) / 条-款-項 (3) を受理・裸番号/未畳み括弧は拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-hojin"]
    ok = mod._directive_id_ok
    assert ok("sochi-hojin-tsutatsu-42の10-1", cfg)  # 2 level (条-項)
    assert ok("sochi-hojin-tsutatsu-62の3-1-1", cfg)  # 3 level (条-款-項)
    assert ok("sochi-hojin-tsutatsu-42の11の2-5の2", cfg)  # の 保持 2 level
    assert not ok("sochi-hojin-tsutatsu-2", cfg)  # 裸番号 (号ノイズ)
    assert not ok("sochi-hojin-tsutatsu-62の3(1)-1", cfg)  # 未畳み込み括弧
    assert not ok("hojin-kihon-tsutatsu-62の3-1-1", cfg)  # prefix 不一致


def test_related_articles_use_full_prefix_forms() -> None:
    """本文の full 表記 (措置法/措置法令) を長い接頭辞優先で解決 (裸「法」へ潰さない)."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-hojin"]
    text = "措置法第42条の4の規定及び措置法令第27条の4、法第9条による。"
    got = {r["raw"]: r["law_abbrev"] for r in mod._extract_related_articles(text, cfg)}
    assert got.get("措置法第42条の4") == "sochi-hou"
    assert got.get("措置法令第27条の4") == "sochi-hou-shikkourei"
    assert got.get("法第9条") == "houjin-zei-hou"


# --- 合成 HTML による抽出パス (項必須・（共）・除外) ---

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
        ["--circular", "sochi-hojin", "--cache-root", str(cache_root), "--output-dir", str(out_dir)]
    )
    out = out_dir / "sochi-hojin-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


def test_kan_directive_start_and_bare_go_number_in_body(tmp_path: Path) -> None:
    """款付き番号は通達開始・本文中の裸号番号 (2) は本文へ (項必須ガード)."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    # 62の3(1)－1 が項開始、本文に号 "2　..." を含む。号は新項を作らない。
    _write(
        root / "09" / "09_62_3.htm",
        _page(
            ("62の3(1)－1", "（甲）", "本文甲。\n2　号としての裸番号（項ではない）。"),
            ("62の3(1)－2", "（乙）", "本文乙。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0, "款付き番号 parse が失敗 (rc!=0)"
    nums = [r["directive_number"] for r in recs]
    assert nums == ["62の3-1-1", "62の3-1-2"], f"裸号番号を誤って項化: {nums}"
    assert "号としての裸番号" in recs[0]["text"]


def test_kyo_marker_directive(tmp_path: Path) -> None:
    """条跨ぎ共通 （共） 番号が範囲末尾へ畳まれて取込まれる."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "01" / "01_42_05.htm", _page(("42の5～48（共）－1", "（共通）", "共通本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_id"] == "sochi-hojin-tsutatsu-42の5_48共-1"


def test_exclude_files_drops_named_basename(tmp_path: Path) -> None:
    """exclude_files の basename (02_57_4.htm) は多章取込から機械除外される."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "02" / "02_57_4.htm", _page(("57の4－1", "（旧）", "旧・解体準備金。")))
    _write(root / "02" / "02_57_4_2.htm", _page(("57の4－1", "（新）", "新・炉心等除去準備金。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0, "除外が効かず同 id 異本文で fail-loud した"
    assert len(recs) == 1
    assert recs[0]["title"] == "（新）", "旧版が残った (除外未適用)"


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_ROOT.exists(),
    reason="NTA HTML cache (cache/tsutatsu/sochi-hojin/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "sochi-hojin",
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
    produced = out_dir / "sochi-hojin-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

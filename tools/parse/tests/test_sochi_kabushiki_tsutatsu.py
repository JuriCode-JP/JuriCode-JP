"""test_sochi_kabushiki_tsutatsu.py -- 租税特別措置法(株式等に係る譲渡所得等関係)の取扱い 取込のゲート (FU-542).

Why this test exists:
    株式等譲渡措通(020624)は所得税(譲渡所得)分野の個別通達で、山林所得・譲渡所得編 (sochi-joto)
    と同じ hierarchical・num_levels=2 (条-番号)。款括弧を持たず・混在レベルもなし (P0-2)、条跨ぎ範囲は
    中黒「・」+ 共通 (37の10・37の11共-1) で書かれ、既存 _RANGE_SEP_RE の ・->_ 正規化 + _LEVEL の
    (?:共)? 接尾により追加コードなしで 37の10_37の11共-1 へ畳まれる。本文には別法令 (金融商品取引法/
    会社法/内閣府令) が 第N条 で現れるため、裸「法/令」の偽マッチを避けるべく named-law を full 形で
    ref_map + corpus_unregistered に登録し unlinked 記録する (誤リンク0・SOUZOKU/SHOTOKU 同型)。

    3 層構成:
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・
          directive_id ユニーク・件数 148・参照母集団 (linked 246 / unlinked 12=named-law) を pin。
      (2) hierarchical 固有ユニット (パーサ import・合成 HTML): 中黒範囲 + 共 (37の10・37の11共->
          37の10_37の11共)・二重枝番 (37の14の2-3の2)・named-law の裸「法」偽マッチ回避。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-kabushiki で subprocess 実行し baseline と byte 一致を assert。

    NB: cache は 4 桁 tree code dir (1273) の下に条 dir が入れ子 (_CHAPTER_DIR_RE に \\d{4} を additive
    追加)。兄弟 dir 1273_1 は「平成14年11月27日付改正以前のもの」= 旧版アーカイブで現行 1273 と
    directive_number を重複させるため \\d{4} (接尾なし) で機械除外する (P0-1・fail-loud 検知で確定)。

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
_BASELINE = _THIS.parent / "fixtures" / "sochi-kabushiki-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_ROOT = _REPO_ROOT / "cache" / "tsutatsu" / "sochi-kabushiki"

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

# P0-3 実測・佐藤ロック (2026-07-04)。18 leaf のうち現行 1273 系 (zenbun 前文と 1273_1 旧版を除く)
# から 148 directive。
_LOCKED_COUNT = 148
_LOCKED_LINKED = 246  # 措置法系 + 所得税法系 + 法人税法系 + 通則法 は全件 corpus 実在 -> link
_LOCKED_UNLINKED = (
    12  # named-law (金融商品取引法/会社法/内閣府令) は corpus 未収録 -> unlinked 記録
)
_SOURCE_PREFIX = "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin/"

# link 先 (corpus 実在・data/v0.2/phase1-tax)。株式譲渡は所得税分野ゆえ裸「法」= 所得税法。
_LINKED_ALLOWED = frozenset(
    {
        "sochi-hou",
        "sochi-hou-shikkourei",
        "sochi-hou-shikoukisoku",
        "shotoku-zei-hou",
        "shotoku-zei-hou-shikkourei",
        "houjin-zei-hou",
        "houjin-zei-hou-shikkourei",
        "kokuzei-tsuusoku-hou",
    }
)

# named-law ガード: 本文に 第N条 で現れる別法令を full 形で登録し裸「法/令」偽マッチを回避 (誤リンク0)。
_NAMED_LAW_UNREG = frozenset(
    {
        "kinyuu-shouhin-torihiki-hou",
        "kaisha-hou",
        "naikakufu-rei",
    }
)


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
        f"株式等譲渡措通 の chunk 数は {_LOCKED_COUNT} "
        "(現行 1273 系・zenbun 前文と 1273_1 旧版アーカイブは除外)"
    )


def test_ref_population_linked_and_named_law_unlinked() -> None:
    """措置法系 + 所得税法系 + 法人税法系 + 通則法 は全 link、named-law は unlinked 記録 (誤リンク0)."""
    linked = unlinked = 0
    linked_abbrevs: set[str] = set()
    unlinked_abbrevs: set[str] = set()
    for rec in _read_baseline():
        for ref in rec["related_articles"]:
            if set(ref.keys()) == LINKED_REF_KEYS:
                linked += 1
                linked_abbrevs.add(ref["law_abbrev"])
            elif set(ref.keys()) == UNLINKED_REF_KEYS:
                unlinked += 1
                unlinked_abbrevs.add(ref["law_abbrev"])
    assert (linked, unlinked) == (_LOCKED_LINKED, _LOCKED_UNLINKED), (
        f"ref 母集団が変化: linked={linked} unlinked={unlinked}"
    )
    assert linked_abbrevs <= _LINKED_ALLOWED, f"想定外の link 先 law_abbrev: {linked_abbrevs}"
    # unlinked は named-law ガードのみ (裸「法/令」偽リンクが混入していない証跡)。
    assert unlinked_abbrevs <= _NAMED_LAW_UNREG, (
        f"想定外の unlinked law_abbrev (偽リンク疑い): {unlinked_abbrevs}"
    )


def test_pipeline_fields_are_sochi_kabushiki() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "租税特別措置法（株式等に係る譲渡所得等関係）の取扱い"
        assert rec["law_abbrev"] == "sochi-kabushiki-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith(_SOURCE_PREFIX)


def test_directive_id_all_pass_format_gate() -> None:
    """全 directive_id が hierarchical 形式ゲート (num_levels=2・共/の 枝番許容) を通る."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-kabushiki"]
    for rec in _read_baseline():
        assert mod._directive_id_ok(rec["directive_id"], cfg), (
            f"directive_id が形式ゲート違反: {rec['directive_id']!r}"
        )


def test_cross_article_range_kyo_marker_present() -> None:
    """条跨ぎ範囲 (中黒・) + 共通 が畳まれた id が存在する (37の10・37の11共-1 -> 37の10_37の11共-1)."""
    ids = {r["directive_id"] for r in _read_baseline()}
    assert "sochi-kabushiki-tsutatsu-37の10_37の11共-1" in ids, (
        "条跨ぎ範囲 (中黒) + 共 の畳み込み id が欠落"
    )


def test_double_branch_present() -> None:
    """二重枝番 (条・番号とも「の」枝番) が保持される (37の14の2-3の2)."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert "37の14の2-3の2" in nums, "二重枝番 (37の14の2-3の2) が欠落"


def test_37_series_present_for_cross_domain_link() -> None:
    """shotoku taxanswer link 対象 (37系株式等譲渡) が corpus に実在する (37の11-1/37の11の2-1)."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert "37の11-1" in nums, "37の11-1 が欠落 (shotoku taxanswer の fallback link 対象)"
    assert "37の11の2-1" in nums, "37の11の2-1 が欠落 (near-pattern 区別対象)"


def test_no_old_archive_directives() -> None:
    """旧版アーカイブ (1273_1・平成14年改正以前) の directive が混入していない (source_url で確認)."""
    for rec in _read_baseline():
        assert "/1273_1/" not in rec["source_url"], (
            f"旧版アーカイブ 1273_1 の directive が混入: {rec['directive_id']}"
        )


# ===========================================================
# (2) hierarchical (中黒範囲・共) 固有ユニット (パーサ import)
# ===========================================================


def test_circular_config_sochi_kabushiki() -> None:
    mod = _import_parser()
    assert "sochi-kabushiki" in mod.CIRCULAR_CONFIGS
    cfg = mod.CIRCULAR_CONFIGS["sochi-kabushiki"]
    assert cfg.law_abbrev == "sochi-kabushiki-tsutatsu"
    assert cfg.law_name_ja == "租税特別措置法（株式等に係る譲渡所得等関係）の取扱い"
    # 山林所得・譲渡所得編と同型 hierarchical・2 レベル (条-番号)。款括弧なし・混在レベルなし (P0-2)。
    assert cfg.num_style == "hierarchical"
    assert cfg.num_levels == 2
    assert cfg.exclude_files == frozenset()
    # named-law ガードで corpus_unregistered は非空 (裸「法/令」偽リンク回避)。
    assert cfg.corpus_unregistered == _NAMED_LAW_UNREG
    # ref_map は実本文の表記 (probe-don't-guess・P0-2): 株式譲渡は所得税分野ゆえ裸「法」= 所得税法。
    assert cfg.ref_map["措置法"] == "sochi-hou"
    assert cfg.ref_map["措置法令"] == "sochi-hou-shikkourei"
    assert cfg.ref_map["法"] == "shotoku-zei-hou"
    assert cfg.ref_map["令"] == "shotoku-zei-hou-shikkourei"
    # NTA 短縮表記「所得税法令」= 所得税法施行令 (P0-2 実確認)。
    assert cfg.ref_map["所得税法令"] == "shotoku-zei-hou-shikkourei"
    assert cfg.ref_map["通則法"] == "kokuzei-tsuusoku-hou"
    # named-law は full 形で登録 (長い接頭辞優先で裸「法」へ潰れない)。
    assert cfg.ref_map["金融商品取引法"] == "kinyuu-shouhin-torihiki-hou"
    assert cfg.ref_map["会社法"] == "kaisha-hou"


def test_directive_id_ok_hierarchical_forms() -> None:
    """hierarchical 形式ゲート (num_levels=2): 条-番号・共・の 枝番を受理・裸番号を拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-kabushiki"]
    ok = mod._directive_id_ok
    assert ok("sochi-kabushiki-tsutatsu-37の11-1", cfg)  # 条-番号
    assert ok("sochi-kabushiki-tsutatsu-37の11の2-1", cfg)  # 条枝番
    assert ok("sochi-kabushiki-tsutatsu-37の14の2-3の2", cfg)  # 二重枝番 (の 保持)
    assert ok("sochi-kabushiki-tsutatsu-37の10_37の11共-1", cfg)  # 条跨ぎ範囲 + 共
    assert not ok("sochi-kabushiki-tsutatsu-37", cfg)  # 裸番号 (番号レベル欠落)
    assert not ok("sochi-joto-tsutatsu-37の11-1", cfg)  # prefix 不一致


# --- 合成 HTML による抽出パス (中黒範囲・共・named-law 偽マッチ回避) ---

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
        [
            "--circular",
            "sochi-kabushiki",
            "--cache-root",
            str(cache_root),
            "--output-dir",
            str(out_dir),
        ]
    )
    out = out_dir / "sochi-kabushiki-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


def test_range_kyo_directive(tmp_path: Path) -> None:
    """条跨ぎ範囲 (中黒・) + 共 番号が範囲区切り正規化で畳まれて取込まれる (37の10・37の11共-1 -> 37の10_37の11共-1)。

    hierarchical は kan_paren と違い款括弧を畳まない。共 は _LEVEL の (?:共)? 接尾で条番号レベルに
    直付き、範囲区切り 中黒「・」のみ _RANGE_SEP_RE で "_" に正規化される (実データ実測形)。
    cache 直下に 4 桁 tree code dir (1273) を要する (_CHAPTER_DIR_RE の \\d{4})。
    """
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(
        root / "1273" / "37_10-11" / "01.htm",
        _page(("37の10・37の11共－1", "（共通）", "共通本文。")),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_id"] == "sochi-kabushiki-tsutatsu-37の10_37の11共-1"


def test_double_branch_directive(tmp_path: Path) -> None:
    """二重枝番 (37の14の2-3の2) が の 保持で取込まれる."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "1273" / "37_14_2" / "01.htm", _page(("37の14の2－3の2", "（甲）", "本文甲。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_number"] == "37の14の2-3の2"


def test_old_archive_dir_excluded(tmp_path: Path) -> None:
    """4 桁 tree code の枝番 dir (1273_1 = 旧版アーカイブ) は _CHAPTER_DIR_RE の \\d{4} 接尾なしで除外."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    # 現行 1273 と旧版 1273_1 を同居させ、現行のみ捕捉・旧版は非収録を pin。
    _write(root / "1273" / "37_11" / "01.htm", _page(("37の11－1", "（現行）", "現行本文。")))
    _write(root / "1273_1" / "37_11" / "01.htm", _page(("37の11－1", "（旧版）", "旧版本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert len(recs) == 1, (
        f"旧版アーカイブが混入 (現行のみのはず): {[r['source_url'] for r in recs]}"
    )
    assert "/1273/" in recs[0]["source_url"] and "/1273_1/" not in recs[0]["source_url"]


def test_named_law_not_falsely_linked_to_shotoku(tmp_path: Path) -> None:
    """named-law の 第N条 が裸「法」で所得税法へ偽リンクしない (unlinked 記録・誤リンク0)."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    # 金融商品取引法第2条 は裸「法」(所得税法) へ潰れず kinyuu-* の unlinked に落ちる。
    _write(
        root / "1273" / "37_11" / "01.htm",
        _page(("37の11-1", "（甲）", "金融商品取引法第2条の規定による。")),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    refs = recs[0]["related_articles"]
    abbrevs = {r["law_abbrev"] for r in refs}
    assert "shotoku-zei-hou" not in abbrevs, f"金融商品取引法が所得税法へ偽リンク: {refs}"
    assert "kinyuu-shouhin-torihiki-hou" in abbrevs, (
        f"named-law が unlinked 記録されていない: {refs}"
    )


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_ROOT.exists(),
    reason="NTA HTML cache (cache/tsutatsu/sochi-kabushiki/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "sochi-kabushiki",
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
    produced = out_dir / "sochi-kabushiki-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

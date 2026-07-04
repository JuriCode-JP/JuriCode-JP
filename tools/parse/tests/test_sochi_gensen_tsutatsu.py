"""test_sochi_gensen_tsutatsu.py -- 租税特別措置法に係る所得税の取扱い(源泉所得税関係) 取込のゲート (FU-546).

Why this test exists:
    源泉所得税措通(880331/gensen/58)は所得税(源泉徴収)分野の個別通達で、株式等譲渡編 (sochi-kabushiki)
    と同じ hierarchical・num_levels=2 (条-番号)。款括弧を持たず・混在レベルもなし (P0-2)、条跨ぎ範囲は
    中黒「・」+ 共通 (41の10・41の12共-1) で書かれ、既存 _RANGE_SEP_RE の ・->_ 正規化 + _LEVEL の
    (?:共)? 接尾により追加コードなしで 41の10_41の12共-1 へ畳まれる。本文には別法令 (勤労者財産形成
    促進法=財形法/外国為替及び外国貿易法=外為法/外国為替令=外為令/外為省令/賃金の支払の確保等に関する
    法律=賃金支払確保法) が 第N条 で現れるため、裸「法/令」の偽マッチを避けるべく named-law を full 形で
    ref_map + corpus_unregistered に登録し unlinked 記録する (誤リンク0・KABUSHIKI/SOZOKU 同型)。

    3 層構成:
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・
          directive_id ユニーク・件数 136・参照母集団 (linked 211 / unlinked 35=named-law) を pin。
      (2) hierarchical 固有ユニット (パーサ import・合成 HTML): 中黒範囲 + 共 (41の10・41の12共->
          41の10_41の12共)・条二重枝番 (41の12の2-1)・named-law の裸「法」偽マッチ回避・zenbun/fusoku 除外。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-gensen で subprocess 実行し baseline と byte 一致を assert。

    NB: cache は 2 桁章 dir (03/04/.../41/42) 直下に leaf。前文 zenbun と附則 fusoku は
    非 directive ゆえ _CHAPTER_DIR_RE (\\d{2}|soti\\d+|\\d{4}) に非該当で機械除外される (P0-1)。

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
_BASELINE = _THIS.parent / "fixtures" / "sochi-gensen-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_ROOT = _REPO_ROOT / "cache" / "tsutatsu" / "sochi-gensen"

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

# P0-3 実測・佐藤ロック (2026-07-04)。18 leaf のうち現行 16 章 leaf (zenbun/fusoku を除く) から
# 136 directive。
_LOCKED_COUNT = 136
_LOCKED_LINKED = 211  # 措置法系 + 所得税法系 は全件 corpus 実在 -> link
_LOCKED_UNLINKED = 35  # named-law (財形法/外為系/賃金支払確保法) は corpus 未収録 -> unlinked 記録
_SOURCE_PREFIX = "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/880331/gensen/58/"

# link 先 (corpus 実在・data/v0.2/phase1-tax)。源泉所得税は所得税分野ゆえ裸「法」= 所得税法。
_LINKED_ALLOWED = frozenset(
    {
        "sochi-hou",
        "sochi-hou-shikkourei",
        "sochi-hou-shikoukisoku",
        "shotoku-zei-hou",
        "shotoku-zei-hou-shikkourei",
        "shotoku-zei-hou-shikoukisoku",
        "houjin-zei-hou",
        "houjin-zei-hou-shikkourei",
        "kokuzei-tsuusoku-hou",
    }
)

# named-law ガード: 本文に 第N条 で現れる別法令を full 形で登録し裸「法/令」偽マッチを回避 (誤リンク0)。
_NAMED_LAW_UNREG = frozenset(
    {
        "kinrousha-zaisan-keisei-sokushin-hou",
        "kinrousha-zaisan-keisei-sokushin-hou-shikkourei",
        "gaikoku-kawase-rei",
        "gaikoku-kawase-shourei",
        "gaikoku-kawase-oyobi-gaikoku-boueki-hou",
        "chingin-shiharai-kakuho-hou",
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
        f"源泉所得税措通 の chunk 数は {_LOCKED_COUNT} (現行 16 章 leaf・zenbun 前文と fusoku 附則は除外)"
    )


def test_ref_population_linked_and_named_law_unlinked() -> None:
    """措置法系 + 所得税法系 は全 link、named-law は unlinked 記録 (誤リンク0)."""
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


def test_pipeline_fields_are_sochi_gensen() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "租税特別措置法に係る所得税の取扱い（源泉所得税関係）"
        assert rec["law_abbrev"] == "sochi-gensen-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith(_SOURCE_PREFIX)


def test_directive_id_all_pass_format_gate() -> None:
    """全 directive_id が hierarchical 形式ゲート (num_levels=2・共/の 枝番許容) を通る."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-gensen"]
    for rec in _read_baseline():
        assert mod._directive_id_ok(rec["directive_id"], cfg), (
            f"directive_id が形式ゲート違反: {rec['directive_id']!r}"
        )


def test_cross_article_range_kyo_marker_present() -> None:
    """条跨ぎ範囲 (中黒・) + 共通 が畳まれた id が存在する (41の10・41の12共-1 -> 41の10_41の12共-1)."""
    ids = {r["directive_id"] for r in _read_baseline()}
    assert "sochi-gensen-tsutatsu-41の10_41の12共-1" in ids, (
        "条跨ぎ範囲 (中黒) + 共 の畳み込み id が欠落"
    )


def test_double_branch_conditions_present() -> None:
    """条の二重枝番 (41の12の2-1) と番号の枝番 (3の3-10の2・4の2-15の2) が の 保持で存在する."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert "41の12の2-1" in nums, "条二重枝番 (41の12の2-1) が欠落"
    assert "3の3-10の2" in nums, "番号枝番 (3の3-10の2) が欠落"
    assert "4の2-15の2" in nums, "番号枝番 (4の2-15の2) が欠落"


def test_3_1_present_for_cross_domain_link() -> None:
    """taxanswer 措通3-1 の fallback link 対象 (措置法第3条 利子所得分離課税) が corpus に実在する."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert "3-1" in nums, "3-1 が欠落 (joto/shotoku taxanswer の措通3-1 fallback link 対象)"


def test_no_zenbun_or_fusoku_directives() -> None:
    """前文 zenbun / 附則 fusoku は非 directive ゆえ収録されない (source_url で確認)."""
    for rec in _read_baseline():
        assert "/zenbun/" not in rec["source_url"], (
            f"前文 zenbun が directive として混入: {rec['directive_id']}"
        )
        assert "/fusoku/" not in rec["source_url"], (
            f"附則 fusoku が directive として混入: {rec['directive_id']}"
        )


# ===========================================================
# (2) hierarchical (中黒範囲・共) 固有ユニット (パーサ import)
# ===========================================================


def test_circular_config_sochi_gensen() -> None:
    mod = _import_parser()
    assert "sochi-gensen" in mod.CIRCULAR_CONFIGS
    cfg = mod.CIRCULAR_CONFIGS["sochi-gensen"]
    assert cfg.law_abbrev == "sochi-gensen-tsutatsu"
    assert cfg.law_name_ja == "租税特別措置法に係る所得税の取扱い（源泉所得税関係）"
    # 株式等譲渡編と同型 hierarchical・2 レベル (条-番号)。款括弧なし・混在レベルなし (P0-2)。
    assert cfg.num_style == "hierarchical"
    assert cfg.num_levels == 2
    assert cfg.exclude_files == frozenset()
    # named-law ガードで corpus_unregistered は非空 (裸「法/令」偽リンク回避)。
    assert cfg.corpus_unregistered == _NAMED_LAW_UNREG
    # ref_map は実本文の表記 (probe-don't-guess・P0-2): 源泉所得税は所得税分野ゆえ裸「法」= 所得税法。
    assert cfg.ref_map["措置法"] == "sochi-hou"
    assert cfg.ref_map["措置法令"] == "sochi-hou-shikkourei"
    assert cfg.ref_map["法"] == "shotoku-zei-hou"
    assert cfg.ref_map["令"] == "shotoku-zei-hou-shikkourei"
    assert cfg.ref_map["所得税法"] == "shotoku-zei-hou"
    # named-law は full 形で登録 (長い接頭辞優先で裸「法」へ潰れない)。
    assert cfg.ref_map["財形法"] == "kinrousha-zaisan-keisei-sokushin-hou"
    assert cfg.ref_map["外為法"] == "gaikoku-kawase-oyobi-gaikoku-boueki-hou"
    assert cfg.ref_map["賃金支払確保法"] == "chingin-shiharai-kakuho-hou"


def test_directive_id_ok_hierarchical_forms() -> None:
    """hierarchical 形式ゲート (num_levels=2): 条-番号・共・の 枝番を受理・裸番号を拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-gensen"]
    ok = mod._directive_id_ok
    assert ok("sochi-gensen-tsutatsu-4の2-1", cfg)  # 条-番号
    assert ok("sochi-gensen-tsutatsu-41の12の2-1", cfg)  # 条二重枝番
    assert ok("sochi-gensen-tsutatsu-4の2-15の2", cfg)  # 番号枝番 (の 保持)
    assert ok("sochi-gensen-tsutatsu-41の10_41の12共-1", cfg)  # 条跨ぎ範囲 + 共
    assert not ok("sochi-gensen-tsutatsu-41", cfg)  # 裸番号 (番号レベル欠落)
    assert not ok("sochi-kabushiki-tsutatsu-4の2-1", cfg)  # prefix 不一致


# --- 合成 HTML による抽出パス (中黒範囲・共・named-law 偽マッチ回避・zenbun 除外) ---

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
            "sochi-gensen",
            "--cache-root",
            str(cache_root),
            "--output-dir",
            str(out_dir),
        ]
    )
    out = out_dir / "sochi-gensen-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


def test_range_kyo_directive(tmp_path: Path) -> None:
    """条跨ぎ範囲 (中黒・) + 共 番号が範囲区切り正規化で畳まれて取込まれる (41の10・41の12共-1 -> 41の10_41の12共-1)。

    hierarchical は kan_paren と違い款括弧を畳まない。共 は _LEVEL の (?:共)? 接尾で条番号レベルに
    直付き、範囲区切り 中黒「・」のみ _RANGE_SEP_RE で "_" に正規化される (実データ実測形)。
    cache は 2 桁章 dir (41) 直下に leaf (_CHAPTER_DIR_RE の \\d{2})。
    """
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(
        root / "41" / "10.htm",
        _page(("41の10・41の12共－1", "（共通）", "共通本文。")),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_id"] == "sochi-gensen-tsutatsu-41の10_41の12共-1"


def test_double_branch_directive(tmp_path: Path) -> None:
    """条二重枝番 (41の12の2-1) が の 保持で取込まれる."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "41" / "12.htm", _page(("41の12の2－1", "（甲）", "本文甲。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_number"] == "41の12の2-1"


def test_zenbun_fusoku_dirs_excluded(tmp_path: Path) -> None:
    """前文 zenbun / 附則 fusoku dir は _CHAPTER_DIR_RE 非該当で除外 (2 桁章 dir のみ収録)."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    # 現行 2 桁章 dir (03) と 前文 zenbun / 附則 fusoku を同居させ、章のみ捕捉を pin。
    _write(root / "03" / "01.htm", _page(("3-1", "（現行）", "現行本文。")))
    _write(root / "zenbun" / "01.htm", _page(("999-1", "（前文）", "前文本文。")))
    _write(root / "fusoku" / "01.htm", _page(("998-1", "（附則）", "附則本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert len(recs) == 1, (
        f"zenbun/fusoku が混入 (現行章のみのはず): {[r['source_url'] for r in recs]}"
    )
    assert "/03/" in recs[0]["source_url"]
    assert "/zenbun/" not in recs[0]["source_url"] and "/fusoku/" not in recs[0]["source_url"]


def test_named_law_not_falsely_linked_to_shotoku(tmp_path: Path) -> None:
    """named-law の 第N条 が裸「法」で所得税法へ偽リンクしない (unlinked 記録・誤リンク0)."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    # 財形法第10条 は裸「法」(所得税法) へ潰れず kinrousha-* の unlinked に落ちる。
    _write(
        root / "04" / "02.htm",
        _page(("4の2-1", "（甲）", "財形法第10条の規定による。")),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    refs = recs[0]["related_articles"]
    abbrevs = {r["law_abbrev"] for r in refs}
    assert "shotoku-zei-hou" not in abbrevs, f"財形法が所得税法へ偽リンク: {refs}"
    assert "kinrousha-zaisan-keisei-sokushin-hou" in abbrevs, (
        f"named-law が unlinked 記録されていない: {refs}"
    )


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_ROOT.exists(),
    reason="NTA HTML cache (cache/tsutatsu/sochi-gensen/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "sochi-gensen",
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
    produced = out_dir / "sochi-gensen-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

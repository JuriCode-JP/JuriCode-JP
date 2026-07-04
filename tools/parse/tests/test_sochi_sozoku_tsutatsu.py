"""test_sochi_sozoku_tsutatsu.py -- 租税特別措置法関係通達 (相続税法の特例関係) 取込のゲート (FU-541).

Why this test exists:
    措置法通達(相続税特例編・080708)は相続税分野の個別通達で、山林所得・譲渡所得編 (sochi-joto)
    と同じ hierarchical・num_levels=2 (条-番号)。款括弧を持たず (P0-2)、条跨ぎ範囲は 中黒「・」+ 共通
    (69の6・69の7共-1) で書かれ、既存 _RANGE_SEP_RE の ・->_ 正規化 + _LEVEL の (?:共)? 接尾により
    追加コードなしで 69の6_69の7共-1 へ畳まれる。本文には別法令 (中小企業信用保険法/会社法/農地法/
    郵政民営化法 等) が 第N条 で現れるため、裸「法/令」の偽マッチを避けるべく named-law を full 形で
    ref_map + corpus_unregistered に登録し unlinked 記録する (誤リンク0・SOUZOKU/HYOKA/SHOTOKU 同型)。

    3 層構成:
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・
          directive_id ユニーク・件数 963・参照母集団 (linked 2197 / unlinked 78=named-law) を pin。
      (2) hierarchical 固有ユニット (パーサ import・合成 HTML): 中黒範囲 + 共 (69の6・69の7共->
          69の6_69の7共)・二重枝番 (70の2の2-3の2)・named-law の裸「法」偽マッチ回避。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-sozoku で subprocess 実行し baseline と byte 一致を assert。

    NB (既知の完全性ギャップ・佐藤へ停止報告→accept-gap 確定 2026-07-04): 本編は同一編内で 2 レベル
    (条-通達 69の4-27) と 3 レベル (条-項-通達) を混在させる。措置法70条1項/3項関係の現行 18 件
    (70-1-1..70-1-14 / 70-3-1..70-3-4) は 3 レベルゆえ num_levels=2 では未収録・旧措置法70の3の3系 7 件
    は「旧」始まりで未収録。corpus は 2 レベル現行分 963 で確定 (3 レベル可変 tail 対応は follow-up)。

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
_BASELINE = _THIS.parent / "fixtures" / "sochi-sozoku-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_ROOT = _REPO_ROOT / "cache" / "tsutatsu" / "sochi-sozoku"

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

# P0-3 実測・佐藤ロック (2026-07-04)。58 leaf 中 54 が directive 産出 (soft-404 0)・2 レベル現行 963。
_LOCKED_COUNT = 963
_LOCKED_LINKED = (
    2197  # 措置法系 + 相続税法系 + 所得税法系 + 法人税法 + 通則法 は全件 corpus 実在 -> link
)
_LOCKED_UNLINKED = (
    78  # named-law (中小企業信用保険法/会社法/農地法 等) は corpus 未収録 -> unlinked 記録
)
_SOURCE_PREFIX = "https://www.nta.go.jp/law/tsutatsu/kobetsu/sozoku/sochiho/080708/"

# link 先 (corpus 実在・data/v0.2/phase1-tax)。相続税法特例編ゆえ裸「法」= 相続税法。
_LINKED_ALLOWED = frozenset(
    {
        "sochi-hou",
        "sochi-hou-shikkourei",
        "sochi-hou-shikoukisoku",
        "souzoku-zei-hou",
        "souzoku-zei-hou-shikkourei",
        "souzoku-zei-hou-shikoukisoku",
        "shotoku-zei-hou",
        "shotoku-zei-hou-shikkourei",
        "houjin-zei-hou",
        "kokuzei-tsuusoku-hou",
    }
)

# named-law ガード: 本文に 第N条 で現れる別法令を full 形で登録し裸「法/令」偽マッチを回避 (誤リンク0)。
_NAMED_LAW_UNREG = frozenset(
    {
        "chusho-kigyo-shinyou-hoken-hou",
        "nogyo-keiei-kiban-kyouka-sokushin-hou",
        "dokuritsu-gyousei-houjin-nougyousha-nenkin-kikin-hou",
        "tokutei-hieiri-katsudou-sokushin-hou",
        "shimin-nouen-seibi-sokushin-hou",
        "sangyou-kyousouryoku-kyouka-hou",
        "yuubinkyoku-kabushiki-gaisha-hou",
        "yuusei-mineika-hou",
        "kaisha-keisan-kisoku",
        "kaisha-hou",
        "nouchi-hou",
        "shinrin-hou-shikoukisoku",
        "shinrin-hou",
        "seisan-ryokuchi-hou",
        "toshi-keikaku-hou",
        "iryou-hou",
        "koyou-hoken-hou",
        "fudousan-touki-kisoku",
        "chihou-jichi-hou",
        "shakuchi-shakuya-hou",
        "bunkazai-hogo-hou",
        "chihou-zei-hou",
        "kyu-sochi-hou",
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
        f"措置法通達 (相続税特例編) の chunk 数は {_LOCKED_COUNT} "
        "(58 leaf・2 レベル現行分・3 レベル 18 件と旧法 7 件は num_levels=2 の構造制約で未収録)"
    )


def test_ref_population_linked_and_named_law_unlinked() -> None:
    """措置法系 + 相続税法系 + 所得税法系 + 法人税法 + 通則法 は全 link、named-law は unlinked 記録 (誤リンク0)."""
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


def test_pipeline_fields_are_sochi_sozoku() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "租税特別措置法関係通達（相続税法の特例関係）"
        assert rec["law_abbrev"] == "sochi-sozoku-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith(_SOURCE_PREFIX)


def test_directive_id_all_pass_format_gate() -> None:
    """全 directive_id が hierarchical 形式ゲート (num_levels=2・共/の 枝番許容) を通る."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-sozoku"]
    for rec in _read_baseline():
        assert mod._directive_id_ok(rec["directive_id"], cfg), (
            f"directive_id が形式ゲート違反: {rec['directive_id']!r}"
        )


def test_cross_article_range_kyo_marker_present() -> None:
    """条跨ぎ範囲 (中黒・) + 共通 が畳まれた id が存在する (69の6・69の7共-1 -> 69の6_69の7共-1)."""
    ids = {r["directive_id"] for r in _read_baseline()}
    assert "sochi-sozoku-tsutatsu-69の6_69の7共-1" in ids, (
        "条跨ぎ範囲 (中黒) + 共 の畳み込み id が欠落"
    )


def test_double_branch_present() -> None:
    """二重枝番 (条・番号とも「の」枝番) が保持される (70の2の2-3の2)."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert "70の2の2-3の2" in nums, "二重枝番 (70の2の2-3の2) が欠落"


def test_69no4_series_present_for_cross_domain_link() -> None:
    """taxanswer link 対象 (69の4 系・小規模宅地等) が corpus に実在する (69の4-27/69の4-28)."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert "69の4-27" in nums, "69の4-27 が欠落 (sozoku taxanswer の link 対象)"
    assert "69の4-28" in nums, "69の4-28 が欠落 (継続参照 '28' の解決対象)"


# ===========================================================
# (2) hierarchical (中黒範囲・共) 固有ユニット (パーサ import)
# ===========================================================


def test_circular_config_sochi_sozoku() -> None:
    mod = _import_parser()
    assert "sochi-sozoku" in mod.CIRCULAR_CONFIGS
    cfg = mod.CIRCULAR_CONFIGS["sochi-sozoku"]
    assert cfg.law_abbrev == "sochi-sozoku-tsutatsu"
    assert cfg.law_name_ja == "租税特別措置法関係通達（相続税法の特例関係）"
    # 山林所得・譲渡所得編と同型 hierarchical・2 レベル (条-番号)。款括弧なし (P0-2)。
    assert cfg.num_style == "hierarchical"
    assert cfg.num_levels == 2
    assert cfg.exclude_files == frozenset()
    # named-law ガードで corpus_unregistered は非空 (裸「法/令」偽リンク回避)。
    assert cfg.corpus_unregistered == _NAMED_LAW_UNREG
    # ref_map は実本文の表記 (probe-don't-guess・P0-2): 相続税特例編ゆえ裸「法」= 相続税法。
    assert cfg.ref_map["措置法"] == "sochi-hou"
    assert cfg.ref_map["措置法令"] == "sochi-hou-shikkourei"
    assert cfg.ref_map["法"] == "souzoku-zei-hou"
    assert cfg.ref_map["相続税法"] == "souzoku-zei-hou"
    assert cfg.ref_map["通則法"] == "kokuzei-tsuusoku-hou"
    # named-law は full 形で登録 (長い接頭辞優先で裸「法」へ潰れない)。
    assert cfg.ref_map["中小企業信用保険法"] == "chusho-kigyo-shinyou-hoken-hou"
    assert cfg.ref_map["会社法"] == "kaisha-hou"


def test_directive_id_ok_hierarchical_forms() -> None:
    """hierarchical 形式ゲート (num_levels=2): 条-番号・共・の 枝番を受理・裸番号を拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-sozoku"]
    ok = mod._directive_id_ok
    assert ok("sochi-sozoku-tsutatsu-69の4-27", cfg)  # 条-番号
    assert ok("sochi-sozoku-tsutatsu-70の2の2-3の2", cfg)  # 二重枝番 (の 保持)
    assert ok("sochi-sozoku-tsutatsu-69の6_69の7共-1", cfg)  # 条跨ぎ範囲 (中黒) + 共
    assert not ok("sochi-sozoku-tsutatsu-69", cfg)  # 裸番号 (番号レベル欠落)
    assert not ok("sochi-joto-tsutatsu-69の4-27", cfg)  # prefix 不一致


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
            "sochi-sozoku",
            "--cache-root",
            str(cache_root),
            "--output-dir",
            str(out_dir),
        ]
    )
    out = out_dir / "sochi-sozoku-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


def test_range_kyo_directive(tmp_path: Path) -> None:
    """条跨ぎ範囲 (中黒・) + 共 番号が範囲区切り正規化で畳まれて取込まれる (69の6・69の7共-1 -> 69の6_69の7共-1)。

    hierarchical は kan_paren と違い款括弧を畳まない。共 は _LEVEL の (?:共)? 接尾で条番号レベルに
    直付き、範囲区切り 中黒「・」のみ _RANGE_SEP_RE で "_" に正規化される (実データ実測形)。
    """
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "69_6" / "01.htm", _page(("69の6・69の7共－1", "（共通）", "共通本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_id"] == "sochi-sozoku-tsutatsu-69の6_69の7共-1"


def test_double_branch_directive(tmp_path: Path) -> None:
    """二重枝番 (70の2の2-3の2) が の 保持で取込まれる."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "70_2" / "02.htm", _page(("70の2の2－3の2", "（甲）", "本文甲。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_number"] == "70の2の2-3の2"


def test_named_law_not_falsely_linked_to_souzoku(tmp_path: Path) -> None:
    """named-law の 第N条 が裸「法」で相続税法へ偽リンクしない (unlinked 記録・誤リンク0)."""
    mod = _import_parser()
    root = tmp_path / "sochi"
    # 中小企業信用保険法第3条 は裸「法」(相続税法) へ潰れず chusho-* の unlinked に落ちる。
    _write(
        root / "70_7" / "01.htm",
        _page(("70の7-1", "（甲）", "中小企業信用保険法第3条の規定による。")),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    refs = recs[0]["related_articles"]
    abbrevs = {r["law_abbrev"] for r in refs}
    assert "souzoku-zei-hou" not in abbrevs, f"中小企業信用保険法が相続税法へ偽リンク: {refs}"
    assert "chusho-kigyo-shinyou-hoken-hou" in abbrevs, (
        f"named-law が unlinked 記録されていない: {refs}"
    )


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_ROOT.exists(),
    reason="NTA HTML cache (cache/tsutatsu/sochi-sozoku/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "sochi-sozoku",
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
    produced = out_dir / "sochi-sozoku-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

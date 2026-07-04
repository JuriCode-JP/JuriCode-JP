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
          directive_id ユニーク・件数 981・参照母集団 (linked 2228 / unlinked 80=named-law) を pin。
      (2) hier_var 固有ユニット (パーサ import・合成 HTML): 中黒範囲 + 共 (69の6・69の7共->
          69の6_69の7共)・二重枝番 (70の2の2-3の2)・2 レベル/3 レベル可変捕捉 (69の4-27 / 70-1-3)・
          旧法除外・over-capture なし・named-law の裸「法」偽マッチ回避。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-sozoku で subprocess 実行し baseline と byte 一致を assert。

    NB (レベル混在・FU-541 で停止報告→FU-543 で num_style="hier_var" 導入で捕捉・佐藤承認どおり):
    本編は同一編内で 2 レベル (条-通達 69の4-27) と 3 レベル (条-項-通達 70-1-3 = 70条1項 通達3) を
    混在させる。num_levels 固定では両立できないため、FU-543 で dash-level を {1,2} で可変に組む gated
    num_style "hier_var" を導入し現行 18 件 (70条1項 70-1-1..14 = 14 件 + 70条3項 70-3-1..4 = 4 件) を
    捕捉 (corpus 963->981)。旧措置法70の3の3系 7 件は「旧」始まりで除外維持 (旧法=現行条番号と不一致)。
    hier_var は gated (sochi-sozoku 専用) ゆえ他 6 編の byte 出力は完全不変 (byte 回帰 test で実証)。

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

# P0 実測・佐藤ロック (FU-543 2026-07-04)。58 leaf・hier_var で 2 レベル 963 + 3 レベル現行 18 = 981。
_LOCKED_COUNT = 981
_LOCKED_LINKED = (
    2228  # 措置法系 + 相続税法系 + 所得税法系 + 法人税法 + 通則法 は全件 corpus 実在 -> link
)
_LOCKED_UNLINKED = (
    80  # named-law (中小企業信用保険法/会社法/農地法 等) は corpus 未収録 -> unlinked 記録
)
# FU-543 hier_var で捕捉した現行 3 レベル 18 件 (措置法70条1項 14 + 70条3項 4)。
_CURRENT_3LEVEL = frozenset(
    [f"70-1-{i}" for i in range(1, 15)] + [f"70-3-{i}" for i in range(1, 5)]
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
        "(58 leaf・hier_var で 2 レベル 963 + 3 レベル現行 18 = 981・旧法 7 件は「旧」始まりで除外)"
    )


def test_current_3level_captured_and_old_excluded() -> None:
    """FU-543 hier_var: 3 レベル現行 18 件 (70条1項/3項) を捕捉・旧法 (「旧」始まり) は除外・over-capture なし。

    2 レベル既存分 (69の4-N 等) は下限 1 で従来同一列を返す (byte 回帰 test で 963 不変を実証済)。
    本 test は 3 レベル現行 18 件が漏れなく収録され、かつ旧法が誤って混入しないことを pin する。
    """
    nums = {r["directive_number"] for r in _read_baseline()}
    missing = _CURRENT_3LEVEL - nums
    assert not missing, f"現行 3 レベル (70条1項/3項) が欠落: {sorted(missing)}"
    old_law = {n for n in nums if n.startswith("旧")}
    assert not old_law, f"旧法 (「旧」始まり) が誤収録 (除外すべき): {sorted(old_law)}"
    # over-capture ガード: 3 レベル (dash 2 個) は 70条1項/3項 18 件のみ (他条は 2 レベル = dash 1 個)。
    # 想定外の N-M-K を弾く (hier_var {1,2} の可変が 2 レベルを 3 レベル化していないことの証跡)。
    three_level = {n for n in nums if n.count("-") == 2}
    assert three_level == _CURRENT_3LEVEL, (
        f"3 レベル directive が想定 (70条1項/3項 18 件) と不一致: "
        f"想定外={sorted(three_level - _CURRENT_3LEVEL)} 欠落={sorted(_CURRENT_3LEVEL - three_level)}"
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
    # FU-543: 2 レベル (69の4-27) と 3 レベル (70-1-3) 混在ゆえ hier_var (可変 {1,2})。款括弧なし (P0-2)。
    assert cfg.num_style == "hier_var"
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


def test_directive_id_ok_hier_var_forms() -> None:
    """hier_var 形式ゲート (可変 {1,2}): 2 レベル/3 レベル・共・の 枝番を受理・裸番号を拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-sozoku"]
    ok = mod._directive_id_ok
    assert ok("sochi-sozoku-tsutatsu-69の4-27", cfg)  # 2 レベル (条-番号)
    assert ok("sochi-sozoku-tsutatsu-70-1-3", cfg)  # 3 レベル (条-項-通達・FU-543)
    assert ok("sochi-sozoku-tsutatsu-70-3-4", cfg)  # 3 レベル (70条3項)
    assert ok("sochi-sozoku-tsutatsu-70の2の2-3の2", cfg)  # 二重枝番 (の 保持)
    assert ok("sochi-sozoku-tsutatsu-69の6_69の7共-1", cfg)  # 条跨ぎ範囲 (中黒) + 共
    assert not ok("sochi-sozoku-tsutatsu-69", cfg)  # 裸番号 (番号レベル欠落)
    assert not ok("sochi-sozoku-tsutatsu-70-1-3-9", cfg)  # 4 レベル (over-capture 拒否)
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


def test_hier_var_captures_2_and_3_levels(tmp_path: Path) -> None:
    """hier_var (可変 {1,2}): 2 レベル (69の4-27) と 3 レベル (70-1-3 = 70条1項 通達3) を同一 config で捕捉。

    FU-543 の本丸。num_levels 固定では両立できない 2/3 レベル混在を dash-level {1,2} で吸収する。
    2 レベルが 3 レベル化しない (over-capture なし) ことも同時に pin。
    """
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(root / "69_4" / "01.htm", _page(("69の4－27", "（甲）", "2 レベル本文。")))
    _write(root / "70_1" / "01.htm", _page(("70－1－3", "（乙）", "3 レベル本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    nums = {r["directive_number"] for r in recs}
    assert "69の4-27" in nums, "2 レベルが捕捉されていない"
    assert "70-1-3" in nums, "3 レベル (70条1項 通達3) が捕捉されていない"


def test_hier_var_excludes_old_law(tmp_path: Path) -> None:
    """旧法 (「旧」始まり) は数値開始の _FIRST_LEVEL に非マッチで除外される (旧70の3の3・70の3の4-1)。

    現行 directive (70-3-4) と旧法を同居させ、現行のみ捕捉・旧法は非収録を pin する (旧法単独ページは
    「no directive」で parser が fail-loud になるため、現行と混在させて除外を検証する)。
    """
    mod = _import_parser()
    root = tmp_path / "sochi"
    _write(
        root / "70_3" / "03.htm",
        _page(
            ("70－3－4", "（現行）", "現行3レベル本文。"),
            ("旧70の3の3・70の3の4－1", "（丙）", "旧法本文。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    nums = {r["directive_number"] for r in recs}
    assert "70-3-4" in nums, "現行 3 レベルが捕捉されていない"
    assert not any(n.startswith("旧") for n in nums), f"旧法が誤収録: {sorted(nums)}"


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

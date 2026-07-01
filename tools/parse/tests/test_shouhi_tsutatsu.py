"""test_shouhi_tsutatsu.py -- 消費税法基本通達 (第1章) 取込のゲート.

Why this test exists:
    消費税法基本通達は parse-nta-tsutatsu.py を CircularConfig でパラメータ化して取込む
    (法人税通達と同一パーサ)。法人税の byte 回帰 (test_tsutatsu_byte_regression.py) と
    対をなし、本ファイルは消費税側の構造健全性を保証する。

    2 層構成 (hojin と同型):
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・
          directive_id ユニーク・件数・参照母集団を pin。
      (2) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular shouhi で subprocess 実行し baseline と byte 一致を assert。

    加えて消費税固有のエッジを unit test:
      - CircularConfig 選択 (法人/消費税で正しい定数)。
      - split-strong (CASE B): 番号が <strong>1</strong>-1-1 に分割される節 (1-1/1-2)
        が取りこぼされず存在する。
      - title-lag 修正 + 削除エッジ: 見出しが本文に整合 (次項の見出しを誤取得しない)。
      - amendment_marker (課消) で改正注記が本文から分離される。

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
_BASELINE = _THIS.parent / "fixtures" / "shouhi-kihon-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_DIR = _REPO_ROOT / "cache" / "tsutatsu" / "shohi" / "01"

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


def _import_parser():
    """Import the hyphenated parser module by path (taxanswer テストと同パターン)."""
    spec = importlib.util.spec_from_file_location("parse_nta_tsutatsu", _PARSER)
    mod = importlib.util.module_from_spec(spec)
    # dataclass(CircularConfig) + `from __future__ import annotations` は文字列注釈の
    # 解決に sys.modules[__module__] を要するため、exec_module 前に登録する。
    sys.modules[spec.name] = mod
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
    assert len(_read_baseline()) == 93, "第1章 (8 節) の chunk 数は 93"


def test_ref_population_linked_only() -> None:
    """第1章は 法/令 のみ参照で全件 corpus 内 -> linked 165 / unlinked 0 を pin."""
    linked = unlinked = 0
    abbrevs: set[str] = set()
    for rec in _read_baseline():
        for ref in rec["related_articles"]:
            if set(ref.keys()) == LINKED_REF_KEYS:
                linked += 1
                abbrevs.add(ref["law_abbrev"])
            elif set(ref.keys()) == UNLINKED_REF_KEYS:
                unlinked += 1
    assert (linked, unlinked) == (165, 0), f"ref 母集団が変化: linked={linked} unlinked={unlinked}"
    assert abbrevs <= {"shouhi-zei-hou", "shouhi-zei-hou-shikkourei", "shouhi-zei-hou-shikoukisoku"}


def test_pipeline_fields_are_shouhi() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "消費税法基本通達"
        assert rec["law_abbrev"] == "shouhi-kihon-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith("https://www.nta.go.jp/law/tsutatsu/kihon/shohi/")


def test_split_strong_sections_present() -> None:
    """CASE B (split-strong) が無いと取りこぼす節 1-1 / 1-2 が存在する."""
    sections = {"-".join(r["directive_number"].split("-")[:2]) for r in _read_baseline()}
    assert {"1-1", "1-2"} <= sections, f"split-strong 節が欠落: {sorted(sections)}"
    assert sections == {f"1-{i}" for i in range(1, 9)}, "第1章は 1-1..1-8 の 8 節"


def test_title_not_lagged() -> None:
    """title-lag 修正: 見出しが本文と整合 (次項の見出しを誤取得しない)."""
    recs = {r["directive_number"]: r for r in _read_baseline()}
    # 1-2-1 は「法人でない社団」、見出しも社団 (旧バグでは次項 1-2-2 の「財団」を誤取得)
    assert recs["1-2-1"]["title"] == "（法人でない社団の範囲）"
    assert "社団" in recs["1-2-1"]["text"]


def test_amendment_note_extracted_with_shouhi_marker() -> None:
    """amendment_marker=課消 で改正注記が本文から分離される (本文末尾に残らない)."""
    import re

    recs = _read_baseline()
    with_amend = [r for r in recs if r["amendment_note"]]
    assert with_amend, "改正注記が 1 件も抽出されていない (課消 marker 不発?)"
    for r in recs:
        assert not re.search(r"（[^）]*課消[^）]*）\s*$", r["text"]), (
            f"{r['directive_number']}: 改正注記が本文末尾に残存 (分離漏れ)"
        )


# ===========================================================
# (2) CircularConfig unit (パーサ import)
# ===========================================================


def test_circular_config_registry() -> None:
    mod = _import_parser()
    assert set(mod.CIRCULAR_CONFIGS) == {"hojin", "shouhi", "shotoku", "souzoku"}
    hojin = mod.CIRCULAR_CONFIGS["hojin"]
    shouhi = mod.CIRCULAR_CONFIGS["shouhi"]
    assert hojin.law_abbrev == "hojin-kihon-tsutatsu"
    assert hojin.amendment_markers == ("課法", "直法")
    assert hojin.num_levels == 3  # 既定 (章-節-項)
    assert shouhi.law_abbrev == "shouhi-kihon-tsutatsu"
    assert shouhi.law_name_ja == "消費税法基本通達"
    assert shouhi.source_url_base == "https://www.nta.go.jp/law/tsutatsu/kihon/shohi"
    assert shouhi.amendment_markers == ("課消",)
    assert shouhi.num_levels == 3
    assert shouhi.ref_map["法"] == "shouhi-zei-hou"
    assert shouhi.ref_map["令"] == "shouhi-zei-hou-shikkourei"
    # 所得税基本通達は 2 レベル (条-番号) + 官総 を含む改正記号 (FU-523)。
    shotoku = mod.CIRCULAR_CONFIGS["shotoku"]
    assert shotoku.law_abbrev == "shotoku-kihon-tsutatsu"
    assert shotoku.law_name_ja == "所得税法基本通達"
    assert shotoku.source_url_base == "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku"
    assert shotoku.num_levels == 2
    assert "官総" in shotoku.amendment_markers
    assert shotoku.ref_map["法"] == "shotoku-zei-hou"
    # 相続税基本通達 (FU-524)。2 レベル (条-番号) + sisan/sozoku2 パス + 資産税系記号 +
    # 多字接頭辞 (措置法/通則法/所得税法/地価税法) を config.ref_map で切替。
    souzoku = mod.CIRCULAR_CONFIGS["souzoku"]
    assert souzoku.law_abbrev == "souzoku-kihon-tsutatsu"
    assert souzoku.law_name_ja == "相続税法基本通達"
    assert souzoku.source_url_base == "https://www.nta.go.jp/law/tsutatsu/kihon/sisan/sozoku2"
    assert souzoku.num_levels == 2
    assert souzoku.amendment_markers == ("課資", "直資", "課審", "課評")
    assert souzoku.ref_map["法"] == "souzoku-zei-hou"
    assert souzoku.ref_map["措置法"] == "sochi-hou"
    assert souzoku.ref_map["通則法"] == "kokuzei-tsuusoku-hou"
    assert souzoku.corpus_unregistered == frozenset({"sochi-hou", "chika-zei-hou"})


def test_related_articles_use_config_refmap() -> None:
    """同一本文でも config の ref_map で参照先 law_abbrev が切替わる."""
    mod = _import_parser()
    text = "法第9条第1項の規定により、令第20条に定める。"
    hojin = mod._extract_related_articles(text, mod.CIRCULAR_CONFIGS["hojin"])
    shouhi = mod._extract_related_articles(text, mod.CIRCULAR_CONFIGS["shouhi"])
    assert {r["law_abbrev"] for r in hojin} == {"houjin-zei-hou", "houjin-zei-hou-shikkourei"}
    assert {r["law_abbrev"] for r in shouhi} == {"shouhi-zei-hou", "shouhi-zei-hou-shikkourei"}


def test_build_law_ref_re_prefix_priority() -> None:
    """config 駆動 ref 正規表現 (_build_law_ref_re) が長い接頭辞を優先する (FU-524).

    Why: 措置法第N条 を「法」に潰さず 措置法 として捕捉するのが FU-524 の中核。
    hojin のキー集合 {法,令,規,措法} では 措置法 は内側の「法」にマッチ (従来挙動 =
    byte 不変)、souzoku のキー集合では 措置法/通則法 を独立接頭辞として捕捉する。
    """
    mod = _import_parser()
    text = "措置法第70条の規定及び通則法第5条、法第9条による。"
    # souzoku: 措置法/通則法 を独立接頭辞で解決 (法へ潰さない)
    souzoku = mod._extract_related_articles(text, mod.CIRCULAR_CONFIGS["souzoku"])
    got = {r["raw"]: r["law_abbrev"] for r in souzoku}
    assert got.get("措置法第70条") == "sochi-hou"
    assert got.get("通則法第5条") == "kokuzei-tsuusoku-hou"
    assert got.get("法第9条") == "souzoku-zei-hou"
    # hojin: 措置法 はキーに無いため内側の「法」= houjin-zei-hou に潰れる (従来挙動・byte 不変)
    hojin = mod._extract_related_articles(text, mod.CIRCULAR_CONFIGS["hojin"])
    hojin_raw = {r["raw"] for r in hojin}
    assert "措置法第70条" not in hojin_raw  # 措置法 単位では拾わない
    assert "法第70条" in hojin_raw  # 内側の「法第70条」として拾う (従来と同じ)


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_DIR.exists(),
    reason="NTA HTML cache (cache/tsutatsu/shohi/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "shouhi",
            "--cache-dir",
            str(_CACHE_DIR),
            "--output-dir",
            str(out_dir),
            "--chapter",
            "01",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, f"parser 失敗 (rc={result.returncode}):\n{result.stderr}"
    produced = out_dir / "shouhi-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

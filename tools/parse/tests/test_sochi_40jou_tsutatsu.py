"""test_sochi_40jou_tsutatsu.py -- 租税特別措置法関係通達(第40条 取扱い) 取込のゲート (FU-547).

Why this test exists:
    措法40条取扱通達(800423・直資2-181・昭55.4.23)は所得税(譲渡所得)分野の個別通達で、01.htm=目次・
    02..23.htm=本文という flat 構成。本文ページの href が base 相対 1 セグメントゆえ既存 BFS では 0 leaf
    になり、fetcher の toc_content モード (目次から content ページを拾う) で取得する。directive 番号は
    財産評価通達と同じ **flat 通し番号 1..52 + の枝番 8** (19の2/20の2/20の3/23の2/23の3/23の4/24の2/
    27の2) = 60。「40条」は directive 番号でなく h2 セクション見出し〔措置法第40条第N項関係〕にのみ現れる
    (hierarchical ではない)。本文は <h2>(title) + <p><strong>N</strong>本文 の既存 flat_branch が処理し、
    strong-gate が (注) 平文番号 "1"/"2" を排除する (num_levels=1 の膨張を起こさない)。附則 22.htm は
    <li> 構造ゆえ <p><strong> 抽出に非該当で自然に 0 件 (dup "1" 自動回避・本則 60)。本文には別法令
    (一般社団・財団法人法/公益認定法/整備法/社会福祉法/医療法(施行規則)/更生保護事業法/博物館法/学校
    教育法/児童福祉法/介護保険法/特定非営利活動促進法) が 第N条 で現れるため、裸「法」の偽マッチを避ける
    べく named-law を full 形で ref_map + corpus_unregistered に登録し unlinked 記録する (誤リンク0)。

    3 層構成:
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・
          directive_id ユニーク・件数 60・参照母集団 (linked 106 / unlinked 15=named-law) を pin。
      (2) flat_branch 固有ユニット (パーサ import・合成 HTML): strong-gate による (注) 平文番号除外・
          の枝番 (19の2)・附則 <li> 除外・named-law の裸「法」偽マッチ回避。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-40jou --cache-dir <flat> --chapter "" で subprocess 実行し baseline と byte 一致。

    NB: content は flat (02..23.htm) ゆえ parse は --cache-dir + --chapter "" (source_url=base/NN.htm)。
    --cache-root は flat top-level を _CHAPTER_DIR_RE で除外するため使わない。

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
_BASELINE = _THIS.parent / "fixtures" / "sochi-40jou-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_DIR = _REPO_ROOT / "cache" / "tsutatsu" / "sochi-40jou"

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

# PS-3 実測・佐藤ロック (2026-07-04)。24 content ページ (02..23.htm) から本則 60 directive
# (flat 1..52 + の枝番 8)。附則 22.htm は <li> 構造ゆえ 0 件。
_LOCKED_COUNT = 60
_LOCKED_LINKED = 106  # 措置法系 + 所得税/法人税/通則系 は全件 corpus 実在 -> link
_LOCKED_UNLINKED = 15  # named-law (団体法系) は corpus 未収録 -> unlinked 記録 (誤リンク0)
_SOURCE_PREFIX = "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/800423/"

# link 先 (corpus 実在・data/v0.2/phase1-tax)。40条は譲渡所得ゆえ裸「法」= 所得税法。
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

# named-law ガード: 本文に 第N条 で現れる別法令を full 形で登録し裸「法」偽マッチを回避 (誤リンク0)。
_NAMED_LAW_UNREG = frozenset(
    {
        "ippan-shadan-zaidan-houjin-hou",
        "koueki-nintei-hou",
        "seibi-hou",
        "shakai-fukushi-hou",
        "iryou-hou-shikoukisoku",
        "iryou-hou",
        "kousei-hogo-jigyou-hou",
        "hakubutsukan-hou",
        "gakkou-kyouiku-hou",
        "jidou-fukushi-hou",
        "kaigo-hoken-hou",
        "tokutei-hieiri-katsudou-sokushin-hou",
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
        f"措法40条取扱通達 の chunk 数は {_LOCKED_COUNT} (本則 flat 1..52 + の枝番 8・附則 22.htm は除外)"
    )


def test_ref_population_linked_and_named_law_unlinked() -> None:
    """措置法系 + 所得税/法人税/通則系 は全 link、named-law は unlinked 記録 (誤リンク0)."""
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
    # unlinked は named-law ガードのみ (裸「法」偽リンクが混入していない証跡)。
    assert unlinked_abbrevs <= _NAMED_LAW_UNREG, (
        f"想定外の unlinked law_abbrev (偽リンク疑い): {unlinked_abbrevs}"
    )


def test_pipeline_fields_are_sochi_40jou() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "租税特別措置法関係通達（第40条 取扱い）"
        assert rec["law_abbrev"] == "sochi-40jou-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith(_SOURCE_PREFIX)


def test_directive_id_all_pass_format_gate() -> None:
    """全 directive_id が flat_branch 形式ゲート (単発番号 + の枝番) を通る."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-40jou"]
    for rec in _read_baseline():
        assert mod._directive_id_ok(rec["directive_id"], cfg), (
            f"directive_id が形式ゲート違反: {rec['directive_id']!r}"
        )


def test_flat_number_range_and_branches_present() -> None:
    """flat 通し番号 1..52 が全て在り、の枝番 8 種が存在する (PS-3 実測 60)."""
    nums = {r["directive_number"] for r in _read_baseline()}
    for n in range(1, 53):
        assert str(n) in nums, f"flat 通し番号 {n} が欠落"
    for br in ("19の2", "20の2", "20の3", "23の2", "23の3", "23の4", "24の2", "27の2"):
        assert br in nums, f"の枝番 {br} が欠落"


def test_no_fusoku_directive_and_number_1_once() -> None:
    """附則(経過的取扱い)は <li> 構造ゆえ 0 件。本則 "1" は 1 度だけ (附則 "1" と衝突しない)."""
    nums = [r["directive_number"] for r in _read_baseline()]
    assert nums.count("1") == 1, "本則 '1' が重複 (附則 '1' が混入した疑い)"
    for rec in _read_baseline():
        # 附則 22.htm 由来の record が無いこと (経過的取扱いタイトルは本則に無い)。
        assert "経過的取扱い" not in rec["title"], f"附則が混入: {rec['directive_id']}"


# ===========================================================
# (2) flat_branch (strong-gate) 固有ユニット (パーサ import)
# ===========================================================


def test_circular_config_sochi_40jou() -> None:
    mod = _import_parser()
    assert "sochi-40jou" in mod.CIRCULAR_CONFIGS
    cfg = mod.CIRCULAR_CONFIGS["sochi-40jou"]
    assert cfg.law_abbrev == "sochi-40jou-tsutatsu"
    assert cfg.law_name_ja == "租税特別措置法関係通達（第40条 取扱い）"
    # 財産評価通達と同じ flat_branch (単発通し番号 + strong-gate)。hierarchical ではない。
    assert cfg.num_style == "flat_branch"
    assert cfg.exclude_files == frozenset()
    # named-law ガードで corpus_unregistered は非空 (裸「法」偽リンク回避)。
    assert cfg.corpus_unregistered == _NAMED_LAW_UNREG
    # ref_map は実本文の表記 (probe-don't-guess・PS-6): 40条は譲渡所得ゆえ裸「法」= 所得税法。
    assert cfg.ref_map["措置法"] == "sochi-hou"
    assert cfg.ref_map["措令"] == "sochi-hou-shikkourei"  # NTA 短縮表記 措令 (PS-6: 71 件)
    assert cfg.ref_map["法"] == "shotoku-zei-hou"
    assert cfg.ref_map["法人税法"] == "houjin-zei-hou"
    # named-law は full 形で登録 (長い接頭辞優先で裸「法」へ潰れない)。
    assert cfg.ref_map["一般社団・財団法人法"] == "ippan-shadan-zaidan-houjin-hou"
    assert cfg.ref_map["社会福祉法"] == "shakai-fukushi-hou"
    assert cfg.ref_map["医療法"] == "iryou-hou"


def test_directive_id_ok_flat_branch_forms() -> None:
    """flat_branch 形式ゲート: 単発番号・の枝番を受理・多レベル (条-番号-番号) を拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-40jou"]
    ok = mod._directive_id_ok
    assert ok("sochi-40jou-tsutatsu-1", cfg)  # 単発番号
    assert ok("sochi-40jou-tsutatsu-52", cfg)  # 単発番号
    assert ok("sochi-40jou-tsutatsu-19の2", cfg)  # の枝番
    assert ok("sochi-40jou-tsutatsu-23の4", cfg)  # の枝番
    assert not ok("sochi-40jou-tsutatsu-40-3-2", cfg)  # 多 dash-level (flat_branch は単一枝まで)
    assert not ok("sochi-gensen-tsutatsu-1", cfg)  # prefix 不一致


# --- 合成 HTML による抽出パス (strong-gate・の枝番・附則 <li> 除外・named-law 偽マッチ回避) ---

_PAGE_TMPL = """<html><head><meta charset="shift_jis"></head><body>
<div id="bodyArea">
<h1>ページ見出し</h1>
{items}
</div></body></html>"""


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _run(mod, cache_dir: Path, out_dir: Path) -> tuple[int, list[dict]]:
    """flat cache を --cache-dir + --chapter "" で読む (source_url=base/NN.htm・実運用と同経路)."""
    rc = mod.main(
        [
            "--circular",
            "sochi-40jou",
            "--cache-dir",
            str(cache_dir),
            "--chapter",
            "",
            "--output-dir",
            str(out_dir),
        ]
    )
    out = out_dir / "sochi-40jou-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


def test_flat_branch_strong_gate_excludes_note_numbers(tmp_path: Path) -> None:
    """strong-gate: <strong> 内番号のみ通達開始。(注) の平文番号 "1"/"2" は本文へ蓄積 (誤検出しない)."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items=(
            "<h2>（実質判定）</h2>\n"
            "<p><strong>5</strong>　措置法第40条に規定する判定は次による。</p>\n"
            "<p>(注)</p>\n"
            "<p>1　上記の取扱いは要件を満たす場合に限る。</p>\n"
            "<p>2　設立準備委員会等に対するものを含む。</p>"
        )
    ).encode("cp932")
    _write(cache / "07.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    assert len(recs) == 1, f"(注) 平文番号が誤検出された: {[r['directive_number'] for r in recs]}"
    assert recs[0]["directive_number"] == "5"
    # (注) 本文が directive 5 の本文へ蓄積されている。
    assert "上記の取扱い" in recs[0]["text"]


def test_no_branch_directive(tmp_path: Path) -> None:
    """の枝番 (19の2) が strong-gate で取込まれる."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items="<h2>（株式）</h2>\n<p><strong>19の2</strong>　措令第25条の17第6項に規定する株式。</p>"
    ).encode("cp932")
    _write(cache / "09.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    assert recs[0]["directive_number"] == "19の2"


def test_fusoku_li_structure_excluded(tmp_path: Path) -> None:
    """附則の <li> 構造 (<li><strong>1</strong>...) は <p><strong> 抽出に非該当で 0 件 (dup 回避)."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items=(
            "<h2>（経過的取扱い）</h2>\n"
            "<ul><li><strong>1</strong> この通達は令和7年4月1日以降に適用する。</li></ul>"
        )
    ).encode("cp932")
    _write(cache / "22.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    # 0 directive -> parser は "no directive items produced" で rc=1 だが record は 0。
    assert recs == [], f"附則 <li> が directive として抽出された: {recs}"


def test_named_law_not_falsely_linked_to_shotoku(tmp_path: Path) -> None:
    """named-law の 第N条 が裸「法」で所得税法へ偽リンクしない (unlinked 記録・誤リンク0)."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    # 一般社団・財団法人法第2条 は裸「法」(所得税法) へ潰れず ippan-* の unlinked に落ちる。
    html = _PAGE_TMPL.format(
        items="<h2>（適正判定）</h2>\n<p><strong>18</strong>　一般社団・財団法人法第2条の規定による。</p>"
    ).encode("cp932")
    _write(cache / "09.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    refs = recs[0]["related_articles"]
    abbrevs = {r["law_abbrev"] for r in refs}
    assert "shotoku-zei-hou" not in abbrevs, f"named-law が所得税法へ偽リンク: {refs}"
    assert "ippan-shadan-zaidan-houjin-hou" in abbrevs, (
        f"named-law が unlinked 記録されていない: {refs}"
    )


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_DIR.exists(),
    reason="NTA HTML cache (cache/tsutatsu/sochi-40jou/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "sochi-40jou",
            "--cache-dir",
            str(_CACHE_DIR),
            "--chapter",
            "",
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
    produced = out_dir / "sochi-40jou-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

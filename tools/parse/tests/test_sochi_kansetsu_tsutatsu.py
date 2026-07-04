"""test_sochi_kansetsu_tsutatsu.py -- 租税特別措置法関係通達(間接諸税関係) 取込のゲート (FU-551).

Why this test exists:
    間接諸税措通(990625・平11.6.25 課消4-15 ほか)は揮発油税/石油石炭税/航空機燃料税/自動車重量税/
    印紙税の間接諸税に係る個別通達。他 4 num_style と根本的に異なる **section_scoped** で取込む:
    directive 番号は <p>/<li><strong>N</strong> の running 番号 (各 <h1> グループで 1 からリセット) で、
    条は <h1> 節/条見出しから解決する (租特法第88条の7《…》関係 -> 88の7)。<h1> の 4 形態 =
      1. 単一条   租特法第88条の7《…》関係                       -> 88の7
      2. 範囲共通 第1節 …第90条の3の4から第90条の6の3共通関係     -> 90の3の4_90の6の3共
      3. 併記     …第90条の8の2《…》及び第90条の9…               -> 90の8の2 (先頭条 primary)
      4. 条なし章 第4章 自動車重量税の還付措置関係 (h1 に条なし)    -> section_article_overrides["4"]=90の15
    01.htm=目次・02..08.htm 系=本文の flat 構成 (fetcher toc_content・FU-547 流用)。頁順≠章順
    (06=第3章・07 系=第5章・08=第4章)。全 directive = 72 (第1章 揮発 7 / 第2章 石油石炭 34 /
    第3章 航空機燃料 13 / 第4章 自動車重量 2 / 第5章 印紙 16)。directive の一部は <ol><li><strong>N</strong>
    にラップされる (04.htm 90の5-5) ため走査タグに li を含める (nested block 除外で二重計上回避)。

    補完条 90の15 の根拠: 08.htm 本文は 租特令第51条の5 を引き、data/v0.2 の 措法施行令51条の5 は
    「法第九十条の十五第一項に規定する…」と明記＝親条は 措法90条の15 (自動車重量税還付・使用済自動車)。
    90条の12 は自動車重量税の免除/軽減 (エコカー減税) で別制度ゆえ不採用。

    ref_map は本文実測 (PS-5): 租特法/租特令/租特規則 の 3 系のみ。裸「法/令/規」第N条 は本文にゼロ
    ゆえ named-law (航空機燃料税法等) が裸「法」へ潰れる経路が構造的に存在せず、誤リンク0 が自明に
    成立する (他編の named-law ガードは裸「法」がある編の対策で本編は不要・corpus_unregistered 空)。

    3 層構成:
      (1) committed baseline fixture (CI-safe) への構造監査: 14 キー順・disjoint Union・directive_id
          ユニーク・件数 72・章別内訳 (7/34/13/2/16)・参照母集団 (linked 96 / unlinked 0)・エッジ3種
          (範囲共通/併記/条なし章) を pin。
      (2) section_scoped 固有ユニット (パーサ import・合成 HTML): 節→条 resolver 4 分岐・running 番号
          strong-gate・<li> ラップ directive の取込・章/節 nav 境界・title 束縛。
      (3) byte 回帰 (ローカル限定): NTA HTML cache (gitignored) が在れば parser を
          --circular sochi-kansetsu --cache-dir <flat> --chapter "" で subprocess 実行し baseline と byte 一致。

    NB: content は flat (02..08.htm 系) ゆえ parse は --cache-dir + --chapter "" (source_url=base/NN.htm)。

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
_BASELINE = _THIS.parent / "fixtures" / "sochi-kansetsu-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_DIR = _REPO_ROOT / "cache" / "tsutatsu" / "sochi-kansetsu"

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

# PS 実測・佐藤ロック (2026-07-04)。14 content ページから 72 directive。
_LOCKED_COUNT = 72
_LOCKED_LINKED = 96  # 租特法系 (措法/措令/措規) は全件 corpus 実在 (data/v0.2/phase1-tax) -> link
_LOCKED_UNLINKED = 0  # 裸「法/令/規」が本文にゼロ -> named-law 偽リンク経路なし・unlinked も 0
_SOURCE_PREFIX = "https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/sochiho/990625/"

# link 先 (corpus 実在・data/v0.2/phase1-tax)。間接諸税は措置法横断ゆえ ref は租特法系のみ。
_LINKED_ALLOWED = frozenset(
    {
        "sochi-hou",
        "sochi-hou-shikkourei",
        "sochi-hou-shikoukisoku",
    }
)

# 章別内訳 (佐藤ロック)。directive_number の条部から章を判定する。
_CHAPTER_LOCKED = {"1": 7, "2": 34, "3": 13, "4": 2, "5": 16}

# エッジ3種の代表 directive_number (baseline pin)。
_EDGE_RANGE_KYOTSU = "90の3の4_90の6の3共-1"  # 範囲共通 (03.htm 第2章第1節・4 件)
_EDGE_HEIKI = "90の8の2-13"  # 併記 (06.htm 第3章・先頭条 90の8の2 primary・13 件)
_EDGE_CHAPTER_NOART = "90の15-1"  # 条なし章 (08.htm 第4章・補完条 90の15・2 件)


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


def _chapter_of(article: str) -> str:
    """directive_number の条部 -> 章番号 (990625 の章構成に基づく決定的マップ)."""
    if article.startswith("88"):
        return "1"
    if article.startswith(("90の3の4", "90の5", "90の6")):
        return "2"
    if article.startswith("90の8"):
        return "3"
    if article.startswith("90の15"):
        return "4"
    if article.startswith("91"):
        return "5"
    return "?"


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
        f"間接諸税措通 の chunk 数は {_LOCKED_COUNT} (第1章7/第2章34/第3章13/第4章2/第5章16)"
    )


def test_chapter_breakdown_locked() -> None:
    """章別内訳 7/34/13/2/16 を pin (佐藤 Tier S ロック・PS-4 実測)."""
    counts: dict[str, int] = {}
    for rec in _read_baseline():
        article = rec["directive_number"].rsplit("-", 1)[0]
        counts[_chapter_of(article)] = counts.get(_chapter_of(article), 0) + 1
    assert counts == _CHAPTER_LOCKED, f"章別内訳が変化: {counts} (期待 {_CHAPTER_LOCKED})"


def test_ref_population_all_linked_no_false_links() -> None:
    """租特法系は全 link、unlinked は 0 (裸「法」不在ゆえ named-law 偽リンク経路なし・誤リンク0)."""
    linked = unlinked = 0
    linked_abbrevs: set[str] = set()
    for rec in _read_baseline():
        for ref in rec["related_articles"]:
            if set(ref.keys()) == LINKED_REF_KEYS:
                linked += 1
                linked_abbrevs.add(ref["law_abbrev"])
            elif set(ref.keys()) == UNLINKED_REF_KEYS:
                unlinked += 1
    assert (linked, unlinked) == (_LOCKED_LINKED, _LOCKED_UNLINKED), (
        f"ref 母集団が変化: linked={linked} unlinked={unlinked}"
    )
    assert linked_abbrevs <= _LINKED_ALLOWED, f"想定外の link 先 law_abbrev: {linked_abbrevs}"


def test_pipeline_fields_are_sochi_kansetsu() -> None:
    for rec in _read_baseline():
        assert rec["law_name_ja"] == "租税特別措置法関係通達（間接諸税関係）"
        assert rec["law_abbrev"] == "sochi-kansetsu-tsutatsu"
        assert rec["license"] == "public-domain-13-2"
        assert rec["segment_type"] == "tsutatsu"
        assert rec["article_id"] is None
        assert rec["source_url"].startswith(_SOURCE_PREFIX)


def test_directive_id_all_pass_format_gate() -> None:
    """全 directive_id が section_scoped 形式ゲート (<条>-<running>) を通る."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-kansetsu"]
    for rec in _read_baseline():
        assert mod._directive_id_ok(rec["directive_id"], cfg), (
            f"directive_id が形式ゲート違反: {rec['directive_id']!r}"
        )


def test_edge_three_forms_present() -> None:
    """エッジ3種 (範囲共通/併記/条なし章) の代表 directive が baseline に在る (佐藤ロック)."""
    nums = {r["directive_number"] for r in _read_baseline()}
    assert _EDGE_RANGE_KYOTSU in nums, "範囲共通 (90の3の4_90の6の3共) が欠落"
    assert _EDGE_HEIKI in nums, "併記 (90の8の2 先頭条 primary・13 件目) が欠落"
    assert _EDGE_CHAPTER_NOART in nums, "条なし章 (自動車重量税 補完条 90の15) が欠落"
    # 範囲共通は 4 件・条なし章は 2 件で確定 (章別内訳の内訳固定)。
    range_kyotsu = sum(1 for n in nums if n.startswith("90の3の4_90の6の3共-"))
    assert range_kyotsu == 4, f"範囲共通 directive 数が 4 でない: {range_kyotsu}"
    heiki = sum(1 for n in nums if n.startswith("90の8の2-"))
    assert heiki == 13, f"併記 (90の8の2) directive 数が 13 でない: {heiki}"
    noart = sum(1 for n in nums if n.startswith("90の15-"))
    assert noart == 2, f"条なし章 (90の15) directive 数が 2 でない: {noart}"


def test_no_fullwidth_digit_in_directive_id_running() -> None:
    """条部は全角数字を半角化 (88の７ -> 88の7)。id に全角数字が残っていない."""
    for rec in _read_baseline():
        num = rec["directive_number"]
        assert not any("０" <= c <= "９" for c in num), (
            f"全角数字が directive_number に残存: {num!r}"
        )


# ===========================================================
# (2) section_scoped 固有ユニット (パーサ import)
# ===========================================================


def test_circular_config_sochi_kansetsu() -> None:
    mod = _import_parser()
    assert "sochi-kansetsu" in mod.CIRCULAR_CONFIGS
    cfg = mod.CIRCULAR_CONFIGS["sochi-kansetsu"]
    assert cfg.law_abbrev == "sochi-kansetsu-tsutatsu"
    assert cfg.law_name_ja == "租税特別措置法関係通達（間接諸税関係）"
    assert cfg.num_style == "section_scoped"
    # 裸「法」不在ゆえ named-law ガード不要 (corpus_unregistered 空・誤リンク0 は構造的に成立)。
    assert cfg.corpus_unregistered == frozenset()
    # ref_map は租特法系 3 系のみ (probe-don't-guess・PS-5)。
    assert cfg.ref_map == {
        "租特法": "sochi-hou",
        "租特令": "sochi-hou-shikkourei",
        "租特規則": "sochi-hou-shikoukisoku",
    }
    # 条なし章 (第4章 自動車重量税還付) の補完条 = 措法90の15。
    assert cfg.section_article_overrides == {"4": "90の15"}
    # 改正記号は 課消 のみ (間接諸税は消費税課所管・実測 84 件)。
    assert cfg.amendment_markers == ("課消",)


def test_resolve_section_article_four_branches() -> None:
    """節→条 resolver の 4 分岐 (単一/範囲共通/併記/条なし章)."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-kansetsu"]
    r = mod._resolve_section_article
    # 1. 単一条 (全角７ を含む NTA 表記ゆれも半角化)
    assert r("租特法第88条の７《バイオエタノール等…》関係", "1", cfg) == "88の7"
    assert r("第2節 租特法第90条の5《…》関係", "2", cfg) == "90の5"
    # 2. 範囲共通 (先頭_末尾共)
    assert r("第1節 租特法第90条の3の4から第90条の6の3共通関係", "2", cfg) == "90の3の4_90の6の3共"
    assert r("第1節 租特法第91条から第91条の4共通関係", "5", cfg) == "91_91の4共"
    # 3. 併記 (及び・先頭条を primary)
    assert r("租特法第90条の8の2《…》及び第90条の9《…》関係", "3", cfg) == "90の8の2"
    # 4. 条なし章 (h1 に条なし -> override)
    assert r("第4章 自動車重量税の還付措置関係", "4", cfg) == "90の15"
    # 未登録章の条なし = None (directive を作らない)
    assert r("第9章 未知の税関係", "9", cfg) is None


def test_directive_id_ok_section_scoped_forms() -> None:
    """section_scoped 形式ゲート: <条>-<running> を受理・多レベルや prefix 不一致を拒否."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["sochi-kansetsu"]
    ok = mod._directive_id_ok
    assert ok("sochi-kansetsu-tsutatsu-88の7-1", cfg)  # 単一条
    assert ok("sochi-kansetsu-tsutatsu-90の3の4_90の6の3共-4", cfg)  # 範囲共通
    assert ok("sochi-kansetsu-tsutatsu-90の8の2-13", cfg)  # 併記
    assert ok("sochi-kansetsu-tsutatsu-90の15-2", cfg)  # 条なし章補完
    assert not ok("sochi-kansetsu-tsutatsu-88の7-1-2", cfg)  # 多 dash-level は不可
    assert not ok("sochi-kansetsu-tsutatsu-88の7", cfg)  # running 番号欠落
    assert not ok("sochi-40jou-tsutatsu-1", cfg)  # prefix 不一致


# --- 合成 HTML による抽出パス (running strong-gate・h1 条解決・li 取込・nav 境界・title 束縛) ---

_PAGE_TMPL = """<html><head><meta charset="shift_jis"></head><body>
<div id="bodyArea">
{items}
</div></body></html>"""


def _run(mod, cache_dir: Path, out_dir: Path) -> tuple[int, list[dict]]:
    """flat cache を --cache-dir + --chapter "" で読む (source_url=base/NN.htm・実運用と同経路)."""
    rc = mod.main(
        [
            "--circular",
            "sochi-kansetsu",
            "--cache-dir",
            str(cache_dir),
            "--chapter",
            "",
            "--output-dir",
            str(out_dir),
        ]
    )
    out = out_dir / "sochi-kansetsu-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_running_number_scoped_to_h1_article(tmp_path: Path) -> None:
    """running 番号 (1,2) が <h1> 解決条にスコープされ <条>-<running> になる (title 束縛も検証)."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items=(
            "<p><strong>第1章 揮発油税の課税標準特例関係</strong></p>\n"
            "<h1>租特法第88条の7《バイオエタノール等…》関係</h1>\n"
            "<h2>（用語の意義）</h2>\n"
            "<p><strong>1</strong>　この章において用いる用語の意義は次による。</p>\n"
            "<h2>（端数計算）</h2>\n"
            "<p><strong>2</strong>　租特法第88条の7第1項の規定により控除する。</p>"
        )
    ).encode("cp932")
    _write(cache / "02.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["88の7-1", "88の7-2"]
    # title 束縛 (lag なし): 1 は「用語の意義」・2 は「端数計算」。
    assert recs[0]["title"] == "（用語の意義）"
    assert recs[1]["title"] == "（端数計算）"
    # 本文先頭の running 番号は剥がされる。
    assert recs[0]["text"].startswith("この章において")
    # 租特法参照は link される。
    assert any(a.get("article_id") == "sochi-hou-art-88-7" for a in recs[1]["related_articles"])


def test_li_wrapped_directive_captured(tmp_path: Path) -> None:
    """<ol><li><strong>N</strong> にラップされた directive も取込む (04.htm 90の5-5 型)."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items=(
            "<h1>第3節 租特法第90条の5《…》関係</h1>\n"
            "<h2>（範囲）</h2>\n"
            "<p><strong>1</strong>　特定揮発油等の範囲は次による。</p>\n"
            "<h2>（数量）</h2>\n"
            '<ol class="lst_none"><li><strong>2　</strong>(1)　特定揮発油を原料に供する場合\n'
            '<p class="indent1">当該数量は投入量とする。</p></li></ol>'
        )
    ).encode("cp932")
    _write(cache / "04.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["90の5-1", "90の5-2"]
    # li ラップ directive の本文 (nested <p> 含む) が取込まれている。
    assert "特定揮発油を原料に供する場合" in recs[1]["text"]
    assert "投入量" in recs[1]["text"]


def test_chapter_nav_echo_is_boundary(tmp_path: Path) -> None:
    """ページ末尾の章/節 nav エコー (<p><strong>第N章…</strong>) が直前 directive に吸い込まれない."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items=(
            "<h1>租特法第88条の7《…》関係</h1>\n"
            "<h2>（意義）</h2>\n"
            "<p><strong>1</strong>　本文である。</p>\n"
            "<p><strong>第1章 揮発油税の課税標準特例関係</strong></p>\n"
            "<p><strong>租税特別措置法（間接諸税関係）の取扱いについて（法令解釈通達）の発遣について</strong> 目次へ戻る</p>"
        )
    ).encode("cp932")
    _write(cache / "02.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    assert len(recs) == 1
    assert recs[0]["directive_number"] == "88の7-1"
    # nav エコーの文言が本文に混入していない。
    assert "目次へ戻る" not in recs[0]["text"]
    assert "課税標準特例関係" not in recs[0]["text"]


def test_chapter_without_article_uses_override(tmp_path: Path) -> None:
    """条なし章 (h1 が章見出しで条なし) は section_article_overrides で補完条を用いる."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items=(
            "<h1>第4章 自動車重量税の還付措置関係</h1>\n"
            "<h2>（有効期間）</h2>\n"
            "<p><strong>1</strong>　租特令第51条の5第3項に規定する有効期間をいう。</p>"
        )
    ).encode("cp932")
    _write(cache / "08.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["90の15-1"]


def test_bare_law_absent_no_false_link(tmp_path: Path) -> None:
    """named-law (航空機燃料税法) の 第N条 は裸「法」で措法へ偽リンクしない (ref_map に裸「法」なし)."""
    mod = _import_parser()
    cache = tmp_path / "cache"
    html = _PAGE_TMPL.format(
        items=(
            "<h1>租特法第90条の8の2《…》及び第90条の9《…》関係</h1>\n"
            "<h2>（測定）</h2>\n"
            "<p><strong>1</strong>　航空機燃料税法第14条に規定する申告書による。</p>"
        )
    ).encode("cp932")
    _write(cache / "06.htm", html)
    rc, recs = _run(mod, cache, tmp_path / "out")
    assert rc == 0
    abbrevs = {a["law_abbrev"] for a in recs[0]["related_articles"]}
    # 航空機燃料税法第14条 は ref_map に無い -> 参照として抽出されず、措法への偽リンクもない。
    assert "sochi-hou" not in abbrevs, (
        f"航空機燃料税法が措法へ偽リンク: {recs[0]['related_articles']}"
    )


# ===========================================================
# (3) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_DIR.exists(),
    reason="NTA HTML cache (cache/tsutatsu/sochi-kansetsu/, gitignored) 不在 -- byte 回帰は push 前ローカル",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--circular",
            "sochi-kansetsu",
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
    produced = out_dir / "sochi-kansetsu-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"
    assert produced.read_bytes() == _BASELINE.read_bytes(), (
        "出力が baseline とバイト不一致. 直すのはパーサ/データであって baseline ではない."
    )

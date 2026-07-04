"""test_taxanswer_related.py -- TDD tests for TaxAnswer related extraction.

Expected values are maintainer-locked (source-verified against NTA TaxAnswer).
DO NOT modify expected values without maintainer approval (R40).

Hermetic (FU-520): the tsutatsu directive corpus that extract_related_from_kikon
checks membership against is normally loaded from build/chunks (gitignored, absent
in CI). To run this test in CI without that runtime artifact, _import_extractor()
injects a tiny committed corpus fixture (fixtures/taxanswer-tsutatsu-corpus.min.jsonl)
into the module's corpus cache, so the test never touches build/chunks. The fixture
is the minimal set of directive_numbers the locked expectations require to be linked
(9-2-9..9-2-38 subset); 9-2-1 / 9-2-45 / 9-2-46 are intentionally absent so they
resolve as unlinked. The fixture is locked: if this test fails, fix the code, not
the fixture/expected values.
"""

from __future__ import annotations

# Import under test (will be implemented in parse-nta-taxanswer.py)
# We import the extraction functions via sys.path manipulation after the
# module is created. For now, define the interface expected.
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "src"))

# ---------------------------------------------------------------------------
# Helpers imported lazily (module does not exist yet -- TDD: tests first)
# ---------------------------------------------------------------------------


# Minimal committed tsutatsu corpus fixture (FU-520): the set of directive_numbers
# the locked expectations require to be LINKED. Injected into the module's corpus
# cache so the test is hermetic (no build/chunks dependency). Locked snapshot.
_MIN_CORPUS = Path(__file__).resolve().parent / "fixtures" / "taxanswer-tsutatsu-corpus.min.jsonl"


def _load_min_corpus() -> set[str]:
    import json

    nums: set[str] = set()
    for line in _MIN_CORPUS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            nums.add(json.loads(line)["directive_number"])
    return nums


def _import_extractor():
    """Lazy import + inject the committed corpus fixture (hermetic, FU-520).

    The module caches its tsutatsu corpus in the module-global _TSUTATSU_CORPUS
    (None until first _load_tsutatsu_corpus() call, which reads build/chunks). We set
    it to the committed fixture set right after import, so extract_related_from_kikon
    never touches build/chunks -- the test runs identically in CI and locally.

    2026-07-01 FU-527: _TSUTATSU_CORPUS is now nested {law_abbrev: {directive_number}}
    (multi-law resolution). The locked LOCK_CASES all use 法基通 -> hojin-kihon-tsutatsu,
    so we key the injected min-corpus under that abbrev. Expected values are unchanged;
    only the corpus container shape adapts to the parser's new internal representation.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "parse_nta_taxanswer",
        Path(__file__).resolve().parents[1] / "parse-nta-taxanswer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # inject before any extraction call (nested: 法基通 -> hojin-kihon-tsutatsu)
    mod._TSUTATSU_CORPUS = {"hojin-kihon-tsutatsu": _load_min_corpus()}
    return mod


# ---------------------------------------------------------------------------
# Fixtures: raw 根拠法令等 strings from lock table (basis: 8 HTM files)
# ---------------------------------------------------------------------------

LOCK_CASES = [
    # (code, raw_kikon, expected_articles, expected_directives, expected_unlinked_raws)
    # ------------------------------------------------------------------ 5200
    (
        "5200",
        "法法2、法令7、71、法基通9-2-1",
        [
            {"raw": "法法2", "article_id": "houjin-zei-hou-art-2"},
            {"raw": "法令7", "article_id": "houjin-zei-hou-shikkourei-art-7"},
            {"raw": "71", "article_id": "houjin-zei-hou-shikkourei-art-71"},  # prefix継承
        ],
        [],  # 法基通9-2-1 は未リンク(款01未取込) → directives空
        ["法基通9-2-1"],  # unlinked raws
    ),
    # ------------------------------------------------------------------ 5202
    (
        "5202",
        "法法22、34、法令69、70、法基通9-2-9～11、9-2-24",
        [
            {"raw": "法法22", "article_id": "houjin-zei-hou-art-22"},
            {"raw": "34", "article_id": "houjin-zei-hou-art-34"},
            {"raw": "法令69", "article_id": "houjin-zei-hou-shikkourei-art-69"},
            {"raw": "70", "article_id": "houjin-zei-hou-shikkourei-art-70"},
        ],
        [
            {"raw": "法基通9-2-9～11", "directive_id": "hojin-kihon-tsutatsu-9-2-9"},
            {"raw": "法基通9-2-9～11", "directive_id": "hojin-kihon-tsutatsu-9-2-10"},
            {"raw": "法基通9-2-9～11", "directive_id": "hojin-kihon-tsutatsu-9-2-11"},
            {"raw": "9-2-24", "directive_id": "hojin-kihon-tsutatsu-9-2-24"},
        ],
        [],  # no unlinked
    ),
    # ------------------------------------------------------------------ 5203
    (
        "5203",
        "法法34、法令70、法基通9-2-32、9-2-35～38",
        [
            {"raw": "法法34", "article_id": "houjin-zei-hou-art-34"},
            {"raw": "法令70", "article_id": "houjin-zei-hou-shikkourei-art-70"},
        ],
        [
            {"raw": "法基通9-2-32", "directive_id": "hojin-kihon-tsutatsu-9-2-32"},
            {"raw": "9-2-35～38", "directive_id": "hojin-kihon-tsutatsu-9-2-35"},
            {"raw": "9-2-35～38", "directive_id": "hojin-kihon-tsutatsu-9-2-36"},
            {"raw": "9-2-35～38", "directive_id": "hojin-kihon-tsutatsu-9-2-37"},
            {"raw": "9-2-35～38", "directive_id": "hojin-kihon-tsutatsu-9-2-38"},
        ],
        [],
    ),
    # ------------------------------------------------------------------ 5205
    (
        "5205",
        "法法34、法令71",
        [
            {"raw": "法法34", "article_id": "houjin-zei-hou-art-34"},
            {"raw": "法令71", "article_id": "houjin-zei-hou-shikkourei-art-71"},
        ],
        [],
        [],
    ),
    # ------------------------------------------------------------------ 5208
    (
        "5208",
        "法法34、法令70、法基通9-2-28、9-2-29",
        [
            {"raw": "法法34", "article_id": "houjin-zei-hou-art-34"},
            {"raw": "法令70", "article_id": "houjin-zei-hou-shikkourei-art-70"},
        ],
        [
            {"raw": "法基通9-2-28", "directive_id": "hojin-kihon-tsutatsu-9-2-28"},
            {"raw": "9-2-29", "directive_id": "hojin-kihon-tsutatsu-9-2-29"},
        ],
        [],
    ),
    # ------------------------------------------------------------------ 5210
    (
        "5210",
        "法法34、54、法令69、法規22の3、法基通9-2-13、平28改正法附則24、平29改正法附則14①",
        [
            {"raw": "法法34", "article_id": "houjin-zei-hou-art-34"},
            {"raw": "54", "article_id": "houjin-zei-hou-art-54"},
            {"raw": "法令69", "article_id": "houjin-zei-hou-shikkourei-art-69"},
            {"raw": "法規22の3", "article_id": "houjin-zei-hou-shikoukisoku-art-22-3"},
        ],
        [
            {"raw": "法基通9-2-13", "directive_id": "hojin-kihon-tsutatsu-9-2-13"},
        ],
        ["平28改正法附則24", "平29改正法附則14①"],  # 改正附則 = unlinked
    ),
    # ------------------------------------------------------------------ 5211
    (
        "5211",
        "法法34、54、54の2、法令69、71の2、71の3、111の2、111の3、法規22の3、法基通9-2-13、平29改正法附則14、15、平29改正令附則9、10、平29改正規則附則3、4",
        [
            {"raw": "法法34", "article_id": "houjin-zei-hou-art-34"},
            {"raw": "54", "article_id": "houjin-zei-hou-art-54"},
            {"raw": "54の2", "article_id": "houjin-zei-hou-art-54-2"},
            {"raw": "法令69", "article_id": "houjin-zei-hou-shikkourei-art-69"},
            {"raw": "71の2", "article_id": "houjin-zei-hou-shikkourei-art-71-2"},
            {"raw": "71の3", "article_id": "houjin-zei-hou-shikkourei-art-71-3"},
            {"raw": "111の2", "article_id": "houjin-zei-hou-shikkourei-art-111-2"},
            {"raw": "111の3", "article_id": "houjin-zei-hou-shikkourei-art-111-3"},
            {"raw": "法規22の3", "article_id": "houjin-zei-hou-shikoukisoku-art-22-3"},
        ],
        [
            {"raw": "法基通9-2-13", "directive_id": "hojin-kihon-tsutatsu-9-2-13"},
        ],
        # 改正附則 6件 = unlinked
        [
            "平29改正法附則14",
            "15",
            "平29改正令附則9",
            "10",
            "平29改正規則附則3",
            "4",
        ],
    ),
    # ------------------------------------------------------------------ 5245
    (
        "5245",
        "法基通9-2-45、9-2-46",
        [],  # no article refs
        [],  # directives both unlinked (款08/09 not ingested)
        ["法基通9-2-45", "9-2-46"],
    ),
]


# ---------------------------------------------------------------------------
# Helper: build sets for comparison
# ---------------------------------------------------------------------------


def _article_ids(result: dict) -> set[str]:
    return {r["article_id"] for r in result.get("related_articles", []) if r.get("article_id")}


def _directive_ids(result: dict) -> set[str]:
    return {
        r["directive_id"] for r in result.get("related_directives", []) if r.get("directive_id")
    }


def _unlinked_raws(result: dict) -> set[str]:
    unlinked = set()
    for r in result.get("related_articles", []):
        if not r.get("article_id"):
            unlinked.add(r["raw"])
    for r in result.get("related_directives", []):
        if not r.get("directive_id"):
            unlinked.add(r["raw"])
    # Also include items in the separate unlinked list (amendment proviso / corpus-missing)
    for r in result.get("unlinked", []):
        unlinked.add(r["raw"])
    return unlinked


# ---------------------------------------------------------------------------
# Parametrized tests (locked expected values -- DO NOT modify without approval)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,raw_kikon,exp_articles,exp_directives,exp_unlinked",
    LOCK_CASES,
    ids=[c[0] for c in LOCK_CASES],
)
def test_extract_related_from_kikon(code, raw_kikon, exp_articles, exp_directives, exp_unlinked):
    """Test related extraction from 根拠法令等 raw text (locked expected values)."""
    mod = _import_extractor()

    result = mod.extract_related_from_kikon(raw_kikon)

    got_article_ids = _article_ids(result)
    got_directive_ids = _directive_ids(result)
    got_unlinked = _unlinked_raws(result)

    expected_article_ids = {r["article_id"] for r in exp_articles}
    expected_directive_ids = {r["directive_id"] for r in exp_directives}
    expected_unlinked_set = set(exp_unlinked)

    assert got_article_ids == expected_article_ids, (
        f"[{code}] article_id mismatch\n"
        f"  got:      {sorted(got_article_ids)}\n"
        f"  expected: {sorted(expected_article_ids)}"
    )
    assert got_directive_ids == expected_directive_ids, (
        f"[{code}] directive_id mismatch\n"
        f"  got:      {sorted(got_directive_ids)}\n"
        f"  expected: {sorted(expected_directive_ids)}"
    )
    assert got_unlinked == expected_unlinked_set, (
        f"[{code}] unlinked_raw mismatch\n"
        f"  got:      {sorted(got_unlinked)}\n"
        f"  expected: {sorted(expected_unlinked_set)}"
    )


# ---------------------------------------------------------------------------
# Range expansion unit tests (R42)
# ---------------------------------------------------------------------------


def test_range_expansion_9_2_9_to_11():
    """9-2-9～11 expands to 9-2-9, 9-2-10, 9-2-11 (integer tail only, R42)."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法基通9-2-9～11")
    ids = _directive_ids(result)
    assert ids == {
        "hojin-kihon-tsutatsu-9-2-9",
        "hojin-kihon-tsutatsu-9-2-10",
        "hojin-kihon-tsutatsu-9-2-11",
    }, f"Range expansion failed: {ids}"


def test_range_expansion_9_2_35_to_38():
    """9-2-35～38 expands to 4 entries."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法基通9-2-35～38")
    ids = _directive_ids(result)
    assert ids == {
        "hojin-kihon-tsutatsu-9-2-35",
        "hojin-kihon-tsutatsu-9-2-36",
        "hojin-kihon-tsutatsu-9-2-37",
        "hojin-kihon-tsutatsu-9-2-38",
    }, f"Range expansion failed: {ids}"


def test_range_with_no_branch_endpoint_is_unlinked():
    """Range with の-branch endpoint (e.g. 9-2-9の2～11) must NOT expand (R34/R42)."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法基通9-2-9の2～11")
    ids = _directive_ids(result)
    unlinked = _unlinked_raws(result)
    # Should NOT produce linked directives; raw preserved as unlinked
    assert len(ids) == 0, f"Should not expand range with の-branch endpoint: {ids}"
    assert len(unlinked) > 0, "Should have unlinked entry for non-expandable range"


# ---------------------------------------------------------------------------
# Prefix inheritance unit tests (R41/連記継承)
# ---------------------------------------------------------------------------


def test_prefix_inheritance_houjin():
    """法法34、54 → both get houjin-zei-hou prefix."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法法34、54")
    ids = _article_ids(result)
    assert "houjin-zei-hou-art-34" in ids
    assert "houjin-zei-hou-art-54" in ids


def test_prefix_inheritance_shikkourei():
    """法令71、2 → both get shikkourei prefix (not 法法)."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法令71、2")
    ids = _article_ids(result)
    assert "houjin-zei-hou-shikkourei-art-71" in ids
    assert "houjin-zei-hou-shikkourei-art-2" in ids
    # Must not produce houjin-zei-hou-art-2
    assert "houjin-zei-hou-art-2" not in ids


def test_prefix_inheritance_tsutatsu():
    """法基通9-2-28、9-2-29 → both get tsutatsu prefix."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法基通9-2-28、9-2-29")
    ids = _directive_ids(result)
    assert "hojin-kihon-tsutatsu-9-2-28" in ids
    assert "hojin-kihon-tsutatsu-9-2-29" in ids


# ---------------------------------------------------------------------------
# No-branch multi-level の unit tests (R41/R43)
# ---------------------------------------------------------------------------


def test_no_branch_article_id():
    """法規22の3 → houjin-zei-hou-shikoukisoku-art-22-3 (R43: -art- not -article-)."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法規22の3")
    ids = _article_ids(result)
    assert "houjin-zei-hou-shikoukisoku-art-22-3" in ids


def test_no_branch_54no2():
    """法法54の2 → houjin-zei-hou-art-54-2."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("法法54の2")
    ids = _article_ids(result)
    assert "houjin-zei-hou-art-54-2" in ids


# ---------------------------------------------------------------------------
# Amendment/附則 = unlinked+warn (R40: no erroneously linked amendment refs)
# ---------------------------------------------------------------------------


def test_kaisei_funsoku_is_unlinked():
    """改正法附則 refs must be unlinked (not mapped to any corpus ID)."""
    mod = _import_extractor()
    result = mod.extract_related_from_kikon("平28改正法附則24、平29改正法附則14①")
    linked_articles = _article_ids(result)
    linked_directives = _directive_ids(result)
    assert len(linked_articles) == 0, f"Amendment should not be linked: {linked_articles}"
    assert len(linked_directives) == 0, f"Amendment should not be linked: {linked_directives}"
    unlinked = _unlinked_raws(result)
    assert len(unlinked) >= 2, f"Amendment refs should appear as unlinked: {unlinked}"


# ---------------------------------------------------------------------------
# related_qa extraction tests (R44: href-based, not body text)
# ---------------------------------------------------------------------------


def test_related_qa_from_href():
    """related_qa extracted from <a href='.../hojin/5210.htm'> (R44)."""
    mod = _import_extractor()
    html = """
    <h2>関連コード</h2>
    <ul>
      <li><a href="/taxes/shiraberu/taxanswer/hojin/5210.htm">5210 役員に対する給与...</a></li>
      <li><a href="/taxes/shiraberu/taxanswer/hojin/5211.htm">5211 役員に対する給与...</a></li>
    </ul>
    """
    qa = mod.extract_related_qa_from_html(html)
    assert set(qa) == {"5210", "5211"}, f"related_qa mismatch: {qa}"


def test_related_qa_relative_href():
    """related_qa works with relative href (5210.htm without full path)."""
    mod = _import_extractor()
    html = '<h2>関連コード</h2><a href="5210.htm">5210</a>'
    qa = mod.extract_related_qa_from_html(html)
    assert "5210" in qa, f"related_qa missing from relative href: {qa}"


def test_related_qa_no_false_positives_from_body():
    """Numbers in body text must NOT appear in related_qa (only href-based)."""
    mod = _import_extractor()
    html = """
    <h2>概要</h2>
    <p>法人税法第5211条の規定... No.5200参照</p>
    <h2>関連コード</h2>
    <a href="/taxes/shiraberu/taxanswer/hojin/5210.htm">5210</a>
    """
    qa = mod.extract_related_qa_from_html(html)
    assert qa == ["5210"], f"False positive in related_qa: {qa}"


# ---------------------------------------------------------------------------
# FU-538: 措通 (措置法通達・法人税編) の款(N)->-N 正規化 + gate (hermetic)
# ---------------------------------------------------------------------------


def _import_extractor_sochi():
    """FU-538: inject a tiny sochi-hojin-tsutatsu corpus (畳み込み形) to pin 款正規化 hermetically.

    taxanswer は措通を款括弧形 (措通61の4(1)-1) で書くが FU-536 corpus は畳み込み形 (61の4-1-1)。
    解決側の款 (N)/（N） -> -N 正規化を sochi-hojin-tsutatsu 限定で当てる挙動を、build/chunks に
    依存せず committed 集合で検証する (CI-safe)。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "parse_nta_taxanswer",
        Path(__file__).resolve().parents[1] / "parse-nta-taxanswer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # NB: corpus は directive_number 形 (の 保持)。directive_id は _build_directive_id が の->- 変換。
    mod._TSUTATSU_CORPUS = {
        "sochi-hojin-tsutatsu": {
            "61の4-1-1",
            "61の4-1-2",
            "64-2-1",
            "64-2-2",
            "67の5-1",
        }
    }
    return mod


def test_sochitsuu_kan_paren_single():
    """措通61の4(1)-1 -> sochi-hojin-tsutatsu-61-4-1-1 (款(1)->-1)。継承した裸番号も正規化される。"""
    mod = _import_extractor_sochi()
    ids = _directive_ids(mod.extract_related_from_kikon("措通61の4(1)-1、61の4(1)-2"))
    assert "sochi-hojin-tsutatsu-61-4-1-1" in ids
    assert "sochi-hojin-tsutatsu-61-4-1-2" in ids  # 措通継承 + 款正規化


def test_sochitsuu_kan_paren_range():
    """措通64(2)-1~2 -> 64-2-1, 64-2-2 (款正規化後にレンジ展開)。"""
    mod = _import_extractor_sochi()
    ids = _directive_ids(mod.extract_related_from_kikon("措通64(2)-1~2"))
    assert ids == {"sochi-hojin-tsutatsu-64-2-1", "sochi-hojin-tsutatsu-64-2-2"}, ids


def test_kan_normalization_gated_to_sochi():
    """gate: 款正規化は sochi-hojin-tsutatsu 限定。他 tsutatsu の同形は正規化しない (非 cross-cutting)。

    同一の款括弧形 99(1)-1 + 同一 corpus {99-1-1} を prefix だけ変えて与える。sochi は正規化されて
    99-1-1 に一致 -> link、法基通は正規化されず 99(1)-1 のまま -> 不一致で未リンク (gate 実証)。
    """
    mod = _import_extractor()
    # sochi: 正規化 (1)->-1 で 99-1-1 に一致 -> link
    mod._TSUTATSU_CORPUS = {"sochi-hojin-tsutatsu": {"99-1-1"}}
    assert "sochi-hojin-tsutatsu-99-1-1" in _directive_ids(
        mod.extract_related_from_kikon("措通99(1)-1")
    )
    # 法基通: 正規化されず 99(1)-1 のまま -> {99-1-1} に不一致で未リンク
    mod._TSUTATSU_CORPUS = {"hojin-kihon-tsutatsu": {"99-1-1"}}
    assert "hojin-kihon-tsutatsu-99-1-1" not in _directive_ids(
        mod.extract_related_from_kikon("法基通99(1)-1")
    )


# ---------------------------------------------------------------------------
# FU-539: 措通 の多編化 (カテゴリ厳格) + sochi-joto の中点(・)正規化 (hermetic)
# ---------------------------------------------------------------------------


def _import_extractor_joto():
    """FU-539: inject a tiny sochi-joto-tsutatsu corpus to pin カテゴリ厳格 + 中点正規化 hermetically.

    taxanswer は譲渡編措通を 中点 条-join 形 (措通31・32共-1) で書くが FU-539 corpus は _RANGE_SEP_RE
    で ・->_ を畳んだ形 (31_32共-1) を持つ。解決側の ・->_ 正規化を sochi-joto-tsutatsu 限定で
    当てる挙動 + 編がカテゴリで確定する挙動を、build/chunks に依存せず committed 集合で検証する。
    NB: corpus は directive_number 形 (の/共 保持・中点は _ 済)。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "parse_nta_taxanswer",
        Path(__file__).resolve().parents[1] / "parse-nta-taxanswer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._TSUTATSU_CORPUS = {
        "sochi-joto-tsutatsu": {
            "31_32共-1",
            "31の3-7",
            "31の3-8",
            "41の5-1",
            "33-31",
        }
    }
    return mod


def test_sochitsuu_joto_naka_kyo_single():
    """joto カテゴリ: 措通31・32共-1 -> sochi-joto-tsutatsu-31_32共-1 (中点 ・->_ 正規化)。"""
    mod = _import_extractor_joto()
    ids = _directive_ids(mod.extract_related_from_kikon("措通31・32共-1", "joto"))
    assert "sochi-joto-tsutatsu-31_32共-1" in ids, ids


def test_sochitsuu_joto_range():
    """joto カテゴリ: 措通31の3-7~8 -> 31の3-7, 31の3-8 (レンジ展開)。

    NB: corpus membership は directive_number 形 (の 保持) で照合するが、生成 directive_id は
    _build_directive_id が の->- 変換する (FU-538 と同一の非対称・link は number 照合で正)。
    """
    mod = _import_extractor_joto()
    ids = _directive_ids(mod.extract_related_from_kikon("措通31の3-7~8", "joto"))
    assert ids == {"sochi-joto-tsutatsu-31-3-7", "sochi-joto-tsutatsu-31-3-8"}, ids


def test_joto_edition_strict_by_category():
    """gate: 措通 の解決編はカテゴリ厳格。横断 fallback しない (佐藤裁定 2026-07-04)。

    同一 corpus {sochi-joto-tsutatsu: {41の5-1}} + 同一 措通41の5-1 を、カテゴリだけ変えて与える。
    joto カテゴリは sochi-joto 編へ解決 -> link。shotoku カテゴリは既定 sochi-hojin 編へ解決され
    (sochi-joto へ fallback しない) 未注入 corpus に無く未リンク (「他編 unlink 維持」を実証)。
    """
    mod = _import_extractor_joto()
    # joto: sochi-joto 編へ解決 -> link (directive_id は の->- 変換形)
    assert "sochi-joto-tsutatsu-41-5-1" in _directive_ids(
        mod.extract_related_from_kikon("措通41の5-1", "joto")
    )
    # shotoku: 既定 sochi-hojin 編へ解決・sochi-joto へ fallback しない -> 未リンク
    ids_shotoku = _directive_ids(mod.extract_related_from_kikon("措通41の5-1", "shotoku"))
    assert "sochi-joto-tsutatsu-41-5-1" not in ids_shotoku, ids_shotoku

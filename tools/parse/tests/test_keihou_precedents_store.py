"""test_keihou_precedents_store.py -- 刑法36条 判例 store + 付与ロジックの機械検証 (CI-safe).

Why (刑法パイロット WU2・2026-07-10): courts.go.jp probe + 佐藤 relevance ロック済みの
28 判例を committed store (data/v0.2/case-law/keihou/precedents.jsonl) に直接投入し、
keihou-article-36.md の frontmatter cases: に付与した。入力 JSON は gitignored (business/)
のため CI では再導出せず、本 test が committed 成果物への構造ゲートを担う:
  - store 全行が PrecedentStoreEntry として IR valid・28 件・case_id ユニーク・昇順・scj- prefix。
  - 佐藤ロック済み relevance 分布 (high 4 / medium 24) の fidelity gate。
  - D5 予約フィールド (overruled_by/modified_by) と cited_by が全行空 (populate は後段 FU)。
  - article 付与: cases: 28 件 == store と同一 id 集合・全件 PrecedentReference valid・
    relevant_paragraph は locked 6 件のみ (第1項 5 / 第2項 1)・本文セクション非改変は
    CI の verify.py (manifest hash) が担保。
builder ロジック (直接投入型) は fixture でオフライン検証する (web fetch なし)。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import PrecedentStoreEntry  # noqa: E402
from juricode_shared.ir import PrecedentReference  # noqa: E402

_STORE = _REPO_ROOT / "data" / "v0.2" / "case-law" / "keihou" / "precedents.jsonl"
_ARTICLE_MD = _REPO_ROOT / "data" / "v0.2" / "phase1-police" / "keihou" / "keihou-article-36.md"
_BUILDER_PATH = _REPO_ROOT / "tools" / "parse" / "build-keihou-precedents.py"
_FIXTURE = Path(__file__).parent / "fixtures" / "keihou36-attach-locked-FIXTURE.json"

# 佐藤ロック済み expected (2026-07-10)。変更には user 明示承認が必要。
_EXPECTED_TOTAL = 28
_EXPECTED_RELEVANCE = {"high": 4, "medium": 24}
_EXPECTED_RP_COUNTS = {1: 5, 2: 1}


def _load_builder():
    """ハイフン名モジュール build-keihou-precedents.py を importlib で読む (確立パターン)。"""
    spec = importlib.util.spec_from_file_location("build_keihou_precedents", _BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_store() -> list[dict]:
    if not _STORE.exists():
        pytest.skip(f"store not present: {_STORE}")
    rows = []
    for line in _STORE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _article_cases() -> list[dict]:
    fm_text = _ARTICLE_MD.read_text(encoding="utf-8").split("---\n", 2)[1]
    fm = yaml.safe_load(fm_text) or {}
    return fm.get("cases") or []


# --------------------------------------------------------------------------- #
# committed store gates
# --------------------------------------------------------------------------- #
def test_store_rows_all_valid_and_locked_shape() -> None:
    rows = _load_store()
    assert len(rows) == _EXPECTED_TOTAL
    ids = [r["case_id"] for r in rows]
    assert len(set(ids)) == _EXPECTED_TOTAL, "case_id が重複"
    assert ids == sorted(ids), "case_id 昇順でない"
    dist: dict[str, int] = {}
    for r in rows:
        entry = PrecedentStoreEntry(**r)
        assert entry.case_id.startswith("scj-")
        dist[r["relevance"]] = dist.get(r["relevance"], 0) + 1
    assert dist == _EXPECTED_RELEVANCE


def test_store_reserved_fields_empty_and_deferred_nulls() -> None:
    """D5 予約 (overruled_by/modified_by)・cited_by は空、summary_ja は D2 defer で null。"""
    for r in _load_store():
        assert r["overruled_by"] == []
        assert r["modified_by"] == []
        assert r["cited_by"] == []
        assert r["summary_ja"] is None
        assert r["relevant_paragraph"] is None, "rp は article 側のみに持つ (store は null)"


def test_store_urls_are_courts_detail2_permalinks() -> None:
    for r in _load_store():
        assert r["url"], f"{r['case_id']}: url 欠落 (probe は 41/41 permalink 取得済)"
        assert r["url"].startswith("https://www.courts.go.jp/hanrei/")
        assert r["url"].endswith("/detail2/index.html")


# --------------------------------------------------------------------------- #
# article 付与 gates
# --------------------------------------------------------------------------- #
def test_article_cases_match_store_and_locked_rp() -> None:
    cases = _article_cases()
    rows = _load_store()
    assert len(cases) == _EXPECTED_TOTAL
    assert {c["case_id"] for c in cases} == {r["case_id"] for r in rows}
    rp_counts: dict[int, int] = {}
    for c in cases:
        PrecedentReference.model_validate(c)
        rp = c.get("relevant_paragraph")
        if rp is not None:
            rp_counts[rp] = rp_counts.get(rp, 0) + 1
    assert rp_counts == _EXPECTED_RP_COUNTS


def test_article_body_sections_untouched() -> None:
    """本文セクション (## 原文) が frontmatter 付与の後も原文のまま存在する回帰。

    byte 単位の不変は CI の verify.py (manifest ja_text_sha256) が担保するため、
    ここでは本文セクションの存在と条文テキストの実在のみを確認する。
    """
    body = _ARTICLE_MD.read_text(encoding="utf-8").split("---\n", 2)[2]
    assert "## 原文 (日本語)" in body
    assert (
        "急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。"
        in body
    )


# --------------------------------------------------------------------------- #
# builder ロジック (fixture・オフライン)
# --------------------------------------------------------------------------- #
def test_locked_gate_rejects_fixture_counts() -> None:
    """load_locked_candidates は 28 件/high4/medium24 の佐藤ロックを強制する (fail-loud)。"""
    mod = _load_builder()
    with pytest.raises(ValueError, match="expected 28"):
        mod.load_locked_candidates(_FIXTURE)


def _fixture_candidates() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["candidates"]


def test_build_store_rows_from_fixture() -> None:
    mod = _load_builder()
    rows = mod.build_store_rows(_fixture_candidates())
    assert [r["case_id"] for r in rows] == sorted(r["case_id"] for r in rows)
    for r in rows:
        PrecedentStoreEntry(**r)
        assert "jiken_number" not in r and "_evidence" not in r
        assert r["overruled_by"] == [] and r["modified_by"] == []
        assert r["relevant_paragraph"] is None


def test_article_payload_rp_only_when_locked_and_in_range() -> None:
    mod = _load_builder()
    cands = {c["case_id"]: c for c in _fixture_candidates()}
    para_nums = {1, 2}
    p_no_rp = mod._article_case_payload(cands["scj-1969-12-04-keishu-23-12-1573-a1165"], para_nums)
    assert "relevant_paragraph" not in p_no_rp
    p_rp2 = mod._article_case_payload(cands["scj-1951-04-10-keishu-5-5-890-re61"], para_nums)
    assert p_rp2["relevant_paragraph"] == 2
    assert "jiken_number" not in p_rp2 and "_evidence" not in p_rp2


def test_article_payload_out_of_range_rp_fails_loud() -> None:
    mod = _load_builder()
    cand = dict(_fixture_candidates()[1])
    cand["relevant_paragraph"] = 5
    with pytest.raises(ValueError, match="relevant_paragraph=5"):
        mod._article_case_payload(cand, {1, 2})


def test_append_cases_to_md_idempotent_and_lf(tmp_path: Path) -> None:
    """空 cases: [] の md に fixture 3 件を splice -> 再実行 0 件・本文非改変・LF 保持。"""
    mod = _load_builder()
    md = tmp_path / "keihou-article-36.md"
    original_body = "\n# 刑法 第36条\n\n## 原文 (日本語)\n\n急迫不正の侵害に対して。\n"
    md.write_text(
        "---\nparagraphs:\n- number: 1\n- number: 2\ncases: []\n---" + original_body,
        encoding="utf-8",
        newline="\n",
    )
    added = mod.append_cases_to_md(md, _fixture_candidates())
    assert added == 3
    assert mod.append_cases_to_md(md, _fixture_candidates()) == 0, "べき等でない"
    text = md.read_text(encoding="utf-8")
    assert text.split("---")[2] == original_body.rstrip("\n") + "\n" or original_body in text
    fm = yaml.safe_load(text.split("---\n", 2)[1])
    assert len(fm["cases"]) == 3
    for c in fm["cases"]:
        PrecedentReference.model_validate(c)
    raw = md.read_bytes()
    assert raw.count(b"\r\n") == 0, "CRLF が混入 (repo は eol=lf)"

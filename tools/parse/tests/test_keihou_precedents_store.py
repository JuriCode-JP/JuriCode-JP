"""test_keihou_precedents_store.py -- 刑法 判例 store + 付与ロジックの機械検証 (CI-safe).

Why (刑法パイロット WU2 2026-07-10 / builder パラメータ化 R1-R6): courts.go.jp probe +
佐藤 relevance ロック済みの 36条 28 判例は committed store
(data/v0.2/case-law/keihou/precedents.jsonl) と keihou-article-36.md cases: に投入済み。
builder パラメータ化 (多条対応) 後も本 test が退行ゼロ (R6) を固定する:
  - store 全行が PrecedentStoreEntry として IR valid・case_id ユニーク・昇順・scj- prefix。
  - 36条スコープ: committed source (_sources/keihou36.json) の佐藤ロック
    (28 件・high 4 / medium 24) が store / article 付与と一致する fidelity gate。
  - D5 予約フィールド (overruled_by/modified_by) と cited_by が全行空 (populate は後段 FU)。
  - R6 byte 不変: store == 全 committed source からの再生成 (byte 一致)・
    committed md への再 attach は no-op (byte 不変)。
  - article 付与: relevant_paragraph は locked 6 件のみ (第1項 5 / 第2項 1)・本文セクション
    非改変は CI の verify.py (manifest hash) が担保。
builder ロジック (多条 merge / conflict fail-loud / lock 自己整合ゲート) は
fixtures/case_law_sources/ でオフライン検証する (web fetch なし)。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
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
_SOURCES_DIR = _REPO_ROOT / "data" / "v0.2" / "case-law" / "keihou" / "_sources"
_SOURCE36 = _SOURCES_DIR / "keihou36.json"
_ARTICLE_MD = _REPO_ROOT / "data" / "v0.2" / "phase1-police" / "keihou" / "keihou-article-36.md"
_BUILDER_PATH = _REPO_ROOT / "tools" / "parse" / "build-keihou-precedents.py"
_FIX = Path(__file__).parent / "fixtures" / "case_law_sources"

# 佐藤ロック済み expected (2026-07-10)。変更には user 明示承認が必要。
_EXPECTED_TOTAL = 28
_EXPECTED_RELEVANCE = {"high": 4, "medium": 24}
_EXPECTED_RP_COUNTS = {1: 5, 2: 1}


def _load_builder():
    """ハイフン名モジュール build-keihou-precedents.py を importlib で読む (確立パターン)。"""
    spec = importlib.util.spec_from_file_location("build_keihou_precedents", _BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    # sys.modules 登録は @dataclass (LockedSource) が cls.__module__ を解決するのに必要
    sys.modules["build_keihou_precedents"] = mod
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


def _source36_candidates() -> list[dict]:
    return json.loads(_SOURCE36.read_text(encoding="utf-8"))["candidates"]


def _article_cases() -> list[dict]:
    fm_text = _ARTICLE_MD.read_text(encoding="utf-8").split("---\n", 2)[1]
    fm = yaml.safe_load(fm_text) or {}
    return fm.get("cases") or []


# --------------------------------------------------------------------------- #
# committed store gates (store 全体の構造・将来の多条追加でも不変の性質)
# --------------------------------------------------------------------------- #
def test_store_rows_all_valid_sorted_unique() -> None:
    rows = _load_store()
    ids = [r["case_id"] for r in rows]
    assert len(set(ids)) == len(ids), "case_id が重複 (store は判例 1 件 = 1 レコード)"
    assert ids == sorted(ids), "case_id 昇順でない"
    for r in rows:
        entry = PrecedentStoreEntry(**r)
        assert entry.case_id.startswith("scj-")


def test_store_36_scope_matches_locked_shape() -> None:
    """36条 committed source の佐藤ロック (28 件・high4/medium24) fidelity gate。"""
    src = json.loads(_SOURCE36.read_text(encoding="utf-8"))
    assert src["lock"] == {"total": _EXPECTED_TOTAL, "relevance": _EXPECTED_RELEVANCE}
    cands = src["candidates"]
    assert len(cands) == _EXPECTED_TOTAL
    src_ids = {c["case_id"] for c in cands}
    store_by_id = {r["case_id"]: r for r in _load_store()}
    assert src_ids <= set(store_by_id), "36条 source の case_id が store に無い"
    dist: dict[str, int] = {}
    for cid in src_ids:
        rel = store_by_id[cid]["relevance"]
        dist[rel] = dist.get(rel, 0) + 1
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
# R6 退行ゼロ gates (builder パラメータ化で 36条データが 1 byte も変わらない)
# --------------------------------------------------------------------------- #
def test_store_regenerates_byte_identical_from_committed_sources() -> None:
    """R5/R6: store == f(全 committed source) の byte 一致 (CI 不変条件)。"""
    mod = _load_builder()
    rows = mod.merge_store_rows(mod.discover_sources(_SOURCES_DIR))
    assert _STORE.read_bytes() == mod._store_content(rows).encode("utf-8"), (
        "committed store が committed source からの再生成と byte 不一致 "
        "(source と store は同一コミットで更新する規律)"
    )


def test_article36_reattach_is_noop_and_byte_identical(tmp_path: Path) -> None:
    """R6: committed md への再 attach は 0 件追加・byte 不変 (べき等)。"""
    mod = _load_builder()
    tmp_md = tmp_path / _ARTICLE_MD.name
    shutil.copyfile(_ARTICLE_MD, tmp_md)
    before = tmp_md.read_bytes()
    assert mod.append_cases_to_md(tmp_md, _source36_candidates()) == 0
    assert tmp_md.read_bytes() == before


# --------------------------------------------------------------------------- #
# article 付与 gates
# --------------------------------------------------------------------------- #
def test_article_cases_match_source_and_locked_rp() -> None:
    cases = _article_cases()
    assert len(cases) == _EXPECTED_TOTAL
    assert {c["case_id"] for c in cases} == {c["case_id"] for c in _source36_candidates()}
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
# builder ロジック (fixtures/case_law_sources/・オフライン)
# --------------------------------------------------------------------------- #
def test_load_locked_source_rejects_lock_total_mismatch() -> None:
    """lock ヘッダの自己整合ゲート (件数のすり替え検出・fail-loud)。"""
    mod = _load_builder()
    with pytest.raises(ValueError, match="lock.total"):
        mod.load_locked_source(_FIX / "badlock" / "keihou36.json")


def test_load_locked_source_rejects_filename_mismatch(tmp_path: Path) -> None:
    """ファイル名 keihou{N}.json と article_id の不一致は fail-loud (取り違え防止)。"""
    mod = _load_builder()
    wrong = tmp_path / "keihou38.json"
    shutil.copyfile(_FIX / "ok" / "keihou36.json", wrong)
    with pytest.raises(ValueError, match="keihou38.json"):
        mod.load_locked_source(wrong)


def test_merge_multi_article_single_store_row_per_case() -> None:
    """多条跨ぎ: 36条と43条で共有する判例は store で 1 レコードに合流する。"""
    mod = _load_builder()
    sources = mod.discover_sources(_FIX / "ok")
    assert [s.article_number for s in sources] == ["36", "43"]
    rows = mod.merge_store_rows(sources)
    ids = [r["case_id"] for r in rows]
    assert len(ids) == 3, "36条 3 件 + 43条 2 件 (全て共有) = ユニーク 3 件"
    assert ids == sorted(ids)
    for r in rows:
        PrecedentStoreEntry(**r)
        assert "jiken_number" not in r and "attached_article_id" not in r
        assert r["overruled_by"] == [] and r["modified_by"] == []
        assert r["relevant_paragraph"] is None


def test_merge_conflicting_store_fields_fail_loud() -> None:
    """source 間で relevance が食い違う共有判例は黙って選択せず fail-loud (L3 差し戻し)。"""
    mod = _load_builder()
    with pytest.raises(ValueError, match="不一致"):
        mod.merge_store_rows(mod.discover_sources(_FIX / "conflict"))


def test_article_payload_rp_only_when_locked_and_in_range() -> None:
    mod = _load_builder()
    cands = {
        c["case_id"]: c
        for c in json.loads((_FIX / "ok" / "keihou36.json").read_text(encoding="utf-8"))[
            "candidates"
        ]
    }
    para_nums = {1, 2}
    p_no_rp = mod._article_case_payload(cands["scj-1969-12-04-keishu-23-12-1573-a1165"], para_nums)
    assert "relevant_paragraph" not in p_no_rp
    p_rp2 = mod._article_case_payload(cands["scj-1951-04-10-keishu-5-5-890-re61"], para_nums)
    assert p_rp2["relevant_paragraph"] == 2
    assert "jiken_number" not in p_rp2 and "_evidence" not in p_rp2


def test_article_payload_out_of_range_rp_fails_loud() -> None:
    mod = _load_builder()
    cand = dict(
        json.loads((_FIX / "ok" / "keihou36.json").read_text(encoding="utf-8"))["candidates"][0]
    )
    cand["relevant_paragraph"] = 5
    with pytest.raises(ValueError, match="relevant_paragraph=5"):
        mod._article_case_payload(cand, {1, 2})


def test_append_cases_to_md_idempotent_and_lf(tmp_path: Path) -> None:
    """空 cases: [] の md に fixture 3 件を splice -> 再実行 0 件・本文非改変・LF 保持。"""
    mod = _load_builder()
    cands = json.loads((_FIX / "ok" / "keihou36.json").read_text(encoding="utf-8"))["candidates"]
    md = tmp_path / "keihou-article-36.md"
    original_body = "\n# 刑法 第36条\n\n## 原文 (日本語)\n\n急迫不正の侵害に対して。\n"
    md.write_text(
        "---\nparagraphs:\n- number: 1\n- number: 2\ncases: []\n---" + original_body,
        encoding="utf-8",
        newline="\n",
    )
    added = mod.append_cases_to_md(md, cands)
    assert added == 3
    assert mod.append_cases_to_md(md, cands) == 0, "べき等でない"
    text = md.read_text(encoding="utf-8")
    assert text.split("---")[2] == original_body.rstrip("\n") + "\n" or original_body in text
    fm = yaml.safe_load(text.split("---\n", 2)[1])
    assert len(fm["cases"]) == 3
    for c in fm["cases"]:
        PrecedentReference.model_validate(c)
    raw = md.read_bytes()
    assert raw.count(b"\r\n") == 0, "CRLF が混入 (repo は eol=lf)"

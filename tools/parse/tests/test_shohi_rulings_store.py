"""test_shohi_rulings_store.py -- 消費税裁決 store + article 付与の機械検証 (CI-safe).

Why (bulk-ingest 検証ゲート・2026-07-08): 消費税 (MP/05) の全 146 裁決を committed store
(data/v0.2/case-law/shohi/rulings.jsonl) に永続化し、参照条文ありの subset を条文 md の
cases: に付与した (法人税 PR#108・相続税 PR#111 の逐語横展開)。本 test はロック済 committed
成果物を読み、機械的な不変条件を検証する:
  - store 全行が RulingStoreEntry として IR valid・case_id 100% ユニーク (dup0)。
  - 継承 issue_code (primary) が issue_codes に含まれる (忠実保持の整合)。
  - article cases: の全 ruling link (article_id) が data/v0.2 に物理実在 = 偽リンク 0。
  - store が主張した各 (case_id->条) が対象 md cases: に実在 (forward 整合・偽リンク0)。
data/v0.2 は gitignore 対象外ゆえ CI で実在する (cache/kfs は gitignored ゆえ本 test は
leaf HTML に依存しない = hermetic)。要旨 byte 照合は dry-run driver 側のゲートが担保する。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

_STORE = _REPO_ROOT / "data" / "v0.2" / "case-law" / "shohi" / "rulings.jsonl"
_DATA_V02 = _REPO_ROOT / "data" / "v0.2"


def _load_store() -> list[dict]:
    if not _STORE.exists():
        pytest.skip(f"store not present: {_STORE}")
    rows = []
    for line in _STORE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _corpus_article_ids() -> set[str]:
    """data/v0.2 の全 article_id 集合 (<abbrev>-article-<N>.md -> <abbrev>-art-<N>)。"""
    ids: set[str] = set()
    for md in _DATA_V02.glob("*/*/*-article-*.md"):
        ids.add(md.stem.replace("-article-", "-art-", 1))
    return ids


def _find_article_md(article_id: str) -> Path | None:
    """article_id (<abbrev>-art-<N>) の md を data/v0.2 から探す。"""
    abbrev, _, num = article_id.rpartition("-art-")
    matches = list(_DATA_V02.glob(f"*/{abbrev}/{abbrev}-article-{num}.md"))
    return matches[0] if matches else None


def test_store_rows_validate_and_unique():
    """store 全行が RulingStoreEntry として valid・case_id ユニーク (dup0)。"""
    from juricode_shared import RulingStoreEntry

    rows = _load_store()
    assert rows, "store is empty"
    seen: set[str] = set()
    for r in rows:
        obj = RulingStoreEntry.model_validate(r)
        assert obj.case_type == "ruling"
        assert obj.case_id.startswith("ntt-")
        assert obj.case_id not in seen, f"duplicate case_id in store: {obj.case_id}"
        seen.add(obj.case_id)


def test_store_issue_code_primary_in_issue_codes():
    """継承 issue_code (primary) は issue_codes に含まれる (忠実保持の整合)。"""
    rows = _load_store()
    for r in rows:
        if r.get("issue_code"):
            assert r["issue_code"] in r["issue_codes"], (
                f"{r['case_id']}: primary issue_code not in issue_codes"
            )


def test_store_attached_ids_exist_in_corpus():
    """store の attached_article_ids は全て data/v0.2 に実在 (偽リンク 0)。"""
    corpus = _corpus_article_ids()
    for r in _load_store():
        for aid in r.get("attached_article_ids", []):
            assert aid in corpus, f"{r['case_id']}: attached {aid} not in corpus (dangling)"


def test_article_ruling_links_are_real_and_in_store():
    """store が主張した各 (case_id -> 条) が対象 md cases: に実在 (forward 整合・偽リンク0).

    store の attached_article_ids を起点に対象 md だけ読む (全 md を舐めない)。cross-store で
    共有される条 md (複数 per-tax store の裁決を保持) に耐えるため forward 方向で検証する。
    """
    import yaml

    rows = _load_store()
    corpus = _corpus_article_ids()
    assert any(r.get("attached_article_ids") for r in rows), "no attached_article_ids in store"

    # Forward invariant (2026-07-08): store が主張した各 (case_id -> attached article) が
    # その条 md の cases: に物理実在することを検証する。Design D は cross-law 裁決を被引用条の
    # md に名前空間横断で denormalize する (FU-552 が hojin 裁決を kokuzei/minpou md に付与済) ため、
    # 共有条 md は複数 per-tax store の裁決を保持しうる。逆方向 (「md の全 ruling が この store に
    # 属す」) は共有条 (例: shohi cross-law が houjin-art-11.md に着地) で偽ゆえ assert しない。
    md_ruling_ids: dict[str, set[str]] = {}
    checked = 0
    for r in rows:
        for aid in r.get("attached_article_ids", []):
            assert aid in corpus, f"{r['case_id']}: attached {aid} not in corpus (dangling)"
            md = _find_article_md(aid)
            assert md is not None, f"md not found for {aid}"
            if aid not in md_ruling_ids:
                fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
                md_ruling_ids[aid] = {
                    c["case_id"] for c in (fm.get("cases") or []) if c.get("case_type") == "ruling"
                }
            assert r["case_id"] in md_ruling_ids[aid], (
                f"{md.name}: store claims {r['case_id']} -> {aid} but md cases: lacks it "
                f"(forward invariant)"
            )
            checked += 1
    assert checked >= 67, f"expected >=67 store->md ruling links, found {checked}"


def test_crosslaw_links_are_present():
    """消費裁決の cross-law link (法人税法・地方税法) が store に存在する (回帰ロック).

    Why: 消費裁決は消費税法本体だけでなく法人税法・地方税法も引く。共有 FULLNAME_LAW_MAP に
    既登録の法人/地方へ corpus 実在分だけ純加算した (偽リンク0)。この cross-law が committed
    store に残っていることを実証し、将来の parser/map 変更で silent に落ちないよう固定する
    (消費 bulk・2026-07-08)。
    """
    rows = _load_store()
    attached = {aid for r in rows for aid in r.get("attached_article_ids", [])}
    for aid in (
        "houjin-zei-hou-art-11",  # cross-law 法人税法 (消費裁決が引用)
        "chihou-zei-hou-art-144",  # cross-law 地方税法 (地方消費税・消費裁決が引用)
    ):
        assert aid in attached, f"消費 cross-law link missing: {aid} (回帰?)"

"""test_hojin_rulings_store.py -- 法人税裁決 store + article 付与の機械検証 (CI-safe).

Why (bulk-ingest 検証ゲート・2026-07-07): 全 451 裁決を committed store
(data/v0.2/case-law/hojin/rulings.jsonl) に永続化し、参照条文ありの subset を条文 md の
cases: に付与した。本 test はロック済 committed 成果物を読み、機械的な不変条件を検証する:
  - store 全行が RulingStoreEntry として IR valid・case_id 100% ユニーク (dup0)。
  - 継承 issue_code (primary) が issue_codes に含まれる (忠実保持の整合)。
  - article cases: の全 ruling link (article_id) が data/v0.2 に物理実在 = 偽リンク 0。
  - article の各 ruling が store に存在する (store と付与の整合)。
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

_STORE = _REPO_ROOT / "data" / "v0.2" / "case-law" / "hojin" / "rulings.jsonl"
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
    """付与先 article md cases: の全 ruling link が corpus 実在 + store に存在 (偽リンク0・整合).

    付与先は store の attached_article_ids から特定し、対象 md だけ読む (全 16k md を舐めない)。
    """
    import yaml

    rows = _load_store()
    store_cids = {r["case_id"] for r in rows}
    corpus = _corpus_article_ids()
    target_aids = sorted({aid for r in rows for aid in r.get("attached_article_ids", [])})
    assert target_aids, "no attached_article_ids in store"

    checked = 0
    for aid in target_aids:
        assert aid in corpus, f"attached {aid} not in corpus (dangling)"
        md = _find_article_md(aid)
        assert md is not None, f"md not found for {aid}"
        fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
        for c in fm.get("cases") or []:
            if c.get("case_type") != "ruling":
                continue
            assert c["case_id"] in store_cids, (
                f"{md.name}: ruling {c['case_id']} not in store (整合違反)"
            )
            checked += 1
    assert checked >= 105, f"expected >=105 ruling links, found {checked}"


def test_fullwidth_and_crosslaw_links_are_present():
    """FU-552 で回収した +9 リンク (全角 2・cross-law 7) が store に存在する (回帰ロック).

    Why: 相続裁決 bulk で共有 parser に全角正規化 + cross-law マップ拡張を入れた後、法人税 store を
    修正後 parser で再生成し純加算 9 link を取り込んだ (FU-552・2026-07-04)。全角取りこぼし
    (法人税法第２条 全角 -> houjin-art-2) と cross-law (国税通則法 art-68・民法 art-624) が
    committed store に残っていることを実証し、将来の parser 変更で silent に落ちないよう固定する。
    """
    rows = _load_store()
    attached = {aid for r in rows for aid in r.get("attached_article_ids", [])}
    for aid in (
        "houjin-zei-hou-art-2",  # 全角 第２条 正規化 (FU-552)
        "kokuzei-tsuusoku-hou-art-68",  # cross-law 重加算税 (FU-552)
        "minpou-art-624",  # cross-law 民法 (FU-552)
    ):
        assert aid in attached, f"FU-552 link missing: {aid} (全角/cross-law 回帰?)"

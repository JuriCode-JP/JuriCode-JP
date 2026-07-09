"""test_kfs_eda_ban_regression.py -- FU-71 枝番偽リンク 31 件の是正を committed 成果物でロックする.

Why (偽リンク0 検査の格上げ・2026-07-08):
    旧「偽リンク0」検査は付与先 article_id が **corpus に実在するか** しか見ていなかった。
    `_ARTICLE_RE` が `第74条の9` の枝番を捨てて `art-74` に潰しても、art-74 は実在するので
    素通りし、merge 済み 5 store に 31 件の偽リンクが commit された (report §1)。
    「実在」だけでは足りず「**生引用が指した条と一致しているか**」まで見る必要がある。

    ただし生引用 (《参照条文等》) は leaf HTML にしか無く、`cache/kfs` は gitignored (.gitignore:65)
    ゆえ CI では再 parse できない。そこで検査を 2 層に分ける:
      (1) resolver 層 (hermetic): 枝番を落とさないことを test_kfs_saiketsu.py の枝番回帰で固定。
          `第74条の9` が実在する別条 art-74 に潰れないことを直接 assert する。
      (2) 成果物層 (本 file): 佐藤が GO-1 で目視ロックした 31 件について、**誤 article_id が
          store/md のどちらにも残っていない**ことと **正 article_id が双方に在る**ことを固定する。
    parser が退行して bulk が再実行されれば (2) が loud に落ちる。

    ロック済リストは fix-kfs-eda-ban-links.py を single source of truth として import する
    (テスト側に写経すると二重管理でズレるため)。
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

_DATA_V02 = _REPO_ROOT / "data" / "v0.2"
_FIX_SCRIPT = _REPO_ROOT / "tools" / "parse" / "fix-kfs-eda-ban-links.py"

# GO-1 でロックした件数 (report §1 の 30 行 -> 除去は case+誤id で 29 ペアに統合、
# さらに map 成長由来の 31 件目を佐藤裁定で追加 -> 除去 30 / 追加 26)。
_EXPECTED_REMOVALS = 30
_EXPECTED_ADDITIONS = 26


def _load_locked() -> tuple[tuple, tuple]:
    """ハイフン名スクリプトから ロック済リストだけを読む (importlib・実行はしない)。"""
    spec = importlib.util.spec_from_file_location("fix_kfs_eda_ban_links", _FIX_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LOCKED_REMOVALS, mod.LOCKED_ADDITIONS


LOCKED_REMOVALS, LOCKED_ADDITIONS = _load_locked()


def _store_attached(store: str) -> dict[str, set[str]]:
    path = _DATA_V02 / "case-law" / store / "rulings.jsonl"
    if not path.exists():
        pytest.skip(f"store not present: {path}")
    out: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["case_id"]] = set(r["attached_article_ids"])
    return out


def _md_case_ids(article_id: str) -> set[str]:
    abbrev, _, num = article_id.rpartition("-art-")
    matches = list(_DATA_V02.glob(f"*/{abbrev}/{abbrev}-article-{num}.md"))
    if not matches:
        return set()
    fm = yaml.safe_load(matches[0].read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
    return {c["case_id"] for c in (fm.get("cases") or [])}


def test_locked_list_counts_match_go1():
    """ロック済リストが GO-1 の粒度 (除去30 / 追加26) から動いていないこと。"""
    assert len(LOCKED_REMOVALS) == _EXPECTED_REMOVALS
    assert len(LOCKED_ADDITIONS) == _EXPECTED_ADDITIONS


@pytest.mark.parametrize("store,case_id,wrong_aid", LOCKED_REMOVALS)
def test_wrong_article_id_absent_from_store(store, case_id, wrong_aid):
    """誤 article_id が store の attached_article_ids に残っていない。"""
    attached = _store_attached(store)
    assert case_id in attached, f"{store}: {case_id} が store から消えている"
    assert wrong_aid not in attached[case_id], f"{store}/{case_id}: 誤リンク {wrong_aid} が残存"


@pytest.mark.parametrize("store,case_id,wrong_aid", LOCKED_REMOVALS)
def test_wrong_article_md_no_longer_cites_ruling(store, case_id, wrong_aid):
    """誤 article_id の条 md の cases: から当該裁決が除去されている (md 側の残存 = 二重リンク)。"""
    assert case_id not in _md_case_ids(wrong_aid), (
        f"{wrong_aid}.md に {case_id} が残存 (二重リンク)"
    )


@pytest.mark.parametrize("store,case_id,right_aid", LOCKED_ADDITIONS)
def test_right_article_id_present_in_store_and_md(store, case_id, right_aid):
    """正 article_id が store と条 md の双方に付与されている (双方向 denormalize の整合)。"""
    attached = _store_attached(store)
    assert right_aid in attached[case_id], (
        f"{store}/{case_id}: 正リンク {right_aid} が store に無い"
    )
    assert case_id in _md_case_ids(right_aid), f"{right_aid}.md に {case_id} が付与されていない"


def test_kokutsu_art74_branches_are_separate_articles():
    """代表ケース: 第74条の9/の11/の14 が本則 art-74 に潰れず別条に付いている。

    Why: 本バグの震源 (国税通則法 art-74 md は誤リンク 4 件だけを持っていた)。
    """
    attached = _store_attached("kokutsu")
    assert "kokuzei-tsuusoku-hou-art-74-9" in attached["ntt-2014-11-13-j97-6"]
    assert "kokuzei-tsuusoku-hou-art-74-11" in attached["ntt-2015-05-26-j99-3"]
    assert "kokuzei-tsuusoku-hou-art-74-14" in attached["ntt-2015-06-01-j99-2"]
    assert _md_case_ids("kokuzei-tsuusoku-hou-art-74") == set(), "本則 art-74 に裁決が残っている"


def test_map_growth_stale_link_fixed():
    """31 件目: 国税通則法施行令第6条第2項 が本則 art-6 でなく施行令 art-6 に付いている。

    Why: shotoku store commit 時 (8070017f) は 国税通則法施行令 が FULLNAME_LAW_MAP 未登録で、
    前方一致により本則 art-6 へ誤付与された。map 成長後に store が refresh されず残存していた。
    """
    attached = _store_attached("shotoku")["ntt-2014-12-04-j97-7"]
    assert "kokuzei-tsuusoku-hou-shikkourei-art-6" in attached
    assert "kokuzei-tsuusoku-hou-art-6" not in attached
    assert "ntt-2014-12-04-j97-7" not in _md_case_ids("kokuzei-tsuusoku-hou-art-6")
    assert "ntt-2014-12-04-j97-7" in _md_case_ids("kokuzei-tsuusoku-hou-shikkourei-art-6")


def test_no_ruling_orphan_between_store_and_md():
    """全 5 store で store.attached と md.cases が双方向一致 (残存/付与漏れ 0)。

    Why: 除去は md 側にしか効かない経路があり (append 専用だった)、片側だけ直ると二重リンクや
    orphan が生まれる。方向を両方見る。
    """
    store_all: dict[str, set[str]] = {}
    for st in ("hojin", "kokutsu", "shohi", "shotoku", "sozoku"):
        for cid, aids in _store_attached(st).items():
            store_all.setdefault(cid, set()).update(aids)

    md_all: dict[str, set[str]] = {}
    for md in _DATA_V02.glob("*/*/*-article-*.md"):
        text = md.read_text(encoding="utf-8")
        if "case_type: ruling" not in text:
            continue
        fm = yaml.safe_load(text.split("---\n", 2)[1]) or {}
        for c in fm.get("cases") or []:
            if c.get("case_type") == "ruling":
                md_all.setdefault(c["case_id"], set()).add(fm["article_id"])

    orphan = {
        c: sorted(a - store_all.get(c, set()))
        for c, a in md_all.items()
        if a - store_all.get(c, set())
    }
    missing = {
        c: sorted(a - md_all.get(c, set()))
        for c, a in store_all.items()
        if a - md_all.get(c, set())
    }
    assert orphan == {}, f"md にあるが store に無い (残存/二重リンク): {orphan}"
    assert missing == {}, f"store にあるが md に無い (付与漏れ): {missing}"

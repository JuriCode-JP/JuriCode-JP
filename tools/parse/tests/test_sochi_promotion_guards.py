"""test_sochi_promotion_guards.py -- FU-537 措置法 prefix 昇格 + parser ガード3種の unit pin.

Why this test exists:
    FU-537 は 措法/措令/措規 を LAW_PREFIX_MAP へ昇格し (措通は当時 FU-536 保留ゆえ UNREG 据置。
    後に FU-538 で措通も昇格・FU-545 で下記 test_sochu_* の期待値を実挙動へ追随更新)、
    生昇格が生む dangling (P0 で 14 他法令偽リンク + 11 malformed + 6 genuine gap) を
    ガード3種で 0 化する:
      D 継承ガード (inherited_cross_law): 措法系 prefix を継承する非数字開始トークン (別法令名) を unlink
      A/B (malformed_range / malformed_etc): 措法系 remainder の ~ / 等 を unlink
      C 実在チェック (corpus_gap): 措法系 article_id が FU-535 corpus に無ければ unlink
    本 test は extract_related_from_kikon を合成 根拠法令等 文字列で直接呼び、各ガードの unlink と
    over-guard なし (真正な裸番号継承は linked のまま) を pin する。data/v0.2 の 措法系 corpus は
    gitignore 対象外ゆえ C ガードの照合は CI でも成立する。

    落ちたら直すのはパーサ (parse-nta-taxanswer.py) であって本 test の期待値ではない。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_PARSER = _THIS.parents[1] / "parse-nta-taxanswer.py"
_SHARED_SRC = _THIS.parents[2] / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

_spec = importlib.util.spec_from_file_location("parse_nta_taxanswer_guards", _PARSER)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

extract = _mod.extract_related_from_kikon
_SOCHI = {"sochi-hou", "sochi-hou-shikkourei", "sochi-hou-shikoukisoku"}


def _linked_ids(res: dict) -> list[str]:
    return [a["article_id"] for a in res["related_articles"] if a["law_abbrev"] in _SOCHI]


def _reason_for(res: dict, needle: str) -> str | None:
    for u in res["unlinked"]:
        if needle in u["raw"]:
            return u["reason"]
    return None


# --- 昇格の基本動作 -------------------------------------------------------


def test_genuine_sochi_article_is_linked() -> None:
    """措法66の4 (corpus 実在) は sochi-hou-art-66-4 として linked。"""
    res = extract("措法66の4")
    assert "sochi-hou-art-66-4" in _linked_ids(res)


def test_sochi_no_arabic_and_hierarchy_normalized() -> None:
    """の -> - の全域正規化 (措令26の27 -> sochi-hou-shikkourei-art-26-27)。"""
    res = extract("措令26の27")
    ids = [a["article_id"] for a in res["related_articles"]]
    assert "sochi-hou-shikkourei-art-26-27" in ids
    assert all("の" not in i for i in ids)


# --- D 継承ガード ---------------------------------------------------------


def test_D_inherited_cross_law_is_unlinked() -> None:
    """措法系 prefix を継承する別法令名 (非数字開始) は inherited_cross_law で unlink。"""
    res = extract("措法41、首都圏整備法2")
    assert _reason_for(res, "首都圏整備法2") == "inherited_cross_law"
    # 別法令名が 措置法条へ偽リンクしていない
    assert not any("首都圏" in a["raw"] for a in res["related_articles"])


def test_no_overguard_genuine_bare_continuation_stays_linked() -> None:
    """真正な裸番号継承 (措法41、70の3) の 70の3 は linked のまま (over-guard なし)。"""
    res = extract("措法41、70の3")
    assert "sochi-hou-art-70-3" in _linked_ids(res)
    assert _reason_for(res, "70の3") is None


# --- A / B レンジ・等 -----------------------------------------------------


def test_A_malformed_range_is_unlinked() -> None:
    """措法系のレンジ (~) は展開せず malformed_range で unlink (article_id に ~ を残さない)。"""
    res = extract("措法34~34の3")
    assert _reason_for(res, "34~34の3") == "malformed_range"
    assert all("~" not in i for i in [a["article_id"] for a in res["related_articles"]])


def test_B_malformed_etc_is_unlinked() -> None:
    """措法系の 等 付き参照は malformed_etc で unlink。"""
    res = extract("措法65の7等")
    assert _reason_for(res, "65の7等") == "malformed_etc"
    assert not any("等" in a["article_id"] for a in res["related_articles"])


# --- C 実在チェック -------------------------------------------------------


def test_C_corpus_gap_is_unlinked() -> None:
    """corpus に存在しない下位条 (措法10の4の2) は corpus_gap で unlink (dangling link を作らない)。"""
    res = extract("措法10の4の2")
    assert _reason_for(res, "10の4の2") == "corpus_gap"
    assert "sochi-hou-art-10-4-2" not in _linked_ids(res)


# --- 境界 (措通据置 / kaisei_funsoku 不変) --------------------------------


def test_sochu_still_unlinked_after_promotion(monkeypatch) -> None:
    """措通 は FU-538 で LAW_PREFIX_MAP へ昇格済ゆえ、措法専用 reason corpus_unregistered
    には論理的にならない。66の4-1 は実在する directive ではなく (実 corpus は 66の4-1-N の
    3階層のみ・P0-0 実測)、昇格後 prefix で解決を試みても corpus に無いため
    tsutatsu_not_in_corpus として unlinked になる (FU-545 で期待値を実挙動へ追随)。

    Hermetic (FU-545): _TSUTATSU_CORPUS を実 corpus 構造の最小スタブ (3階層 66の4-1-N のみ・
    2階層 66の4-1 なし) に固定し、build/chunks の有無に依存せず CI/ローカルで同一挙動にする。

    落ちたら直すのはパーサ (parse-nta-taxanswer.py) であって本 test の期待値ではない。
    """
    # 実 corpus 構造の最小再現: 2階層 66の4-1 は存在せず 3階層 66の4-1-N のみ (P0-0 fixture 実測)。
    monkeypatch.setattr(
        _mod, "_TSUTATSU_CORPUS", {"sochi-hojin-tsutatsu": {"66の4-1-1", "66の4-1-2"}}
    )
    res = extract("措通66の4-1")
    assert _reason_for(res, "措通66の4-1") == "tsutatsu_not_in_corpus"
    # 昇格しても存在しない 2 階層 id へ偽リンクしない
    assert not any(a["law_abbrev"] in _SOCHI for a in res["related_articles"] if "措通" in a["raw"])


def test_kaisei_funsoku_not_hijacked_by_promotion() -> None:
    """改正措法附則は amendment 先行判定で kaisei_funsoku 維持 (昇格が横取りしない)。"""
    res = extract("措法41、令3改正措法附則38")
    assert _reason_for(res, "改正措法附則38") == "kaisei_funsoku"
    assert not any("改正" in a["raw"] for a in res["related_articles"])


# --- disjoint (article_id 基準) -------------------------------------------


def test_disjoint_linked_unlinked_by_article_id() -> None:
    """linked article_id は一意で、unlinked は article_id を持たない (id 空間が disjoint)。"""
    res = extract("措法66の4、首都圏整備法2、措法10の4の2、措法65の7等")
    ids = _linked_ids(res)
    assert len(ids) == len(set(ids))
    assert all("article_id" not in u for u in res["unlinked"])

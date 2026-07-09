"""test_kokutsu_amendments.py -- 国税通則法 amendments[] populate の機械検証 (CI-safe).

Why (改正履歴 横展開②・国税通則法・案A corpus ソース版アンカー):
    消費税/相続税/法人税/所得税と同型の忠実性ゲートを国税通則法に適用する。国通は e-Gov の
    メタデータ/本文連結遅延で CurrentEnforced=0 (2026-06-24 施行版が未連結) のため、改正
    チェーンを corpus のソース版 = e-Gov law_data(現行) = 2026-05-21 版にアンカーして
    populate した (64 エントリ / 41 条)。本 test は committed 成果物
    (data/v0.2/phase1-tax/kokuzei-tsuusoku-hou/*.md) を読み機械的不変条件を検証する:
      - 全 amendments が IR (juricode_shared.Amendment・extra=forbid) valid。
      - エントリ総数 = 64・付与条数 = 41 (実 populate の実測値をロック・佐藤裁定で確定)。
      - 各 (effective_date, law_num) が実 law_revisions (committed fixture) に存在
        = 捏造改正 0 (忠実性ゲート)。
      - 全 effective_date が window (>= 2020-04-01) 内。description が承認形式。
      - 付与条集合 ⊆ 現行本則 194 条 (逸脱ゼロ)。
      - point-in-time: アンカー (2026-05-21) より後の未連結施行版
        (2026-05-25 令和六年法律第五十二号 / 2026-06-24 令和八年法律第四十六号) は amendments に
        出ない (corpus 未反映ゆえ・corpus 再取得+再 run で自動追随)。
    加えてアンカーロジックを fixture から hermetic に固定する。cache/ の XML には依存しない。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
_AMEND_SRC = _REPO_ROOT / "tools" / "amendments"
for _p in (_SHARED_SRC, _AMEND_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_CORPUS = _REPO_ROOT / "data" / "v0.2" / "phase1-tax" / "kokuzei-tsuusoku-hou"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kokutsu-law-revisions.json"

# 実 populate の実測値をロック (64/41・Phase0 report + 佐藤裁定 2026-07-09・案A アンカー)。
_EXPECTED_ENTRIES = 64
_EXPECTED_ARTICLES = 41
_EXPECTED_MAIN_ARTICLES = 194
_WINDOW_FROM = "2020-04-01"
# corpus ソース版アンカー = e-Gov law_data(現行) = 2026-05-21 版 (CurrentEnforced=0 の下で採用)。
_ANCHOR_RID = "337AC0000000066_20260521_505AC0000000003"
# アンカーより後の未連結施行版 (point-in-time で除外されるべき改正法番号)。
_POST_ANCHOR_LAW_NUMS = ("令和六年法律第五十二号", "令和八年法律第四十六号")


def _load_articles() -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    for md in sorted(_CORPUS.glob("kokuzei-tsuusoku-hou-article-*.md")):
        fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
        out.append((md, fm))
    return out


def _load_revisions() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_corpus_present():
    """corpus が存在し 194 本則条ある (前提)。"""
    arts = _load_articles()
    if not arts:
        pytest.skip(f"corpus not present: {_CORPUS}")
    assert len(arts) == _EXPECTED_MAIN_ARTICLES, (
        f"expected {_EXPECTED_MAIN_ARTICLES} 本則条, found {len(arts)}"
    )


def test_all_amendments_ir_valid():
    """全条が IR valid で、amendments は Amendment(extra=forbid) を通る。"""
    from juricode_shared.frontmatter import article_from_frontmatter

    for md, fm in _load_articles():
        article = article_from_frontmatter(fm)
        for am in article.amendments:
            assert am.effective_date is not None
            assert am.law_num, f"{md.name}: amendment missing law_num"


def test_entry_and_article_counts_locked():
    """エントリ総数 64・付与条数 41 (dry-run 実測ロック・佐藤裁定・案A アンカー)。"""
    total = 0
    with_amend = 0
    for _md, fm in _load_articles():
        ams = fm.get("amendments") or []
        if ams:
            with_amend += 1
            total += len(ams)
    assert total == _EXPECTED_ENTRIES, f"expected {_EXPECTED_ENTRIES} entries, found {total}"
    assert with_amend == _EXPECTED_ARTICLES, (
        f"expected {_EXPECTED_ARTICLES} articles with amendments, found {with_amend}"
    )


def test_amendments_fidelity_against_revisions():
    """各 (effective_date, law_num) が実 law_revisions に存在する (捏造改正 0・忠実性)。"""
    revs = _load_revisions()
    real = {
        (r.get("amendment_enforcement_date"), r.get("amendment_law_num"))
        for r in revs
        if r.get("current_revision_status") in ("PreviousEnforced", "CurrentEnforced")
    }
    checked = 0
    for md, fm in _load_articles():
        for am in fm.get("amendments") or []:
            key = (str(am["effective_date"]), am["law_num"])
            assert key in real, (
                f"{md.name}: amendment {key} not in real enforced law_revisions (fabricated?)"
            )
            checked += 1
    assert checked == _EXPECTED_ENTRIES


def test_amendments_within_window_and_format():
    """全 effective_date が window 内・description が承認形式に従う。"""
    for md, fm in _load_articles():
        for am in fm.get("amendments") or []:
            assert str(am["effective_date"]) >= _WINDOW_FROM, (
                f"{md.name}: effective_date {am['effective_date']} < window {_WINDOW_FROM}"
            )
            desc = am.get("description") or ""
            assert desc.startswith(("本条を改正", "本条を新設", "本条を削除")), (
                f"{md.name}: unexpected description form: {desc!r}"
            )


def test_attributed_articles_subset_of_corpus():
    """付与条集合 ⊆ 現行本則194条 (corpus 整合・逸脱条ゼロ)。"""
    corpus_nums = {
        p.stem[len("kokuzei-tsuusoku-hou-article-") :]
        for p in _CORPUS.glob("kokuzei-tsuusoku-hou-article-*.md")
    }
    attributed = {
        md.stem[len("kokuzei-tsuusoku-hou-article-") :]
        for md, fm in _load_articles()
        if fm.get("amendments")
    }
    assert attributed <= corpus_nums, f"逸脱条: {sorted(attributed - corpus_nums)}"


def test_point_in_time_truncation_excludes_unconsolidated():
    """point-in-time: アンカー (2026-05-21) より後の未連結施行版は amendments に出ない。

    Why (データ契約・corpus ソース版アンカー): 改正 diff は corpus 本文と同一 point-in-time
    で終端する。e-Gov が law_data に未連結の施行済版 (2026-05-25 令和六年法律第五十二号 /
    2026-06-24 令和八年法律第四十六号) は corpus に反映されていないため付与しない。corpus 再取得
    + 再 run 時に自動追随する。回帰でこれら未連結版が紛れ込んでいないことを固定する。
    """
    for _md, fm in _load_articles():
        for am in fm.get("amendments") or []:
            assert am["law_num"] not in _POST_ANCHOR_LAW_NUMS, (
                f"未連結施行版 {am['law_num']} が amendments に混入 (アンカー打ち切り不発?)"
            )


def test_crosscheck_known_article():
    """回帰ロック: 既知の付与条 (art-2) の 連結欠損金額削除 改正が残ることを固定する。

    Why: parser/map 変更で silent に落ちないよう代表条の具体エントリを 1 件固定する。
    art-2 (定義) は 2022-04-01 施行 (令和二年法律第八号・グループ通算移行) で「連結欠損金額」
    が削除された。
    """
    fm = yaml.safe_load(
        (_CORPUS / "kokuzei-tsuusoku-hou-article-2.md")
        .read_text(encoding="utf-8")
        .split("---\n", 2)[1]
    )
    keys = {(str(a["effective_date"]), a["law_num"]) for a in (fm.get("amendments") or [])}
    assert ("2022-04-01", "令和二年法律第八号") in keys, "art-2 の 2022-04-01 改正が消えた (回帰?)"


def test_crosscheck_anchor_version_included():
    """回帰ロック: アンカー版 (2026-05-21 令和五年法律第三号) の改正が付与されている。

    Why: アンカーで打ち切るが、アンカー版「まで」は含む。art-14 はアンカー版で改正された
    代表条。アンカー境界の off-by-one (アンカー版を誤って除外) を固定する。
    """
    fm = yaml.safe_load(
        (_CORPUS / "kokuzei-tsuusoku-hou-article-14.md")
        .read_text(encoding="utf-8")
        .split("---\n", 2)[1]
    )
    keys = {(str(a["effective_date"]), a["law_num"]) for a in (fm.get("amendments") or [])}
    assert ("2026-05-21", "令和五年法律第三号") in keys, "art-14 のアンカー版改正が消えた (回帰?)"


# ---- ユニット (ロジック・hermetic) ---------------------------------------


def test_build_enforced_chain_anchored_from_fixture():
    """fixture からアンカー付きチェーンを構築 (CurrentEnforced=0・アンカー=2026-05-21)。"""
    import extract_amendments as ea

    chain = ea.build_enforced_chain(_load_revisions(), law_data_current_rid=_ANCHOR_RID, today=None)
    assert chain[-1]["law_revision_id"] == _ANCHOR_RID, "アンカーで終端していない"
    # CurrentEnforced フラグは 0 件 (e-Gov 遅延) だがアンカーで一意に決まる。
    assert sum(1 for r in chain if r.get("current_revision_status") == "CurrentEnforced") == 0
    dates = [r["amendment_enforcement_date"] for r in chain]
    assert dates == sorted(dates), "enforced chain not ascending by enforcement date"
    # 未連結の後続施行版は打ち切られている。
    rids = {r["law_revision_id"] for r in chain}
    assert "337AC0000000066_20260624_508AC0000000046" not in rids


def test_generalized_config_registry():
    """LAW_CONFIGS に国税通則法が登録され、値が実コードと一致する (config 駆動裏取り)。"""
    import extract_amendments as ea

    assert "kokuzei-tsuusoku-hou" in ea.LAW_CONFIGS
    cfg = ea.LAW_CONFIGS["kokuzei-tsuusoku-hou"]
    assert cfg.law_id == "337AC0000000066"
    assert cfg.law_abbrev == "kokuzei-tsuusoku-hou"
    assert cfg.window_from.isoformat() == _WINDOW_FROM
    assert cfg.corpus_dir.name == "kokuzei-tsuusoku-hou"
    # 先行4法令も registry に温存 (byte 回帰対象)。
    assert ea.LAW_CONFIGS["shouhi-zei-hou"].law_id == "363AC0000000108"
    assert ea.LAW_CONFIGS["souzoku-zei-hou"].law_id == "325AC0000000073"
    assert ea.LAW_CONFIGS["houjin-zei-hou"].law_id == "340AC0000000034"
    assert ea.LAW_CONFIGS["shotoku-zei-hou"].law_id == "340AC0000000033"

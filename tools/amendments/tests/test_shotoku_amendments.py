"""test_shotoku_amendments.py -- 所得税法 amendments[] populate の機械検証 (CI-safe).

Why (改正履歴 Phase 1・条文単位帰属・横展開④):
    消費税法パイロット (test_shouhi_amendments.py) / 相続税法 横展開① / 法人税法 横展開③ と
    同型の忠実性ゲートを所得税法に適用する。所得税法 本則 300 条のうち 96 条に、直近 5 年
    (施行日 >= 2020-04-01) の改正を amendments[] として populate した (156 エントリ)。
    本 test は committed 成果物 (data/v0.2/phase1-tax/shotoku-zei-hou/*.md) を読み、機械的な
    不変条件を検証する:
      - 全 amendments が IR (juricode_shared.Amendment・extra=forbid) valid。
      - エントリ総数 = 156・付与条数 = 96 (実 populate の実測値をロック・佐藤裁定で確定)。
      - 各 (effective_date, law_num) が実 law_revisions (committed fixture) に存在
        = 捏造改正 0 (忠実性ゲート)。
      - 全 effective_date が window (>= 2020-04-01) 内。
      - description が承認形式 (本条を改正/新設/削除) に従う。
      - 付与条集合 ⊆ 現行本則 300 条 (逸脱ゼロ)。連続削除条を畳み込む range Num
        (96:101 / 234:236) の構成条 (旧 96-101 / 234-236) は現行 corpus 非在ゆえ非付与
        = データ契約通り (章単位の大改正で現行条に残らない改廃は amendments[] に出ない)。
    加えて range Num ガード (削除条プレースホルダを diff 対象外に skip+log する共通防御) を
    hermetic に固定する。cache/ の XML (gitignored) には依存しない = hermetic。
"""

from __future__ import annotations

import json
import logging
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

_CORPUS = _REPO_ROOT / "data" / "v0.2" / "phase1-tax" / "shotoku-zei-hou"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "shotoku-law-revisions.json"

# 実 populate の実測値をロック (156/96・Phase0 report + 佐藤裁定 2026-07-09)。
_EXPECTED_ENTRIES = 156
_EXPECTED_ARTICLES = 96
_EXPECTED_MAIN_ARTICLES = 300
_WINDOW_FROM = "2020-04-01"


def _load_articles() -> list[tuple[Path, dict]]:
    """条 md の (path, frontmatter dict) を列挙する。"""
    out: list[tuple[Path, dict]] = []
    for md in sorted(_CORPUS.glob("shotoku-zei-hou-article-*.md")):
        fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
        out.append((md, fm))
    return out


def _load_revisions() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_corpus_present():
    """corpus が存在し 300 本則条ある (前提)。"""
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
        article = article_from_frontmatter(fm)  # raises on invalid
        for am in article.amendments:
            assert am.effective_date is not None
            assert am.law_num, f"{md.name}: amendment missing law_num"


def test_entry_and_article_counts_locked():
    """エントリ総数 156・付与条数 96 (dry-run 実測ロック・佐藤裁定)。"""
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
                f"{md.name}: amendment {key} not found in real enforced law_revisions (fabricated?)"
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
    """付与条集合 ⊆ 現行本則300条 (corpus 整合・逸脱条ゼロ)。

    Why: 連続削除条を畳み込む range Num (96:101 = 旧96〜101条削除 / 234:236 = 旧234〜236条
    削除) の構成条は現行 corpus に残らない。これら corpus 非在条は range Num ガード + corpus
    実在ゲートで自然に非付与となり、付与条は必ず現行 300 条の部分集合になる (誤帰属ゼロ)。
    """
    corpus_nums = {
        p.stem[len("shotoku-zei-hou-article-") :]
        for p in _CORPUS.glob("shotoku-zei-hou-article-*.md")
    }
    attributed = {
        md.stem[len("shotoku-zei-hou-article-") :]
        for md, fm in _load_articles()
        if fm.get("amendments")
    }
    assert attributed <= corpus_nums, f"逸脱条: {sorted(attributed - corpus_nums)}"


def test_range_num_deleted_articles_not_in_corpus():
    """range Num の構成条 (旧96-101 / 234-236) は現行 corpus 非在ゆえ amendments に出ない。

    Why (データ契約・連続削除条の range Num): e-Gov は連続削除条を 1 つの
    Article @Num="96:101" / "234:236" に畳み込む。案B は現行 corpus 条にのみ帰属するため、
    これら畳み込まれた削除条は corpus ファイル自体が存在せず、その改廃は amendments[] に
    記録されない (改正の完全一覧ではない・本則現行条スコープ)。回帰でこの非在条が corpus に
    紛れ込んでいないことを固定する (逸脱ゼロの裏取り)。
    """
    for n in ("96", "97", "98", "99", "100", "101", "234", "235", "236"):
        assert not (_CORPUS / f"shotoku-zei-hou-article-{n}.md").exists(), (
            f"range Num 削除条 {n} が corpus に存在 (スコープ逸脱?)"
        )


def test_crosscheck_known_article():
    """回帰ロック: 既知の付与条 (art-2) の 暗号資産 改正が残ることを固定する。

    Why: parser/map 変更で silent に落ちないよう、代表条の具体エントリを 1 件固定する。
    art-2 (定義) は 2020-05-01 施行 (令和元年法律第二十八号・資金決済法等改正) で
    「仮想通貨」→「暗号資産」の語句改正を受けた。
    """
    fm = yaml.safe_load(
        (_CORPUS / "shotoku-zei-hou-article-2.md").read_text(encoding="utf-8").split("---\n", 2)[1]
    )
    keys = {(str(a["effective_date"]), a["law_num"]) for a in (fm.get("amendments") or [])}
    assert ("2020-05-01", "令和元年法律第二十八号") in keys, "art-2 の暗号資産 改正が消えた (回帰?)"


# ---- ユニット (ロジック・hermetic) ---------------------------------------


def test_build_enforced_chain_from_fixture():
    """fixture から施行済チェーンを構築し不変条件 assert が通る (CurrentEnforced=1)。"""
    import extract_amendments as ea

    chain = ea.build_enforced_chain(_load_revisions())
    assert chain[-1]["current_revision_status"] == "CurrentEnforced"
    assert sum(1 for r in chain if r["current_revision_status"] == "CurrentEnforced") == 1
    dates = [r["amendment_enforcement_date"] for r in chain]
    assert dates == sorted(dates), "enforced chain not ascending by enforcement date"


def test_range_num_guard_skips_and_logs(caplog):
    """range Num ガード: Article @Num に ":" を含む削除条は map に載らず INFO log される。

    Why (共通防御): e-Gov は連続削除条を "96:101" 等の range Num に畳み込む。単一 corpus
    条に帰属できず案B の安定キー前提が崩れるため diff 対象外に skip+log する (fail-safe)。
    所得税法の 96:101 / 234:236 は静的 inert (現行 corpus 非在) だが恒久ガード。
    """
    import extract_amendments as ea

    xml = (
        "<law_data_response><law_full_text><Law><LawBody><MainProvision>"
        "<Article Num='95'><Paragraph><ParagraphSentence><Sentence>本則95</Sentence>"
        "</ParagraphSentence></Paragraph></Article>"
        "<Article Num='96:101'><Paragraph><ParagraphSentence>"
        "<Sentence>第九十六条から第百一条まで削除</Sentence></ParagraphSentence></Paragraph></Article>"
        "<Article Num='102'><Paragraph><ParagraphSentence><Sentence>本則102</Sentence>"
        "</ParagraphSentence></Paragraph></Article>"
        "</MainProvision></LawBody></Law></law_full_text></law_data_response>"
    )
    with caplog.at_level(logging.INFO, logger="juricode.amendments"):
        m = ea.article_text_map(xml)
    assert set(m.keys()) == {"95", "102"}, "range Num 96:101 が map に混入 (ガード不発)"
    assert any("96:101" in rec.message for rec in caplog.records), "range Num skip の log が出ない"


def test_generalized_config_registry():
    """LAW_CONFIGS に所得税法が登録され、値が実コードと一致する (config 駆動裏取り)。"""
    import extract_amendments as ea

    assert "shotoku-zei-hou" in ea.LAW_CONFIGS
    cfg = ea.LAW_CONFIGS["shotoku-zei-hou"]
    assert cfg.law_id == "340AC0000000033"
    assert cfg.law_abbrev == "shotoku-zei-hou"
    assert cfg.window_from.isoformat() == _WINDOW_FROM
    assert cfg.corpus_dir.name == "shotoku-zei-hou"
    # 先行 (消費税・相続・法人) も registry に温存 (byte 回帰対象)。
    assert ea.LAW_CONFIGS["shouhi-zei-hou"].law_id == "363AC0000000108"
    assert ea.LAW_CONFIGS["souzoku-zei-hou"].law_id == "325AC0000000073"
    assert ea.LAW_CONFIGS["houjin-zei-hou"].law_id == "340AC0000000034"

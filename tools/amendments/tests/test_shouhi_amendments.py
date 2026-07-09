"""test_shouhi_amendments.py -- 消費税法 amendments[] populate の機械検証 (CI-safe).

Why (改正履歴 Phase 1・条文単位帰属):
    消費税法 本則 85 条のうち 52 条に、直近 5 年 (施行日 >= 2020-04-01) の改正を
    amendments[] として populate した (78 エントリ)。本 test は committed 成果物
    (data/v0.2/phase1-tax/shouhi-zei-hou/*.md) を読み、機械的な不変条件を検証する:
      - 全 amendments が IR (juricode_shared.Amendment・extra=forbid) valid。
      - エントリ総数 = 78・付与条数 = 52 (実 populate の実測値をロック)。
      - 各 (effective_date, law_num) が実 law_revisions (committed fixture) に存在
        = 捏造改正 0 (忠実性ゲート)。
      - 全 effective_date が window (>= 2020-04-01) 内。
      - description が承認形式 (本条を改正/新設/削除) に従う。
    cache/ の XML (gitignored) には依存しない = hermetic。要旨 byte 相当の忠実性は
    dry-run driver 側の diff ゲートが build 時に担保する。
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

_CORPUS = _REPO_ROOT / "data" / "v0.2" / "phase1-tax" / "shouhi-zei-hou"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "shouhi-law-revisions.json"

# 実 populate の実測値をロック (78/52)。
_EXPECTED_ENTRIES = 78
_EXPECTED_ARTICLES = 52
_WINDOW_FROM = "2020-04-01"


def _load_articles() -> list[tuple[Path, dict]]:
    """条 md の (path, frontmatter dict) を列挙する。"""
    out: list[tuple[Path, dict]] = []
    for md in sorted(_CORPUS.glob("shouhi-zei-hou-article-*.md")):
        fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
        out.append((md, fm))
    return out


def _load_revisions() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_corpus_present():
    """corpus が存在し 85 本則条ある (前提)。"""
    arts = _load_articles()
    if not arts:
        pytest.skip(f"corpus not present: {_CORPUS}")
    assert len(arts) == 85, f"expected 85 本則条, found {len(arts)}"


def test_all_amendments_ir_valid():
    """全条が IR valid で、amendments は Amendment(extra=forbid) を通る。"""
    from juricode_shared.frontmatter import article_from_frontmatter

    for md, fm in _load_articles():
        article = article_from_frontmatter(fm)  # raises on invalid
        for am in article.amendments:
            assert am.effective_date is not None
            assert am.law_num, f"{md.name}: amendment missing law_num"


def test_entry_and_article_counts_locked():
    """エントリ総数 78・付与条数 52 (dry-run 実測ロック)。"""
    total = 0
    with_amend = 0
    for _md, fm in _load_articles():
        ams = fm.get("amendments") or []
        # `amendments: []` は付与なし。
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


def test_crosscheck_known_article():
    """回帰ロック: 既知の付与条 (art-6) の amendment が残ることを固定する。

    Why: parser/map 変更で silent に落ちないよう、代表条の具体エントリを 1 件固定する。
    art-6 は 2023-10-01 施行 (平成二十八年法律第十五号・インボイス制度) で改正された。
    """
    fm = yaml.safe_load(
        (_CORPUS / "shouhi-zei-hou-article-6.md").read_text(encoding="utf-8").split("---\n", 2)[1]
    )
    keys = {(str(a["effective_date"]), a["law_num"]) for a in (fm.get("amendments") or [])}
    assert ("2023-10-01", "平成二十八年法律第十五号") in keys, "art-6 の既知改正が消えた (回帰?)"


# ---- ユニット (ロジック・hermetic) ---------------------------------------


def test_build_enforced_chain_from_fixture():
    """fixture から施行済チェーンを構築し不変条件 assert が通る。"""
    import extract_amendments as ea

    chain = ea.build_enforced_chain(_load_revisions())
    assert chain[-1]["current_revision_status"] == "CurrentEnforced"
    assert sum(1 for r in chain if r["current_revision_status"] == "CurrentEnforced") == 1
    dates = [r["amendment_enforcement_date"] for r in chain]
    assert dates == sorted(dates), "enforced chain not ascending by enforcement date"


def test_chain_assert_fails_loud_on_two_current():
    """CurrentEnforced が 2 件なら fail-loud (誤帰属せず raise)。"""
    import extract_amendments as ea

    revs = _load_revisions()
    dupe = [dict(r) for r in revs]
    # 施行済版を 1 つ余分に CurrentEnforced に化けさせる。
    n = 0
    for r in dupe:
        if r["current_revision_status"] == "PreviousEnforced":
            r["current_revision_status"] = "CurrentEnforced"
            n += 1
            if n == 1:
                break
    with pytest.raises(ValueError):
        ea.build_enforced_chain(dupe)


def test_build_description_forms():
    """description の 3 形式 (改正/新設/削除) と決定論。"""
    import extract_amendments as ea

    assert ea.build_description(None, "新条文") == "本条を新設。"
    assert ea.build_description("旧条文", None) == "本条を削除。"
    d = ea.build_description("第一号のイ", "第二号のイ")
    assert d.startswith("本条を改正（") and d.endswith("）")
    assert ea.build_description("あいう", "あXう") == ea.build_description("あいう", "あXう")


def test_article_text_map_mainprovision_only():
    """MainProvision の Article のみ抽出・附則条は除外・枝番正規化。"""
    import extract_amendments as ea

    xml = (
        "<law_data_response><law_full_text><Law><LawBody>"
        "<MainProvision><Article Num='15_2'><ArticleTitle>第十五条の二</ArticleTitle>"
        "<Paragraph><ParagraphSentence><Sentence>本則テキスト</Sentence></ParagraphSentence>"
        "</Paragraph></Article></MainProvision>"
        "<SupplProvision><Article Num='1'><Paragraph><ParagraphSentence>"
        "<Sentence>附則テキスト</Sentence></ParagraphSentence></Paragraph></Article>"
        "</SupplProvision></LawBody></Law></law_full_text></law_data_response>"
    )
    m = ea.article_text_map(xml)
    assert set(m.keys()) == {"15-2"}, "附則条が混入 or 枝番正規化ミス"
    assert "本則テキスト" in m["15-2"]
    assert "附則テキスト" not in "".join(m.values())

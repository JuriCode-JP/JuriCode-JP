"""Locked expectations for the e-Gov article-anchor index.

Every expected anchor here was measured against the rendered e-Gov DOM
(2026-07-20) or is the direct structural consequence of a measured rule.
They are LOCKED: if one of these fails, the builder regressed -- do not
re-baseline the expectation.

Measured references:
    法人税法 第132条の2   Mp-Pa_2-Ch_5-At_132_2
    法人税法 第142条の2の2 Mp-Pa_3-Ch_2-Se_1-Ss_2-At_142_2_2
    法人税法 第22条の2    Mp-Pa_2-Ch_1-Se_1-Ss_3-Di_1-At_22_2
    民法 第424条         Mp-Pa_3-Ch_1-Se_2-Ss_3-Di_1-At_424
    所得税法施行規則 第1条の2 Mp-At_1_2   (編章のない法令は短縮される)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import egov_anchor_index as AI  # noqa: E402

BASE = "https://laws.e-gov.go.jp/law/999AC0000000001"


def _write(tmp_path: Path, main_provision: str, name: str = "law.xml") -> Path:
    """Wrap a MainProvision fragment in the e-Gov API envelope."""
    p = tmp_path / name
    p.write_text(
        "<law_data_response><law_full_text><Law><LawBody>"
        f"<MainProvision>{main_provision}</MainProvision>"
        "</LawBody></Law></law_full_text></law_data_response>",
        encoding="utf-8",
    )
    return p


# ---- anchor construction --------------------------------------------------


@pytest.mark.parametrize(
    ("main_provision", "key", "expected"),
    [
        # 平坦法令: 編章が無ければダミーを挟まず Mp-At_<N> に短縮する。
        ('<Article Num="1"/>', "1", "Mp-At_1"),
        ('<Article Num="1_2"/>', "1_2", "Mp-At_1_2"),
        # 編・章
        (
            '<Part Num="1"><Chapter Num="1"><Article Num="1"/></Chapter></Part>',
            "1",
            "Mp-Pa_1-Ch_1-At_1",
        ),
        # 単一枝番 (法人税法 第132条の2 の実測形)
        (
            '<Part Num="2"><Chapter Num="5"><Article Num="132_2"/></Chapter></Part>',
            "132_2",
            "Mp-Pa_2-Ch_5-At_132_2",
        ),
        # 二重枝番 + 節/款 (法人税法 第142条の2の2 の実測形)
        (
            '<Part Num="3"><Chapter Num="2"><Section Num="1"><Subsection Num="2">'
            '<Article Num="142_2_2"/></Subsection></Section></Chapter></Part>',
            "142_2_2",
            "Mp-Pa_3-Ch_2-Se_1-Ss_2-At_142_2_2",
        ),
        # 三重枝番 (corpus に N-N-N-N が 14 件実在する)
        (
            '<Chapter Num="1"><Article Num="10_2_3_4"/></Chapter>',
            "10_2_3_4",
            "Mp-Ch_1-At_10_2_3_4",
        ),
        # 目 (Division) の略号は Di -- 民法 第424条 の実測形
        (
            '<Part Num="3"><Chapter Num="1"><Section Num="2"><Subsection Num="3">'
            '<Division Num="1"><Article Num="424"/></Division>'
            "</Subsection></Section></Chapter></Part>",
            "424",
            "Mp-Pa_3-Ch_1-Se_2-Ss_3-Di_1-At_424",
        ),
        # 枝番の章: Num を int 化すると壊れるので生文字列で積む。
        (
            '<Chapter Num="2_2"><Article Num="4_2"/></Chapter>',
            "4_2",
            "Mp-Ch_2_2-At_4_2",
        ),
        # 条が編の直下にある形 (実データに 147 件ある)
        ('<Part Num="1"><Article Num="7"/></Part>', "7", "Mp-Pa_1-At_7"),
    ],
)
def test_anchor_path_locked(tmp_path, main_provision, key, expected):
    index = AI.build_anchor_index(_write(tmp_path, main_provision))
    assert index[key] == expected


# ---- what must NOT be anchored -------------------------------------------


def test_supplementary_provisions_are_not_indexed(tmp_path):
    """附則 live in a separate namespace and are another strand's scope."""
    p = tmp_path / "law.xml"
    p.write_text(
        "<law_data_response><law_full_text><Law><LawBody>"
        '<MainProvision><Article Num="1"/></MainProvision>'
        '<SupplProvision><Article Num="22"/></SupplProvision>'
        "</LawBody></Law></law_full_text></law_data_response>",
        encoding="utf-8",
    )
    index = AI.build_anchor_index(p)
    assert index == {"1": "Mp-At_1"}


def test_appendix_and_preamble_are_not_descended(tmp_path):
    """Only the article hierarchy is walked; sibling structures are skipped."""
    index = AI.build_anchor_index(
        _write(tmp_path, '<Article Num="1"/><AppdxTable><Article Num="99"/></AppdxTable>')
    )
    assert index == {"1": "Mp-At_1"}


def test_ambiguous_article_number_is_dropped(tmp_path):
    """Two paths to one number: fall back rather than guess a wrong link."""
    index = AI.build_anchor_index(
        _write(
            tmp_path,
            '<Chapter Num="1"><Article Num="5"/></Chapter>'
            '<Chapter Num="2"><Article Num="5"/></Chapter>',
        )
    )
    assert "5" not in index


def test_structure_without_num_skips_its_subtree(tmp_path):
    """An unnamable level would poison every path beneath it."""
    index = AI.build_anchor_index(_write(tmp_path, '<Chapter><Article Num="3"/></Chapter>'))
    assert index == {}


def test_missing_main_provision_is_fatal(tmp_path):
    p = tmp_path / "law.xml"
    p.write_text("<Law><LawBody/></Law>", encoding="utf-8")
    with pytest.raises(AI.AnchorIndexError):
        AI.build_anchor_index(p)


# ---- real tracked XML (the shapes the live probe confirmed) ---------------

_REPO = Path(__file__).resolve().parents[3]
CACHE = _REPO / "cache" / "laws"

#: (law_id, article_number, expected anchor, shape). Each expected value was
#: confirmed in a real browser by tools/probe/probe-egov-anchors.py on
#: 2026-07-20: the anchor named the element AND the page landed on it. This is
#: the CI-resident half of that probe -- it cannot re-check resolution offline,
#: but it does pin the exact strings the probe blessed, so a builder change
#: that would break resolution fails here instead of in production.
#: cache/laws/*.xml is tracked (.gitignore re-includes it), so CI has the input.
MEASURED = [
    ("129AC0000000089", "1", "Mp-Pa_1-Ch_1-At_1", "平条"),
    ("129AC0000000089", "424", "Mp-Pa_3-Ch_1-Se_2-Ss_3-Di_1-At_424", "節/款/目 入れ子"),
    ("340AC0000000034", "22", "Mp-Pa_2-Ch_1-Se_1-Ss_2-At_22", "節/款 入れ子"),
    ("340AC0000000034", "132-2", "Mp-Pa_2-Ch_5-At_132_2", "単一枝番"),
    ("340AC0000000034", "142-2-2", "Mp-Pa_3-Ch_2-Se_1-Ss_2-At_142_2_2", "二重枝番"),
    ("340AC0000000034", "22-2", "Mp-Pa_2-Ch_1-Se_1-Ss_3-Di_1-At_22_2", "枝番 + 目"),
    ("340AC0000000034", "4-2", "Mp-Pa_1-Ch_2_2-At_4_2", "枝番の章 Ch_2_2"),
    ("325M50000040017", "1", "Mp-At_1", "施行規則・平坦法令"),
    ("325M50000040017", "1-2", "Mp-At_1_2", "平坦法令 + 枝番"),
    ("325CO0000000245", "48-9-7-2", "Mp-Ch_3-Se_1-At_48_9_7_2", "施行令・三重枝番"),
    ("325AC0000000226", "193", "Mp-Ch_2-Se_9-At_193", "削除条"),
    ("325AC0000000226", "19-3", "Mp-Ch_1-Se_13-Ss_1-At_19_3", "削除条 + 枝番"),
]


@pytest.mark.parametrize(
    ("law_id", "article_number", "expected", "shape"),
    MEASURED,
    ids=[f"{shape}:{law_id}:{num}" for law_id, num, _, shape in MEASURED],
)
def test_measured_anchor_from_tracked_xml(law_id, article_number, expected, shape):
    xml_path = CACHE / f"{law_id}.xml"
    if not xml_path.exists():  # pragma: no cover - tracked, but keep the skip honest
        pytest.skip(f"tracked XML absent: {xml_path}")
    index = AI.build_anchor_index(xml_path)
    assert index[AI.to_egov_article_key(article_number)] == expected


def test_deleted_article_is_anchored_like_any_other():
    """A 「削除」 article keeps a normal id -- confirmed live, so no special case."""
    index = AI.build_anchor_index(CACHE / "325AC0000000226.xml")
    assert index["193"] == "Mp-Ch_2-Se_9-At_193"


def test_supplementary_articles_absent_from_real_index():
    """At_22 occurs once in 本則 and 12 more times across 附則; only 本則 is indexed."""
    index = AI.build_anchor_index(CACHE / "340AC0000000034.xml")
    assert index["22"] == "Mp-Pa_2-Ch_1-Se_1-Ss_2-At_22"
    assert all(a.startswith("Mp-") and "-Sp-" not in a for a in index.values())


# ---- key translation ------------------------------------------------------


@pytest.mark.parametrize(
    ("article_number", "expected"),
    [("1", "1"), ("132-2", "132_2"), ("142-2-2", "142_2_2"), ("10-2-3-4", "10_2_3_4")],
)
def test_registry_number_translates_to_egov_key(article_number, expected):
    assert AI.to_egov_article_key(article_number) == expected


# ---- resolution + fallback -----------------------------------------------


def test_resolve_returns_anchored_url():
    index = {"999AC0000000001": {"132_2": "Mp-Pa_2-Ch_5-At_132_2"}}
    url, anchored = AI.resolve_article_anchor(index, "999AC0000000001", "132-2", BASE)
    assert anchored is True
    assert url == f"{BASE}#Mp-Pa_2-Ch_5-At_132_2"


@pytest.mark.parametrize(
    ("index", "law_id", "number"),
    [
        ({}, "999AC0000000001", "1"),  # XML 欠落 (法令ごと索引が無い)
        ({"999AC0000000001": {}}, "999AC0000000001", "1"),  # 本則に無い条
        ({"999AC0000000001": {"1": "Mp-At_1"}}, "OTHER", "1"),  # 別法令
    ],
)
def test_resolve_falls_back_to_law_level(index, law_id, number):
    url, anchored = AI.resolve_article_anchor(index, law_id, number, BASE)
    assert (url, anchored) == (BASE, False)

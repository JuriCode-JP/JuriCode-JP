"""Locked behaviour for the source_url anchor gate.

The gate is the offline half of "no fake links": it cannot prove an anchor
scrolls to the right article (that needs a rendered DOM), so it proves shape
and source coverage for every row instead. These tests lock what counts as
malformed -- a loosened pattern here would let bad links through CI.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[1] / "check-source-url-anchors.py"
_spec = importlib.util.spec_from_file_location("check_source_url_anchors", _GATE)
GATE = importlib.util.module_from_spec(_spec)
sys.modules["check_source_url_anchors"] = GATE
_spec.loader.exec_module(GATE)

LAW = "340AC0000000034"
BASE = f"https://laws.e-gov.go.jp/law/{LAW}"


@pytest.mark.parametrize(
    "frag",
    [
        "Mp-At_1",  # 平坦法令
        "Mp-At_1_2",
        "Mp-Pa_1-Ch_1-At_1",
        "Mp-Pa_2-Ch_5-At_132_2",
        "Mp-Pa_3-Ch_2-Se_1-Ss_2-At_142_2_2",
        "Mp-Pa_3-Ch_1-Se_2-Ss_3-Di_1-At_424",
        "Mp-Ch_2_2-At_4_2",  # 枝番の章
    ],
)
def test_measured_anchor_shapes_are_accepted(frag):
    assert GATE.classify(f"{BASE}#{frag}", LAW) == "anchored"


def test_law_level_url_is_a_counted_fallback_not_an_error():
    assert GATE.classify(BASE, LAW) == "fallback"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://laws.e-gov.go.jp/law/340AC0000000034",  # not https
        "https://laws.e-gov.go.jp/law/340AC0000000034/",  # trailing slash
        "https://example.com/law/340AC0000000034#Mp-At_1",  # wrong host
        f"{BASE}#At_1",  # 部分アンカー: 実測で解決しない
        f"{BASE}#Mp-Pa_1",  # 条まで届いていない
        f"{BASE}#Mp-Dv_1-At_1",  # 目の略号は Di
        f"{BASE}#340AC0000000034-Sp-At_22",  # 附則名前空間
        f"{BASE}#:~:text=%E7%AC%AC%E4%B8%80%E6%9D%A1",  # text fragment: 却下済
    ],
)
def test_malformed_urls_are_rejected(url):
    assert GATE.classify(url, LAW) == "malformed"


def test_anchor_law_id_must_match_the_row():
    assert GATE.classify("https://laws.e-gov.go.jp/law/OTHER#Mp-At_1", LAW) == "malformed"


def _write_docs(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "documents.jsonl"
    p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
        newline="\n",
    )
    return p


def test_only_statute_article_rows_are_checked(tmp_path):
    """附則 (no article_number) and other layers keep their own URL rules."""
    docs = _write_docs(
        tmp_path,
        [
            {
                "juri_id": "a",
                "layer": "statute",
                "law_id": LAW,
                "article_number": "1",
                "source_url": f"{BASE}#Mp-At_1",
            },
            {
                "juri_id": "s",
                "layer": "statute",
                "law_id": LAW,
                "article_number": None,
                "source_url": BASE,
            },
            {
                "juri_id": "t",
                "layer": "tsutatsu",
                "law_id": None,
                "article_number": None,
                "source_url": "https://www.nta.go.jp/law/t/1.htm",
            },
        ],
    )
    counts, samples, law_ids = GATE.check_documents(docs)
    assert counts == {"anchored": 1, "fallback": 0, "malformed": 0}
    assert samples == []
    assert law_ids == {LAW}


def test_missing_tracked_xml_is_reported(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{LAW}.xml").write_text("<Law/>", encoding="utf-8")
    assert GATE.check_coverage(cache, {LAW}) == []
    assert GATE.check_coverage(cache, {LAW, "MISSING"}) == ["MISSING"]

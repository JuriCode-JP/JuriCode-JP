"""Unit tests for citation verification (juricode_verifier.citations, G1/G2).

Pure-Python (no network): the checks are pure functions, so CI runs them without
any provider. G1 = citation existence, G2 = verbatim quote (with failure breakdown).
"""

from __future__ import annotations

from juricode_verifier import check_citations_exist, check_quotes_verbatim, valid_citations_only

# ---- G1: citation existence ----


def test_g1_rejects_unknown_chunk_id():
    v = check_citations_exist([{"chunk_id": "ghost"}], allowed_chunk_ids={"real-1"})
    assert [x.code for x in v] == ["G1"]


def test_g1_accepts_known_chunk_id():
    assert check_citations_exist([{"chunk_id": "real-1"}], {"real-1"}) == []


# ---- G2: server-cut quote verified against source bytes (with breakdown) ----


def test_g2_accepts_server_cut_substring():
    texts = {"c1": "第一条 この法律は正当防衛について定める。"}
    v = check_quotes_verbatim([{"chunk_id": "c1", "quote": "正当防衛について定める"}], texts)
    assert v == []


def test_g2_anchor_not_locatable_when_quote_none():
    # anchor が原文に位置特定できず quote=None -> "anchor not locatable" 区分の G2 違反。
    texts = {"c1": "第一条 この法律は正当防衛について定める。"}
    v = check_quotes_verbatim([{"chunk_id": "c1", "anchor": "言い換え", "quote": None}], texts)
    assert [x.code for x in v] == ["G2"]
    assert "anchor not locatable" in v[0].detail


def test_g2_snapped_quote_mismatch_is_flagged_as_impl_bug():
    # サーバー切り出しが原文に無い (= 構造上あり得ないはずのバグ) -> "snapped_quote_mismatch"。
    texts = {"c1": "第一条 この法律は正当防衛について定める。"}
    v = check_quotes_verbatim([{"chunk_id": "c1", "quote": "原文にない語"}], texts)
    assert [x.code for x in v] == ["G2"]
    assert "snapped_quote_mismatch" in v[0].detail


def test_g2_rejects_when_body_missing():
    v = check_quotes_verbatim([{"chunk_id": "c1", "quote": "x"}], chunk_texts={})
    assert [x.code for x in v] == ["G2"]


# ---- valid_citations_only: G1+G2 filter ----


def test_valid_citations_only_keeps_grounded():
    texts = {"c1": "本文AAA", "c2": "本文BBB"}
    cits = [
        {"chunk_id": "c1", "quote": "本文A"},  # ok
        {"chunk_id": "ghost", "quote": "x"},  # G1 fail
        {"chunk_id": "c2", "quote": "存在しない"},  # G2 fail
    ]
    kept = valid_citations_only(cits, {"c1", "c2"}, texts)
    assert [c["chunk_id"] for c in kept] == ["c1"]

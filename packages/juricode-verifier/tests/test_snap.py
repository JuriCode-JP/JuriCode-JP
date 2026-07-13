"""Unit tests for server-side quote snapping (juricode_verifier.snap).

Pure-Python (no network). Locks the core invariant: the returned quote is
always a verbatim (byte) substring of the body, and normalization is used only to LOCATE
the anchor (never returned). Covers whitespace-shifted anchors, cut range, and
the invariant across all cases.
"""

from __future__ import annotations

from juricode_verifier import snap_quote

BODY = "第三十六条　急迫不正の侵害に対して、自己又は他人の権利を防衛するため、\nやむを得ずにした行為は、罰しない。"


def test_exact_anchor_locates_and_returns_original_bytes():
    q = snap_quote("急迫不正の侵害に対して", BODY)
    assert q is not None
    assert q in BODY  # invariant: verbatim substring
    assert q.startswith("急迫不正の侵害に対して")


def test_whitespace_shifted_anchor_still_locates():
    # anchor に無い空白・改行・全角空白を混ぜても位置特定でき、返る引用は原文のバイト列。
    shifted = "急迫不正の 侵害\nに対　して"
    q = snap_quote(shifted, BODY)
    assert q is not None
    assert q in BODY  # returned bytes are the ORIGINAL, not the normalized anchor
    assert "急迫不正の侵害に対して" in q


def test_cut_extends_to_sentence_end():
    # 句点まで延ばす (改行を挟まない本文)。返りは句点で終わる原文スライス。
    body = "急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。"
    q = snap_quote("自己又は他人の権利", body)
    assert q is not None
    assert q.endswith("。")
    assert q in body


def test_cut_stops_at_paragraph_boundary_before_sentence_end():
    body = "第一項の前段である。\n第二項はここから始まる。"
    # 段落境界 (改行) が句点より先に来るケースでは改行の手前で止まる。
    q = snap_quote("第一項の前段", body)
    assert q is not None
    assert "\n" not in q
    assert q in body


def test_max_len_truncation():
    body = "あ" * 500
    q = snap_quote("あああ", body, max_len=50)
    assert q is not None
    assert len(q) <= 50
    assert q in body


def test_paraphrase_anchor_not_locatable():
    assert snap_quote("原文に存在しない言い換え表現", BODY) is None


def test_empty_anchor_returns_none():
    assert snap_quote("", BODY) is None
    assert snap_quote("   \n　", BODY) is None


def test_invariant_returned_quote_is_always_substring():
    # 不変条件: いくつもの anchor で、返る引用が常に原文の byte 部分文字列であること。
    anchors = [
        "第三十六条",
        "急迫不正",
        "自己又は他人の権利を防衛",
        "やむを得ずにした行為",
        "罰しない",
        "急　迫\n不正",  # whitespace-injected
    ]
    for a in anchors:
        q = snap_quote(a, BODY)
        assert q is not None, f"anchor should locate: {a!r}"
        assert q in BODY, f"returned quote not verbatim for anchor {a!r}: {q!r}"

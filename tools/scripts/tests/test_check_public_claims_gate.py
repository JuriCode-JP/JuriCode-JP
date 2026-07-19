"""Tests for the outward guarantee-claims gate (VA-5).

The gate driver reads only BOARD_FILES, never this file, so `scan_text` can be
exercised here with literal guarantee words and accuracy figures without the gate
ever flagging the test itself. These lock the guard: the adjacency window, the
metric regex, and each exclusion class are pinned so a later edit that weakens one
fails here instead of silently letting a bare claim back onto a board.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_GATE = Path(__file__).resolve().parents[1] / "check-public-claims-gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_public_claims_gate", _GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


def test_bare_guarantee_is_flagged():
    # A guarantee word with no gate id after it is a bare promise -> flagged.
    bare, metrics = gate.scan_text("This corpus is a verbatim copy of the source.")
    assert len(bare) == 1
    assert metrics == []


def test_adjacent_gate_id_passes():
    # The gate id sits within the adjacency window right after the word -> clean.
    bare, _ = gate.scan_text("This corpus is a verbatim [G2] copy of the source.")
    assert bare == []


def test_far_gate_id_is_flagged():
    # A gate id past the window (25 chars) does not back the word -> flagged.
    bare, _ = gate.scan_text("This is verbatim and then a long stretch of prose [G2] here.")
    assert len(bare) == 1


def test_gate_id_on_another_line_is_flagged():
    # Option B is same-line: an id on the next line does not back the word.
    bare, _ = gate.scan_text("The corpus is verbatim.\nBacked by [G2] elsewhere.")
    assert any(lineno == 1 for lineno, _ in bare)


def test_accuracy_figure_is_flagged():
    _, metrics = gate.scan_text("Re-measured: Recall@3 = 100% held on the eval set.")
    assert len(metrics) == 1


def test_metric_definition_without_digit_passes():
    # "Recall@K" is a definition, not a figure (boundary+digit regex).
    _, metrics = gate.scan_text("See methodology for Recall@K definitions.")
    assert metrics == []


def test_date_log_line_excludes_word_but_not_metric():
    # A dated progress-log bullet excuses the guarantee WORD, but the accuracy
    # figure on that same line is still banned.
    line = "- **2026-05-20 (完了)**: round-trip 検証済 with Recall@3 = 100%"
    bare, metrics = gate.scan_text(line)
    assert bare == []
    assert len(metrics) == 1


def test_goal_declaration_is_excluded():
    # A stated aim (北極星 / 最終ビジョン marker) is not a current guarantee.
    line = "北極星: すべての公務員が使える検証済みの公共法令インフラ。"
    bare, _ = gate.scan_text(line)
    assert bare == []


def test_disclaimer_is_excluded():
    # A line that withdraws the claim ("完全な一覧ではない") is not a promise.
    line = "amendments[] はその条文に対する改正の完全な一覧ではない。"
    bare, _ = gate.scan_text(line)
    assert bare == []

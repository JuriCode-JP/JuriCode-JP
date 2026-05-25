"""Tests for PARAGRAPH_HEADING_PATTERN (FU-301).

Why this test exists:
    The single-source-of-truth `PARAGRAPH_HEADING_PATTERN` in segment_parser.py
    is used both for matching headings and splitting body text. A regression in
    this pattern would silently produce empty chunks (cf. 既知事故 (g) — 4,810
    empty chunks before the 枝番条 regex fix).

    Coverage targets:
    - 基本形: 第N条 (no paragraph)
    - 枝番条: 第N条のM (e.g. 第三条の二)
    - 項番号付き: 第N条第K項
    - 枝番条 + 項番号: 第N条のM第K項
    - body split で sections の数が期待通りになる
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running this file directly via `python -m pytest tests/...`
# (segment_parser.py is in the parent dir, not on PYTHONPATH by default)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from segment_parser import PARAGRAPH_HEADING_PATTERN  # noqa: E402  (must follow sys.path tweak)

# ===========================================================
# Match tests (line-level)
# ===========================================================


def test_match_basic_article() -> None:
    """第N条 (項番号なし) が match する."""
    assert PARAGRAPH_HEADING_PATTERN.match("### 第三十六条")
    assert PARAGRAPH_HEADING_PATTERN.match("### 第一条")
    assert PARAGRAPH_HEADING_PATTERN.match("### 第百九十七条")


def test_match_branch_article() -> None:
    """枝番条 第N条のM が match する (既知事故 (g) の再発防止)."""
    assert PARAGRAPH_HEADING_PATTERN.match("### 第三条の二")
    assert PARAGRAPH_HEADING_PATTERN.match("### 第百九十七条の三")
    assert PARAGRAPH_HEADING_PATTERN.match("### 第六条の十")


def test_match_article_with_paragraph() -> None:
    """第N条第K項 が match する."""
    assert PARAGRAPH_HEADING_PATTERN.match("### 第三十六条第二項")
    assert PARAGRAPH_HEADING_PATTERN.match("### 第一条第一項")


def test_match_branch_article_with_paragraph() -> None:
    """枝番条 + 項番号 第N条のM第K項 が match する (最複雑系)."""
    assert PARAGRAPH_HEADING_PATTERN.match("### 第百九十七条の三第二項")
    assert PARAGRAPH_HEADING_PATTERN.match("### 第三条の二第一項")


def test_match_trailing_whitespace() -> None:
    """末尾の空白を許容する (\\s*$)."""
    assert PARAGRAPH_HEADING_PATTERN.match("### 第一条   ")
    assert PARAGRAPH_HEADING_PATTERN.match("### 第三条の二第一項  \t")


def test_no_match_for_other_headings() -> None:
    """他の見出しに誤マッチしない."""
    assert PARAGRAPH_HEADING_PATTERN.match("### 第一節") is None
    assert PARAGRAPH_HEADING_PATTERN.match("## 原文") is None
    assert PARAGRAPH_HEADING_PATTERN.match("### Article 36") is None
    assert PARAGRAPH_HEADING_PATTERN.match("# 第一条") is None  # # の数が違う
    assert PARAGRAPH_HEADING_PATTERN.match("第一条") is None  # ### がない


def test_no_match_with_extra_content() -> None:
    """見出し行に余計な content があると match しない."""
    assert PARAGRAPH_HEADING_PATTERN.match("### 第一条 (本文)") is None
    assert PARAGRAPH_HEADING_PATTERN.match("### 第一条 — 補足") is None


# ===========================================================
# Split tests (body-level)
# ===========================================================


def test_split_single_article() -> None:
    """1 つの見出しで分割すると 2 sections."""
    body = "## 原文\n\n### 第一条\n\n本文。\n"
    sections = PARAGRAPH_HEADING_PATTERN.split(body)
    assert len(sections) == 2
    assert sections[0] == "## 原文\n\n"
    assert "本文。" in sections[1]


def test_split_multiple_articles() -> None:
    """N 個の見出しで分割すると N+1 sections (capture group なし設計の確認)."""
    body = "## 原文\n### 第一条\n本文 A\n### 第二条\n本文 B\n### 第三条\n本文 C\n"
    sections = PARAGRAPH_HEADING_PATTERN.split(body)
    # capture group があると len は変わるが、設計上 capture なしなので 4 sections
    assert len(sections) == 4, (
        f"Expected 4 sections (capture-group-free split), got {len(sections)}. "
        f"If this fails, capture groups were re-introduced — see FU-301 Why comment."
    )


def test_split_with_branch_articles() -> None:
    """枝番条が混じった body の分割 (既知事故 (g) の最重要シナリオ)."""
    body = "## 原文\n### 第一条\n本文 1\n### 第一条の二\n本文 1-2\n### 第二条\n本文 2\n"
    sections = PARAGRAPH_HEADING_PATTERN.split(body)
    assert len(sections) == 4
    # 各 section が空でないこと (FU-301 の本質: empty chunks 量産を防ぐ)
    for i, s in enumerate(sections[1:], 1):
        assert s.strip(), f"section[{i}] is empty — regex split が失敗"


def test_split_with_paragraph_numbers() -> None:
    """項番号付き見出しを境に分割."""
    body = "### 第三十六条\n第 1 項本文\n### 第三十六条第二項\n第 2 項本文\n"
    sections = PARAGRAPH_HEADING_PATTERN.split(body)
    assert len(sections) == 3
    assert sections[0] == ""  # 見出しから始まるので最初は空
    assert "第 1 項本文" in sections[1]
    assert "第 2 項本文" in sections[2]


def test_split_preserves_content_between_headings() -> None:
    """見出し以外の content が失われない (内容保持の不変条件)."""
    body = (
        "intro before any heading\n"
        "### 第一条\n"
        "body of art 1\n"
        "## English Translation\n"
        "Article 1 translation\n"
    )
    sections = PARAGRAPH_HEADING_PATTERN.split(body)
    assert "intro before" in sections[0]
    assert "body of art 1" in sections[1]
    assert "Article 1 translation" in sections[1]  # English も section 1 に含まれる


# ===========================================================
# Regression guard for known incident (g)
# ===========================================================


def test_no_regression_known_incident_g() -> None:
    """既知事故 (g) のシナリオ: 4,810 件 empty chunks を生んだ regex 漏れ条件.

    枝番条 (第N条のM) が match しないと、その見出しが split で「分割境界」
    にならず、前後の段落が 1 つに合体し、後続条文が empty body になる。
    本テストは、枝番条見出しが正しく split されることを保証する。
    """
    body_with_branch_articles = (
        "### 第三条\n"
        "通常の第三条 body\n"
        "### 第三条の二\n"
        "枝番条 body (これが empty になっていた)\n"
        "### 第三条の三\n"
        "もう一つの枝番条 body\n"
        "### 第四条\n"
        "次の条 body\n"
    )
    sections = PARAGRAPH_HEADING_PATTERN.split(body_with_branch_articles)
    # 4 見出し -> 5 sections (capture-group なし)
    assert len(sections) == 5, (
        f"Expected 5 sections, got {len(sections)}. 枝番条 regex 漏れの回帰の可能性"
    )
    # 全 body section が non-empty
    for i, body_section in enumerate(sections[1:], 1):
        stripped = body_section.strip()
        assert stripped, f"section[{i}] is empty -- empty chunks の再発リスク (FU-301)"

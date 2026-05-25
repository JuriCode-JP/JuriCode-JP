"""Tests for render_v02_md scope limitation + warnings (FU-303).

Why this test exists:
    Old `render_v02_md` performed `body.replace(search_str, ..., 1)` on the
    *entire* body. This had two failure modes:
      (a) The same 20-char prefix appeared in `## English Translation` section,
          causing markers to be inserted into English text by mistake.
      (b) If `seg.text[:20]` contained `\n`, `.strip()` produced a string that
          did not match the actual body content -> silent no-hit, marker lost.

    FU-303 limits insertion scope to the corresponding paragraph slice and
    records every failure in `parsing_warnings`. This file guards both
    behaviors with regression tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from segment_parser import ParagraphV02, Segment, render_v02_md  # noqa: E402

# ===========================================================
# Helpers
# ===========================================================


def _mk_seg(seg_id: str, type_: str, text: str) -> Segment:
    """Minimal Segment for testing (default modality, no flags)."""
    return Segment(
        id=seg_id,
        type=type_,
        text=text,
        modality="hyojun",
    )


def _mk_para(number: int, segments: list[Segment]) -> ParagraphV02:
    return ParagraphV02(
        number=number,
        segments=segments,
        has_proviso=False,
        has_items=False,
        is_added_by_amendment=False,
    )


# ===========================================================
# Scope limitation: English Translation must not be touched
# ===========================================================


def test_marker_not_inserted_into_english_translation() -> None:
    """同じ 20-char prefix が英訳に含まれていても marker は本文側のみ."""
    # Japanese body contains "急迫不正の侵害" and English duplicates the marker target.
    # In the old buggy code, "search_str" could land in the English block first.
    body = (
        "## 原文\n\n"
        "### 第一条\n"
        "急迫不正の侵害に対して、自己又は他人の権利を防衛するため。\n"
        "\n"
        "## English Translation\n"
        "### Article 1\n"
        "急迫不正の侵害 = imminent and unjust infringement.\n"
    )
    seg = _mk_seg("test-art-1-p1-honbun", "honbun", "急迫不正の侵害に対して、自己又は他人の権利")
    para = _mk_para(1, [seg])
    warnings: list[str] = []
    out = render_v02_md({"article_id": "test-art-1"}, [para], body, parsing_warnings=warnings)
    # マーカーは本文側 (### 第一条 と ## English の間) にだけ存在
    en_idx = out.find("## English Translation")
    ja_part = out[:en_idx]
    en_part = out[en_idx:]
    assert "<!-- segment: honbun" in ja_part, f"marker not found in Japanese body. Output:\n{out}"
    assert "<!-- segment:" not in en_part, (
        f"marker leaked into English Translation section!\n{en_part}"
    )
    assert warnings == [], f"Unexpected warnings: {warnings}"


# ===========================================================
# Failure modes: warnings should be recorded
# ===========================================================


def test_warning_when_no_paragraph_headings() -> None:
    """見出しがない body で segment があると warning."""
    body = "## 原文\n\n本文だけで見出しなし\n"
    seg = _mk_seg("x", "honbun", "本文だけで")
    para = _mk_para(1, [seg])
    warnings: list[str] = []
    render_v02_md({}, [para], body, parsing_warnings=warnings)
    assert len(warnings) >= 1
    assert "no paragraph headings" in warnings[0]


def test_warning_when_paragraph_number_out_of_range() -> None:
    """paragraph_number が body の見出し数を超えると warning."""
    body = "## 原文\n\n### 第一条\n本文 A\n"
    # paragraph 2 を指定するが body には paragraph 1 しかない
    seg = _mk_seg("x", "honbun", "non-existent")
    para = _mk_para(2, [seg])
    warnings: list[str] = []
    render_v02_md({}, [para], body, parsing_warnings=warnings)
    assert any("out of range" in w for w in warnings), warnings


def test_warning_when_search_str_not_found() -> None:
    """text が body に含まれないと warning (typo 等)."""
    body = "## 原文\n\n### 第一条\n本文 A\n"
    seg = _mk_seg("x", "honbun", "違う本文")  # body に存在しない
    para = _mk_para(1, [seg])
    warnings: list[str] = []
    render_v02_md({}, [para], body, parsing_warnings=warnings)
    assert any("not found in paragraph" in w for w in warnings), warnings


def test_warning_on_empty_search_str() -> None:
    """text が空白のみだと warning."""
    body = "## 原文\n\n### 第一条\n本文\n"
    seg = _mk_seg("x", "honbun", "   ")  # whitespace only
    para = _mk_para(1, [seg])
    warnings: list[str] = []
    render_v02_md({}, [para], body, parsing_warnings=warnings)
    assert any("empty search_str" in w for w in warnings), warnings


# ===========================================================
# Newline handling: text starting with multi-line content
# ===========================================================


def test_marker_inserted_even_when_text_starts_with_long_first_line() -> None:
    """seg.text が長い 1 行で始まる場合、最初の 20 文字で検索成功."""
    long_first_line = "急迫不正の侵害に対して、自己又は他人の権利を防衛するため、やむを得ずにした行為は、罰しない。"
    body = f"### 第一条\n{long_first_line}\n次の行\n"
    seg = _mk_seg("x", "honbun", long_first_line)
    para = _mk_para(1, [seg])
    warnings: list[str] = []
    out = render_v02_md({}, [para], body, parsing_warnings=warnings)
    assert "<!-- segment:" in out
    assert warnings == [], warnings


# ===========================================================
# Backwards compatibility: parsing_warnings is optional
# ===========================================================


def test_parsing_warnings_argument_optional() -> None:
    """既存呼び出し側を壊さないため、parsing_warnings なしでも動く."""
    body = "### 第一条\n本文\n"
    seg = _mk_seg("x", "honbun", "本文")
    para = _mk_para(1, [seg])
    # warnings なしで呼んでも例外を投げない
    out = render_v02_md({}, [para], body)
    assert isinstance(out, str)

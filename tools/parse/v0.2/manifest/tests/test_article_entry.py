"""Tests for manifest/article_entry.py.

Coverage targets:
  - Pydantic field validation (pattern / ge constraints)
  - extra="forbid" / frozen=True
  - build_article_entry happy path (frontmatter + body 完備)
  - build_article_entry エッジケース (frontmatter 欠落、article_id 不正、
    law_abbrev mismatch, file 不在, YAML invalid)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

# manifest パッケージを import 可能にする (parent dir = tools/parse/v0.2/)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from manifest.article_entry import ArticleEntry, build_article_entry  # noqa: E402

# ============================================================
# Pydantic model validation
# ============================================================


def _valid_kwargs() -> dict:
    """Default valid ArticleEntry kwargs for incremental mutation in tests."""
    return {
        "article_id": "minpou-art-770",
        "article_number": "770",
        "filename": "minpou-article-770.md",
        "ja_text_sha256": "a" * 64,
        "ja_text_bytes": 123,
        "paragraph_count": 2,
    }


def test_model_accepts_valid_input() -> None:
    """全 field 妥当 → 構築成功."""
    entry = ArticleEntry(**_valid_kwargs())
    assert entry.article_id == "minpou-art-770"


def test_model_is_frozen() -> None:
    """frozen=True → 構築後 mutate 不可."""
    entry = ArticleEntry(**_valid_kwargs())
    with pytest.raises(ValidationError):
        entry.article_id = "other-art-1"  # type: ignore[misc]


def test_model_rejects_extra_field() -> None:
    """extra='forbid' → 未知 field は ValidationError."""
    kwargs = _valid_kwargs()
    kwargs["unknown_field"] = "x"
    with pytest.raises(ValidationError, match="unknown_field"):
        ArticleEntry(**kwargs)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("article_id", "INVALID UPPERCASE"),  # 大文字 NG
        ("article_id", "noartdash"),  # -art- 区切り無し
        ("article_id", "minpou-art-"),  # 後ろが空
        ("article_id", "-art-1"),  # law_abbrev が空 (先頭 [a-z] 違反)
        ("article_number", "abc"),  # 数字以外
        ("article_number", "36-"),  # 末尾 dash
        ("filename", "../traversal.md"),  # path traversal
        ("filename", "with space.md"),  # space 不可
        ("ja_text_sha256", "g" * 64),  # hex 以外
        ("ja_text_sha256", "a" * 63),  # 短い
        ("ja_text_sha256", "A" * 64),  # 大文字 (小文字必須)
        ("ja_text_bytes", -1),  # 負数
        ("paragraph_count", 0),  # 0 不可 (ge=1)
        ("paragraph_count", -1),
    ],
)
def test_model_rejects_invalid_field(field: str, bad_value: object) -> None:
    """pattern / ge 違反は ValidationError."""
    kwargs = _valid_kwargs()
    kwargs[field] = bad_value
    with pytest.raises(ValidationError):
        ArticleEntry(**kwargs)


def test_model_accepts_branch_article_id() -> None:
    """枝番条 article_id (e.g. 'keihou-art-36-2') OK."""
    kwargs = _valid_kwargs()
    kwargs["article_id"] = "keihou-art-36-2"
    kwargs["article_number"] = "36-2"
    kwargs["filename"] = "keihou-article-36-2.md"
    entry = ArticleEntry(**kwargs)
    assert entry.article_number == "36-2"


# ============================================================
# build_article_entry
# ============================================================


def _build_v02_md(article_id: str, article_number: str, body: str = "本文.") -> str:
    """テスト用 v0.2 .md 文字列を生成."""
    return (
        "---\n"
        f"article_id: {article_id}\n"
        f"article_number: '{article_number}'\n"
        "---\n\n"
        "# Title\n\n"
        "## 原文 (日本語)\n\n"
        f"### 第一条\n\n{body}\n"
    )


def test_build_happy_path(tmp_path: Path) -> None:
    """frontmatter + body 完備 → ArticleEntry 構築."""
    md = tmp_path / "keihou-article-36.md"
    md.write_text(_build_v02_md("keihou-art-36", "36"), encoding="utf-8")
    entry = build_article_entry(md, expected_law_abbrev="keihou")
    assert entry.article_id == "keihou-art-36"
    assert entry.article_number == "36"
    assert entry.filename == "keihou-article-36.md"
    assert len(entry.ja_text_sha256) == 64
    assert entry.paragraph_count >= 1


def test_build_raises_on_missing_file(tmp_path: Path) -> None:
    """file 不在 → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        build_article_entry(tmp_path / "ghost.md")


def test_build_raises_on_missing_frontmatter_open(tmp_path: Path) -> None:
    """frontmatter 開デリミタ無し → ValueError."""
    md = tmp_path / "noopen.md"
    md.write_text("# Title\n\n## 原文 (日本語)\n\n### 第一条\n\n本文.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frontmatter opening delimiter"):
        build_article_entry(md)


def test_build_raises_on_missing_frontmatter_close(tmp_path: Path) -> None:
    """frontmatter 閉デリミタ無し → ValueError."""
    md = tmp_path / "noclose.md"
    md.write_text("---\nfoo: bar\n\n本文.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frontmatter closing delimiter"):
        build_article_entry(md)


def test_build_raises_on_invalid_yaml(tmp_path: Path) -> None:
    """frontmatter が壊れた YAML → ValueError."""
    md = tmp_path / "badyaml.md"
    md.write_text(
        "---\n: : : invalid\n---\n\n## 原文 (日本語)\n\n### 第一条\n\n本文.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        build_article_entry(md)


def test_build_raises_on_missing_article_id(tmp_path: Path) -> None:
    """frontmatter に article_id 無し → ValueError."""
    md = tmp_path / "noid.md"
    md.write_text(
        "---\narticle_number: '1'\n---\n\n## 原文 (日本語)\n\n### 第一条\n\n本文.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required field"):
        build_article_entry(md)


def test_build_raises_on_law_abbrev_mismatch(tmp_path: Path) -> None:
    """ファイル名と expected_law_abbrev が不一致 → ValueError."""
    md = tmp_path / "keihou-article-36.md"
    md.write_text(_build_v02_md("keihou-art-36", "36"), encoding="utf-8")
    with pytest.raises(ValueError, match="law_abbrev mismatch"):
        build_article_entry(md, expected_law_abbrev="minpou")


def test_build_accepts_integer_article_number(tmp_path: Path) -> None:
    """frontmatter の article_number が int でも str に変換して受ける.

    Why: YAML パーサは '36' を str、36 を int として読む可能性があり、
    どちらも実害なしなので int → str 変換で許容する.
    """
    md = tmp_path / "test-article-36.md"
    md.write_text(
        "---\narticle_id: test-art-36\narticle_number: 36\n---\n\n"
        "## 原文 (日本語)\n\n### 第一条\n\n本文.\n",
        encoding="utf-8",
    )
    entry = build_article_entry(md)
    assert entry.article_number == "36"

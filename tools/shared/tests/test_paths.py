"""ファイル配置ルールのテスト."""

from pathlib import Path

from juricode_shared.paths import article_path


def test_article_path_basic() -> None:
    p = article_path("keihou", "36")
    assert p == Path("data/phase1-police/keihou/keihou-article-36.md")


def test_article_path_with_branch() -> None:
    p = article_path("keihou", "36-2")
    assert p == Path("data/phase1-police/keihou/keihou-article-36-2.md")


def test_article_path_custom_root() -> None:
    p = article_path("keihou", "36", root="/repo/data")
    assert p == Path("/repo/data/phase1-police/keihou/keihou-article-36.md")


def test_article_path_long_abbrev() -> None:
    p = article_path("keiji-soshou-hou", "198")
    assert p == Path("data/phase1-police/keiji-soshou-hou/keiji-soshou-hou-article-198.md")

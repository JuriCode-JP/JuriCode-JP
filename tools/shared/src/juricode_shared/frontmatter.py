"""YAML frontmatter ヘルパ: Markdown ファイル <-> Python dict <-> JuriCodeArticle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from juricode_shared.ir import JuriCodeArticle

FRONTMATTER_DELIM = "---"


def parse_frontmatter_text(text: str) -> tuple[dict[str, Any], str]:
    """Markdown 文字列から frontmatter と本文を分離.

    Returns:
        (frontmatter_dict, body_markdown) のタプル.

    Raises:
        ValueError: フロントマターのデリミタが見つからない場合.
    """
    if not text.startswith(FRONTMATTER_DELIM):
        raise ValueError(f"File does not start with frontmatter delimiter ({FRONTMATTER_DELIM})")

    # 最初の --- の次から検索
    lines = text.split("\n")
    if lines[0].strip() != FRONTMATTER_DELIM:
        raise ValueError("Invalid frontmatter opening")

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_DELIM:
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("Frontmatter closing delimiter not found")

    fm_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")

    fm_dict = yaml.safe_load(fm_text) or {}
    return fm_dict, body


def parse_frontmatter(path: Path | str) -> tuple[dict[str, Any], str]:
    """Markdown ファイルから frontmatter と本文を分離."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_frontmatter_text(text)


def article_from_frontmatter(fm_dict: dict[str, Any]) -> JuriCodeArticle:
    """frontmatter dict から JuriCodeArticle を構築."""
    return JuriCodeArticle.model_validate(fm_dict)


def dump_frontmatter(article: JuriCodeArticle) -> str:
    """JuriCodeArticle を YAML frontmatter 文字列にダンプ."""
    data = article.model_dump(exclude_none=True, mode="json")
    yaml_str = yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"{FRONTMATTER_DELIM}\n{yaml_str}{FRONTMATTER_DELIM}\n"

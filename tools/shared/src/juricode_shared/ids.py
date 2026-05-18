"""ID 規約: article_id / case_id の生成と検証."""

from __future__ import annotations

import re
from datetime import date

ARTICLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-art-[0-9]+(-[0-9]+)*$")
CASE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,9}-[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+$")
ARTICLE_NUMBER_PATTERN = re.compile(r"^[0-9]+(-[0-9]+)*$")
LAW_ABBREV_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def make_article_id(law_abbrev: str, article_number: str) -> str:
    """法令略称と条番号から article_id を生成.

    Examples:
        >>> make_article_id("keihou", "36")
        'keihou-art-36'
        >>> make_article_id("keihou", "36-2")
        'keihou-art-36-2'
    """
    if not LAW_ABBREV_PATTERN.match(law_abbrev):
        raise ValueError(
            f"Invalid law_abbrev: {law_abbrev!r}. Must match {LAW_ABBREV_PATTERN.pattern}"
        )
    if not ARTICLE_NUMBER_PATTERN.match(article_number):
        raise ValueError(
            f"Invalid article_number: {article_number!r}. Must match {ARTICLE_NUMBER_PATTERN.pattern}"
        )
    return f"{law_abbrev}-art-{article_number}"


def validate_article_id(article_id: str) -> bool:
    """article_id がパターンに合致するか."""
    return bool(ARTICLE_ID_PATTERN.match(article_id))


def make_case_id(
    court_abbrev: str,
    decision_date: date,
    citation_slug: str,
) -> str:
    """判例 ID を生成.

    Args:
        court_abbrev: 裁判所略号(例: "scj", "scj-pb1", "oh", "tdc")
        decision_date: 判決日
        citation_slug: 掲載誌・巻号スラグ(例: "keishu-23-12-1573")

    Examples:
        >>> from datetime import date
        >>> make_case_id("scj-pb1", date(1969, 12, 4), "keishu-23-12-1573")
        'scj-pb1-1969-12-04-keishu-23-12-1573'
    """
    return f"{court_abbrev}-{decision_date.isoformat()}-{citation_slug}"

"""frontmatter ヘルパのテスト."""

from datetime import date

import pytest

from juricode_shared.frontmatter import (
    article_from_frontmatter,
    dump_frontmatter,
    parse_frontmatter_text,
)
from juricode_shared.ir import (
    JuriCodeArticle,
    Paragraph,
    TranslationStatus,
)

SAMPLE_MD = """---
law_id: 140AC0000000045
law_name_ja: 刑法
law_name_en: Penal Code
article_number: "36"
article_id: keihou-art-36
version_date: 2007-06-12
translation_status: none
source_url: https://laws.e-gov.go.jp/law/140AC0000000045
last_verified: 2026-05-18
license: MIT
paragraphs:
  - number: 1
    text: 急迫不正の侵害に対して...
    has_proviso: false
    items: []
  - number: 2
    text: 防衛の程度を超えた行為は...
    has_proviso: false
    items: []
tags:
  - phase1-police
  - 刑事法
  - 正当防衛
---

# 刑法 第36条 (正当防衛)

## 原文 (日本語)

### 第三十六条
...
"""


def test_parse_frontmatter_text_basic() -> None:
    fm, body = parse_frontmatter_text(SAMPLE_MD)
    assert fm["law_id"] == "140AC0000000045"
    assert fm["article_number"] == "36"
    assert len(fm["paragraphs"]) == 2
    assert "# 刑法 第36条" in body


def test_parse_frontmatter_missing_delim() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_frontmatter_text("no frontmatter here")


def test_article_from_frontmatter() -> None:
    fm, _ = parse_frontmatter_text(SAMPLE_MD)
    article = article_from_frontmatter(fm)
    assert article.article_id == "keihou-art-36"
    assert article.translation_status == TranslationStatus.NONE
    assert len(article.paragraphs) == 2


def test_dump_frontmatter_roundtrip() -> None:
    """JuriCodeArticle → frontmatter → JuriCodeArticle ラウンドトリップ."""
    original = JuriCodeArticle(
        law_id="140AC0000000045",
        law_name_ja="刑法",
        law_name_en="Penal Code",
        article_number="36",
        article_id="keihou-art-36",
        version_date=date(2007, 6, 12),
        translation_status=TranslationStatus.NONE,
        source_url="https://laws.e-gov.go.jp/law/140AC0000000045",
        last_verified=date(2026, 5, 18),
        paragraphs=[Paragraph(number=1, text="本文")],
        tags=["phase1-police", "刑事法", "正当防衛"],
    )
    yaml_text = dump_frontmatter(original)
    # YAML 部分だけ取り出して parse
    fm, _ = parse_frontmatter_text(yaml_text + "\nbody\n")
    restored = article_from_frontmatter(fm)
    assert restored.article_id == original.article_id
    assert restored.paragraphs == original.paragraphs
    assert restored.tags == original.tags

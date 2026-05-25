"""Tests for manifest/law_manifest.py.

Coverage targets:
  - LawManifest Pydantic field validation
  - assemble_law_manifest happy path (.md 2 件 + XML 有り)
  - assemble_law_manifest WARN (XML 不在) — source_xml_sha256 が空文字
  - 重複 article_id 検出 → ValueError
  - 重複 filename 検出 → ValueError
  - law_dir に .md が 0 件 → FileNotFoundError
  - write_law_manifest が atomic write して読み直せる
  - verify.py の REQUIRED_MANIFEST_FIELDS と互換 (round-trip)
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

# manifest パッケージを import 可能にする (parent dir = tools/parse/v0.2/)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from manifest.article_entry import ArticleEntry  # noqa: E402
from manifest.law_manifest import (  # noqa: E402
    LawManifest,
    assemble_law_manifest,
    write_law_manifest,
)

# ============================================================
# Helpers
# ============================================================


def _make_v02_md(law_abbrev: str, article_id: str, article_number: str, law_id: str) -> str:
    """テスト用 v0.2 .md 文字列."""
    return (
        "---\n"
        f"law_id: {law_id}\n"
        "law_name_ja: テスト法\n"
        f"article_id: {article_id}\n"
        f"article_number: '{article_number}'\n"
        "version_date: '2024-01-01'\n"
        "---\n\n"
        f"# テスト法 第{article_number}条\n\n"
        "## 原文 (日本語)\n\n"
        "### 第一条\n\n"
        f"本文 {article_number}.\n"
    )


def _create_law_dir(
    tmp_path: Path,
    law_abbrev: str,
    law_id: str,
    article_numbers: list[str],
) -> Path:
    """law_dir + .md ファイル群を生成して law_dir path を返す."""
    law_dir = tmp_path / law_abbrev
    law_dir.mkdir(parents=True)
    for num in article_numbers:
        article_id = f"{law_abbrev}-art-{num}"
        path = law_dir / f"{law_abbrev}-article-{num}.md"
        path.write_text(_make_v02_md(law_abbrev, article_id, num, law_id), encoding="utf-8")
    return law_dir


def _valid_manifest_kwargs() -> dict:
    """ValidationError 検査用の base kwargs."""
    return {
        "schema_version": "1.0",
        "law_id": "129AC0000000089",
        "law_name_ja": "民法",
        "law_abbrev": "minpou",
        "source_url": "https://laws.e-gov.go.jp/api/2/law_data/129AC0000000089",
        "source_xml_path": "cache/laws/129AC0000000089.xml",
        "source_xml_sha256": "b" * 64,
        "source_xml_bytes": 100,
        "source_fetched_at": date.today().isoformat(),
        "parser": "tools/parse/v0.2/segment_parser.py",
        "parser_version": "tools/parse/v0.2/segment_parser.py@0.1.0",
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
        "version_date": "1896-04-27",
        "article_count": 0,
        "articles": [],
    }


# ============================================================
# LawManifest model validation
# ============================================================


def test_model_accepts_valid_input() -> None:
    """全 field 妥当 → 構築成功."""
    m = LawManifest(**_valid_manifest_kwargs())
    assert m.law_id == "129AC0000000089"
    assert m.article_count == 0


def test_model_accepts_empty_xml_sha256() -> None:
    """source_xml_sha256 = 空文字列許容 (XML 不在ケース)."""
    kwargs = _valid_manifest_kwargs()
    kwargs["source_xml_sha256"] = ""
    kwargs["source_xml_bytes"] = 0
    m = LawManifest(**kwargs)
    assert m.source_xml_sha256 == ""


def test_model_is_frozen() -> None:
    """frozen=True → 構築後 mutate 不可."""
    m = LawManifest(**_valid_manifest_kwargs())
    with pytest.raises(ValidationError):
        m.law_id = "other"  # type: ignore[misc]


def test_model_rejects_extra_field() -> None:
    """extra='forbid' → 未知 field NG."""
    kwargs = _valid_manifest_kwargs()
    kwargs["unknown"] = "x"
    with pytest.raises(ValidationError):
        LawManifest(**kwargs)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("schema_version", "2.0"),  # 1.x 系のみ
        ("law_id", "lowercase"),  # 大文字数字_ のみ
        ("law_abbrev", "UPPERCASE"),  # 小文字英数 hyphen のみ
        ("law_abbrev", "with space"),
        ("source_xml_sha256", "g" * 64),  # hex 違反
        ("source_xml_sha256", "a" * 63),  # 短い
        ("source_xml_bytes", -1),  # 負数
        ("article_count", -1),
    ],
)
def test_model_rejects_invalid_field(field: str, bad_value: object) -> None:
    kwargs = _valid_manifest_kwargs()
    kwargs[field] = bad_value
    with pytest.raises(ValidationError):
        LawManifest(**kwargs)


# ============================================================
# assemble_law_manifest — happy path
# ============================================================


def test_assemble_2_articles_with_xml(tmp_path: Path) -> None:
    """.md 2 件 + XML 1 件 → article_count=2, source_xml_sha256 が埋まる."""
    law_dir = _create_law_dir(tmp_path, "minpou", "129AC0000000089", ["1", "2"])
    cache_dir = tmp_path / "cache" / "laws"
    cache_dir.mkdir(parents=True)
    xml_path = cache_dir / "129AC0000000089.xml"
    xml_path.write_bytes(b'<?xml version="1.0"?>\n<Law/>\n')

    manifest = assemble_law_manifest(
        law_dir=law_dir, xml_path=xml_path, parser_version="test@0.0.1"
    )
    assert manifest.article_count == 2
    assert len(manifest.articles) == 2
    assert {a.article_number for a in manifest.articles} == {"1", "2"}
    assert manifest.law_id == "129AC0000000089"
    assert manifest.law_name_ja == "テスト法"
    assert manifest.law_abbrev == "minpou"
    assert manifest.source_xml_sha256 != ""
    assert manifest.source_xml_bytes > 0


def test_assemble_warns_when_xml_missing(tmp_path: Path) -> None:
    """XML 不在 → WARN + source_xml_sha256 が空文字."""
    law_dir = _create_law_dir(tmp_path, "minpou", "129AC0000000089", ["1"])
    xml_path = tmp_path / "cache" / "laws" / "129AC0000000089.xml"  # not created

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        manifest = assemble_law_manifest(
            law_dir=law_dir, xml_path=xml_path, parser_version="test@0.0.1"
        )
        assert any("XML cache not found" in str(w.message) for w in caught)

    assert manifest.source_xml_sha256 == ""
    assert manifest.source_xml_bytes == 0
    assert manifest.article_count == 1


def test_assemble_sorts_articles_by_filename(tmp_path: Path) -> None:
    """articles の順序は filename の string sort (deterministic)."""
    # 注意: string sort なので '1', '10', '2' の順になる (自然ソートではない).
    # これは parse-egov.py の挙動とも一致.
    law_dir = _create_law_dir(tmp_path, "minpou", "129AC0000000089", ["2", "1", "10"])
    xml_path = tmp_path / "absent.xml"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        manifest = assemble_law_manifest(
            law_dir=law_dir, xml_path=xml_path, parser_version="t@0.0.1"
        )
    filenames = [a.filename for a in manifest.articles]
    assert filenames == sorted(filenames)


# ============================================================
# assemble_law_manifest — failure paths
# ============================================================


def test_assemble_raises_on_empty_law_dir(tmp_path: Path) -> None:
    """law_dir に .md が 0 件 → FileNotFoundError."""
    empty = tmp_path / "empty_law"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        assemble_law_manifest(law_dir=empty, xml_path=tmp_path / "x.xml", parser_version="t@0.0.1")


def test_assemble_raises_on_duplicate_article_id(tmp_path: Path) -> None:
    """同一 article_id の .md が 2 件 → ValueError."""
    law_dir = tmp_path / "duplaw"
    law_dir.mkdir()
    md1 = law_dir / "duplaw-article-1.md"
    md2 = law_dir / "duplaw-article-1-copy.md"
    md1.write_text(_make_v02_md("duplaw", "duplaw-art-1", "1", "TEST01"), encoding="utf-8")
    # 同じ article_id を持つが filename が違う 2 番目
    md2.write_text(_make_v02_md("duplaw", "duplaw-art-1", "1", "TEST01"), encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match="Duplicate article_id"):
            assemble_law_manifest(
                law_dir=law_dir,
                xml_path=tmp_path / "x.xml",
                parser_version="t@0.0.1",
            )


def test_assemble_raises_when_frontmatter_missing_law_id(tmp_path: Path) -> None:
    """frontmatter に law_id 無し → ValueError."""
    law_dir = tmp_path / "broken"
    law_dir.mkdir()
    md = law_dir / "broken-article-1.md"
    md.write_text(
        "---\nlaw_name_ja: x\narticle_id: broken-art-1\narticle_number: '1'\n"
        "version_date: '2024-01-01'\n---\n\n"
        "## 原文 (日本語)\n\n### 第一条\n\n本文.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required fields"):
        assemble_law_manifest(
            law_dir=law_dir, xml_path=tmp_path / "x.xml", parser_version="t@0.0.1"
        )


# ============================================================
# write_law_manifest — round-trip
# ============================================================


def test_write_and_reload_round_trip(tmp_path: Path) -> None:
    """書出した manifest を json.load → Pydantic で復元できる."""
    law_dir = _create_law_dir(tmp_path, "minpou", "129AC0000000089", ["1"])
    xml_path = tmp_path / "absent.xml"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        manifest = assemble_law_manifest(
            law_dir=law_dir, xml_path=xml_path, parser_version="t@0.0.1"
        )

    out_path = law_dir / "_source-manifest.json"
    write_law_manifest(manifest, out_path)

    assert out_path.exists()
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    # 必須 field の存在確認 (verify.py:48-56 と同じ set)
    for key in (
        "schema_version",
        "law_id",
        "law_name_ja",
        "law_abbrev",
        "source_xml_sha256",
        "article_count",
        "articles",
    ):
        assert key in raw, f"manifest missing verify.py required field: {key}"

    # Pydantic で復元できる = schema 完全互換
    restored = LawManifest.model_validate(raw)
    assert restored.law_id == manifest.law_id
    assert restored.article_count == manifest.article_count


def test_write_creates_valid_article_entries(tmp_path: Path) -> None:
    """articles list の各要素が verify.py REQUIRED_ARTICLE_MANIFEST_FIELDS を持つ."""
    law_dir = _create_law_dir(tmp_path, "minpou", "129AC0000000089", ["1", "2"])
    xml_path = tmp_path / "absent.xml"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        manifest = assemble_law_manifest(
            law_dir=law_dir, xml_path=xml_path, parser_version="t@0.0.1"
        )
    out_path = law_dir / "_source-manifest.json"
    write_law_manifest(manifest, out_path)

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    for art in raw["articles"]:
        for key in ("article_id", "article_number", "filename", "ja_text_sha256"):
            assert key in art, f"article entry missing verify.py required field: {key}"
        # Pydantic で復元可能 = ArticleEntry schema 互換
        ArticleEntry.model_validate(art)

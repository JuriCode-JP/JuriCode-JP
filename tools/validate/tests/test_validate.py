"""tools/validate/_validate.py のテスト."""

from __future__ import annotations

import sys
from pathlib import Path

# tools/validate/_validate を import するために tools/validate を sys.path に追加
_VALIDATE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VALIDATE_DIR))

from _validate import REPO_ROOT, find_data_files, validate_file  # noqa: E402

VALID_FRONTMATTER = """---
law_id: 140AC0000000045
law_name_ja: 刑法
law_name_en: Penal Code
article_number: "36"
article_id: keihou-art-36
version_date: 2007-06-12
source_url: https://laws.e-gov.go.jp/law/140AC0000000045
last_verified: 2026-05-18
license: MIT
translation_status: none
---

# 刑法 第36条

## 原文 (日本語)

### 第三十六条
急迫不正の侵害...
"""


def test_validate_existing_sample(tmp_path: Path) -> None:
    """正規サンプル(examples/keihou/keihou-article-36.md) を検証."""
    sample = REPO_ROOT / "examples" / "keihou" / "keihou-article-36.md"
    if not sample.exists():
        # 必ずあるはずだが念のため
        return
    result = validate_file(sample)
    assert result.ok, f"unexpected errors: {result.errors}"


def test_validate_missing_file(tmp_path: Path) -> None:
    result = validate_file(tmp_path / "does-not-exist.md")
    assert not result.ok
    assert any("not found" in e for e in result.errors)


def test_validate_wrong_extension(tmp_path: Path) -> None:
    f = tmp_path / "keihou-article-36.txt"
    f.write_text(VALID_FRONTMATTER, encoding="utf-8")
    result = validate_file(f)
    assert not result.ok
    assert any(".md" in e for e in result.errors)


def test_validate_valid_minimal(tmp_path: Path) -> None:
    """frontmatter のみで body を最低限を満たすファイルが PASS."""
    f = tmp_path / "keihou-article-36.md"
    f.write_text(VALID_FRONTMATTER, encoding="utf-8")
    result = validate_file(f)
    assert result.ok, f"unexpected errors: {result.errors}"


def test_validate_filename_mismatch(tmp_path: Path) -> None:
    """article_id とファイル名が整合しない場合は FAIL."""
    f = tmp_path / "keihou-article-99.md"  # ファイル名は 99 だが article_number=36
    f.write_text(VALID_FRONTMATTER, encoding="utf-8")
    result = validate_file(f)
    assert not result.ok
    assert any("Filename mismatch" in e for e in result.errors)


def test_validate_missing_required_section(tmp_path: Path) -> None:
    """## 原文 セクションがないと FAIL."""
    f = tmp_path / "keihou-article-36.md"
    bad = VALID_FRONTMATTER.replace("## 原文 (日本語)", "## 別のセクション")
    f.write_text(bad, encoding="utf-8")
    result = validate_file(f)
    assert not result.ok
    assert any("## 原文" in e for e in result.errors)


def test_validate_ir_error_caught(tmp_path: Path) -> None:
    """IR で article_id と article_number の不整合を検出."""
    f = tmp_path / "keihou-article-36.md"
    bad = VALID_FRONTMATTER.replace("article_id: keihou-art-36", "article_id: keihou-art-99")
    f.write_text(bad, encoding="utf-8")
    result = validate_file(f)
    assert not result.ok
    assert any("IR validation error" in e for e in result.errors)


def test_find_data_files() -> None:
    """examples/ または data/ 配下のファイルを列挙."""
    files = find_data_files(REPO_ROOT)
    # 少なくとも examples/keihou/keihou-article-36.md は存在するはず
    assert len(files) >= 1
    assert any("keihou-article-36.md" in str(f) for f in files)

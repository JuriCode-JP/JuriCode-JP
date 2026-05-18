"""法令データファイルの検証ロジック.

このモジュールは `validate-file.py` および `validate-all.py` から再利用される
共通の検証関数を提供する.

主な検証項目:
1. ファイル拡張子(.md)
2. YAML frontmatter のパース可能性
3. Pydantic IR (JuriCodeArticle) によるスキーマ検証
4. ファイル名と article_id の整合
5. 本文必須セクション(## 原文)の存在
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

# tools/shared/src を sys.path に追加して juricode_shared を import 可能にする
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared.frontmatter import (  # noqa: E402
    article_from_frontmatter,
    parse_frontmatter,
)


class ValidationResult(NamedTuple):
    """単一ファイルの検証結果."""

    ok: bool
    errors: list[str]
    warnings: list[str]


def validate_file(path: Path) -> ValidationResult:
    """単一の法令データファイル(.md)を検証する.

    Args:
        path: 検証対象のファイルパス

    Returns:
        ValidationResult: ok=True なら全検証 PASS、errors にエラーメッセージのリスト
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. 存在確認
    if not path.exists():
        return ValidationResult(False, [f"File not found: {path}"], [])

    # 2. 拡張子確認
    if path.suffix != ".md":
        errors.append(f"Expected .md extension, got '{path.suffix}'")

    # 3. frontmatter パース
    try:
        fm_dict, body = parse_frontmatter(path)
    except Exception as e:
        return ValidationResult(
            False,
            [f"frontmatter parse error: {type(e).__name__}: {e}"],
            warnings,
        )

    if not body.strip():
        errors.append("Body is empty")

    # 4. IR (Pydantic) によるスキーマ検証
    try:
        article = article_from_frontmatter(fm_dict)
    except Exception as e:
        # IR エラーは詳細を出す(Pydantic ValidationError はそのまま長文を残す)
        errors.append(f"IR validation error: {type(e).__name__}: {e}")
        return ValidationResult(False, errors, warnings)

    # 5. ファイル名と article_id の整合
    #    article_id = "keihou-art-36" の場合、ファイル名は "keihou-article-36.md"
    expected_law_abbrev = article.article_id.rsplit("-art-", 1)[0]
    expected_filename = f"{expected_law_abbrev}-article-{article.article_number}.md"
    if path.name != expected_filename:
        errors.append(
            f"Filename mismatch: expected '{expected_filename}', "
            f"got '{path.name}' (based on article_id='{article.article_id}', "
            f"article_number='{article.article_number}')"
        )

    # 6. 本文必須セクション
    if "## 原文" not in body:
        errors.append("Missing required section: '## 原文'")

    # 7. 警告レベル(致命的でないが推奨、ir-spec.md §5.2 / §5.3)
    if article.translation_status.value != "none" and "## English Translation" not in body:
        warnings.append(
            f"translation_status='{article.translation_status.value}' "
            f"but body has no '## English Translation' section"
        )
    if article.cases and "## 判例リンク" not in body:
        warnings.append(
            f"cases declared in frontmatter ({len(article.cases)} entries) "
            f"but body has no '## 判例リンク' section"
        )
    # ir-spec.md §5.2: machine_translated == True なら translation_status='draft' 推奨
    if article.machine_translated and article.translation_status.value != "draft":
        warnings.append(
            f"machine_translated=True but translation_status="
            f"'{article.translation_status.value}'. "
            f"Spec recommends 'draft' status for machine-translated content."
        )

    return ValidationResult(len(errors) == 0, errors, warnings)


def find_data_files(repo_root: Path) -> list[Path]:
    """data/ および examples/ 配下の条文ファイルを列挙する.

    パターン: `*-article-*.md`
    """
    targets: list[Path] = []
    for sub in ["data", "examples"]:
        d = repo_root / sub
        if d.exists():
            targets.extend(sorted(d.rglob("*-article-*.md")))
    return targets


def format_result(path: Path, result: ValidationResult, repo_root: Path | None = None) -> str:
    """単一の検証結果を整形文字列にする."""
    try:
        display = path.relative_to(repo_root) if repo_root else path
    except (ValueError, TypeError):
        display = path

    if result.ok and not result.warnings:
        return f"OK  {display}"
    if result.ok and result.warnings:
        out = [f"OK  {display}  (with {len(result.warnings)} warning(s))"]
        for w in result.warnings:
            out.append(f"    ! {w}")
        return "\n".join(out)
    out = [f"NG  {display}"]
    for e in result.errors:
        out.append(f"    - {e}")
    for w in result.warnings:
        out.append(f"    ! {w}")
    return "\n".join(out)


# 外部 import 用の便宜関数
REPO_ROOT = _REPO_ROOT

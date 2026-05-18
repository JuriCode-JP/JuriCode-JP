"""ファイル配置ルール: data/ 配下の条文 Markdown の正規パス."""

from __future__ import annotations

from pathlib import Path

# Phase 1 警察関連法令のデフォルト phase ディレクトリ
DEFAULT_PHASE_DIR = "phase1-police"

# 過去版アーカイブのサブディレクトリ名 (Phase 1 では未使用、将来仕様)
ARCHIVE_SUBDIR = "archive"


def article_path(
    law_abbrev: str,
    article_number: str,
    *,
    root: Path | str = "data",
    phase_dir: str = DEFAULT_PHASE_DIR,
) -> Path:
    """条文 Markdown の正規パスを返す.

    Examples:
        >>> article_path("keihou", "36")
        PosixPath('data/phase1-police/keihou/keihou-article-36.md')
        >>> article_path("keihou", "36-2", root="/repo/data")
        PosixPath('/repo/data/phase1-police/keihou/keihou-article-36-2.md')
    """
    return Path(root) / phase_dir / law_abbrev / f"{law_abbrev}-article-{article_number}.md"

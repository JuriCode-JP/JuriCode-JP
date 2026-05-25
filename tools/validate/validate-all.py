#!/usr/bin/env python3
"""validate-all.py — data/ および examples/ 配下の全条文ファイルを検証する.

Usage:
    python tools/validate/validate-all.py                   # repo root を自動検出
    python tools/validate/validate-all.py --path data/      # 任意ディレクトリ
    python tools/validate/validate-all.py --path /tmp/empty # 0 files でエラー

Exit codes:
    0: 全ファイルが検証 PASS
    1: 1 つ以上のファイルが検証 FAIL, または --path 配下に対象ファイル 0 件

FU-403: 旧版は REPO_ROOT 固定で argparse なし. bulk-ingest.py が `--data-root`
を渡しても silently 無視され、非標準 data-root の検証が「実は何も検証していない」
状態だった (偽の green CI 源). 命名は tools/parse/verify.py と揃え (--path, --verbose).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 同一ディレクトリの _validate を import するため
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _validate import (
    REPO_ROOT,
    find_data_files,
    format_result,
    validate_file,
)


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "JuriCode-JP data validator (Layer 4 — frontmatter / IR / filename / "
            "Markdown sections)."
        )
    )
    ap.add_argument(
        "--path",
        type=Path,
        default=None,
        help=(
            "検索対象ディレクトリ (data/ または examples/ を直下に持つ root). "
            "未指定時は repo root を自動検出."
        ),
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="OK ファイルも全件表示する (default: NG / warning 付き OK のみ表示).",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    root = args.path if args.path is not None else REPO_ROOT
    root = root.resolve()

    if not root.exists():
        print(f"ERROR: --path does not exist: {root}", file=sys.stderr)
        return 1

    targets = find_data_files(root)

    if not targets:
        # FU-403: 旧版は exit 0 で silent ignore (偽の green CI). 0 件は error 扱い.
        print(
            f"ERROR: No '*-article-*.md' files found under {root}/(data|examples)/",
            file=sys.stderr,
        )
        return 1

    print(f"Validating {len(targets)} file(s) under {root}...\n")
    fail_count = 0
    warn_count = 0
    for path in targets:
        result = validate_file(path)
        if result.ok and not result.warnings and not args.verbose:
            # 静かに通す (大量 OK の出力で本物の NG が埋もれるのを防ぐ)
            continue
        print(format_result(path, result, repo_root=root))
        if not result.ok:
            fail_count += 1
        if result.warnings:
            warn_count += 1

    print()
    print(f"Summary: {len(targets)} file(s), {fail_count} failed, {warn_count} with warnings")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

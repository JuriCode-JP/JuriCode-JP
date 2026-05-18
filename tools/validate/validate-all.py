#!/usr/bin/env python3
"""validate-all.py — data/ および examples/ 配下の全条文ファイルを検証する.

Usage:
    python tools/validate/validate-all.py

Exit codes:
    0: 全ファイルが検証 PASS
    1: 1 つ以上のファイルが検証 FAIL
"""

from __future__ import annotations

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


def main() -> int:
    targets = find_data_files(REPO_ROOT)

    if not targets:
        print("No '*-article-*.md' files found under data/ or examples/")
        return 0

    print(f"Validating {len(targets)} file(s)...\n")
    fail_count = 0
    warn_count = 0
    for path in targets:
        result = validate_file(path)
        print(format_result(path, result, repo_root=REPO_ROOT))
        if not result.ok:
            fail_count += 1
        if result.warnings:
            warn_count += 1

    print()
    print(f"Summary: {len(targets)} file(s), {fail_count} failed, {warn_count} with warnings")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

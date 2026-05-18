#!/usr/bin/env python3
"""validate-file.py — 単一の法令データファイルを検証する.

Usage:
    python tools/validate/validate-file.py <path-to-md> [<path-to-md> ...]

Exit codes:
    0: 全ファイルが検証 PASS
    1: 1 つ以上のファイルが検証 FAIL
    2: 引数エラー
"""

from __future__ import annotations

import sys
from pathlib import Path

# 同一ディレクトリの _validate を import するため
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _validate import REPO_ROOT, format_result, validate_file


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: python validate-file.py <path-to-md> [<path-to-md> ...]",
            file=sys.stderr,
        )
        return 2

    fail_count = 0
    for arg in argv[1:]:
        path = Path(arg).resolve()
        result = validate_file(path)
        print(format_result(path, result, repo_root=REPO_ROOT))
        if not result.ok:
            fail_count += 1

    if fail_count > 0:
        print(
            f"\n{fail_count} file(s) failed validation.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

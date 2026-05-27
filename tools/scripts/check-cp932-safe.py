#!/usr/bin/env python3
"""check-cp932-safe.py -- project-wide cp932 safety scanner.

Why (FU-505 Layer 1):
Windows cp932 console での argparse `--help` 出力が UnicodeEncodeError で
crash する事故 (FU-502/503/505) を構造的に予防する.

scan 対象: tools/ 配下の *.py
除外: tests / __pycache__ / .venv / venv / .tox / build / dist
  (生成物・仮想環境を弾いて、誤検知ゼロを保つ)
exit 0: 全 file cp932-safe
exit 1: 1 件以上 unsafe 文字あり (stderr に詳細出力)
"""

import argparse
import sys
from pathlib import Path

# 仮想環境 / キャッシュ / ビルド生成物を除外
EXCLUDE_PARTS = frozenset({
    "tests",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "build",
    "dist",
})


def is_cp932_safe(c: str) -> bool:
    """Return True if c can be encoded as cp932."""
    try:
        c.encode("cp932")
        return True
    except UnicodeEncodeError:
        return False


def scan_file(path: Path) -> list[tuple[int, str, list[str]]]:
    """Return list of (lineno, line, [unsafe_chars]) for unsafe lines."""
    src = path.read_text(encoding="utf-8")
    unsafe_lines = []
    for i, line in enumerate(src.splitlines(), 1):
        bad = sorted(set(c for c in line if ord(c) >= 128 and not is_cp932_safe(c)))
        if bad:
            unsafe_lines.append((i, line, bad))
    return unsafe_lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan tools/ for cp932-unsafe characters (FU-505)."
    )
    parser.add_argument("--path", type=Path, default=Path("tools"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    total = 0
    bad_files = 0
    for p in sorted(args.path.rglob("*.py")):
        if any(part in EXCLUDE_PARTS for part in p.parts):
            continue
        total += 1
        unsafe = scan_file(p)
        if unsafe:
            bad_files += 1
            print(f"FAIL: {p}", file=sys.stderr)
            for lineno, line, chars in unsafe:
                char_repr = " ".join(f"U+{ord(c):04X}({c!r})" for c in chars)
                print(f"  L{lineno}: {char_repr}", file=sys.stderr)
                if args.verbose:
                    print(f"        {line.strip()[:100]}", file=sys.stderr)

    if bad_files:
        print(f"\n=== cp932-unsafe: {bad_files}/{total} files ===", file=sys.stderr)
        return 1

    print(f"=== cp932-safe: {total} files scanned ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""check-md-residue.py -- G0-e を CI で常設するための単体チェック.

正本 md の **ファイル全体** に残骸が無いことを検査する:
  1. 内部マーカー (`<!-- ... -->`) が 0 件。
  2. frontmatter と `## 原文 (日本語)` の間に、H1 見出し以外の非空行が 0 件
     (この領域は H1 のみ = format-spec §5.1)。

Why 単体スクリプトにするか:
    G0 ゲート本体 (g0_fidelity_gate.py) は ground truth として e-Gov XML
    (`cache/laws/`, 133 MB, gitignored) を要求するため CI で走らない。
    しかし **G0-e は XML を必要としない** (md ファイル単体で判定できる)。
    CI で走る形に切り出しておかないと、「CI で見ていない検査」になってしまう。

Why この検査が必要か (今日 3 回目の同型の失敗):
    G0-a〜d は `## 原文` セクションの **中身しか見ていない**。検査範囲の外にある
    ものは、ゲートが緑でも永久に残り続ける。実際、G0-a/b/c/d を全部緑にして
    「マーカー 0」と報告した後、**セクション外に内部マーカー 1 件と本文の残骸
    17 件が残っていた** (2026-07-14, MCP セッションで発覚)。

    同型の失敗:
      1. verify.py は md <-> manifest の自己整合しか見ない -> 原典との欠落が見えない
      2. eval の gold に枝番・号が無い                     -> corpus の穴が見えない
      3. G0-a〜d は本文セクションしか見ない                -> セクション外の残骸が見えない
    共通の型: **検査範囲の外にあるものは、永久に見えない**。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER_RE = re.compile(r"<!--[^>]*-->")
FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
JA_HEADING_RE = re.compile(r"^##\s*原文", re.MULTILINE)


def check_file(md_text: str) -> tuple[int, list[str]]:
    """(内部マーカー数, `## 原文` より前にある H1 以外の非空行) を返す."""
    body = FRONTMATTER_RE.sub("", md_text, count=1)
    markers = MARKER_RE.findall(body)

    junk: list[str] = []
    m = JA_HEADING_RE.search(body)
    if m:
        junk = [
            ln.strip()
            for ln in body[: m.start()].splitlines()
            if ln.strip() and not ln.startswith("# ")
        ]
    return len(markers), junk


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--path", type=Path, default=Path("data/v0.2"))
    args = ap.parse_args()

    scanned = marker_articles = marker_total = junk_articles = 0
    for p in sorted(args.path.rglob("*-article-*.md")):
        scanned += 1
        n_markers, junk = check_file(p.read_text(encoding="utf-8"))
        if n_markers:
            marker_articles += 1
            marker_total += n_markers
            print(f"FAIL {p}: internal marker x{n_markers}", file=sys.stderr)
        if junk:
            junk_articles += 1
            print(f"FAIL {p}: text outside the body section: {junk[0][:60]!r}", file=sys.stderr)

    failed = marker_articles + junk_articles
    print(f"=== md residue (G0-e): {scanned} files scanned ===", file=sys.stderr)
    print(f"  internal markers        : {marker_articles} files ({marker_total} occurrences)")
    print(f"  text outside the body   : {junk_articles} files")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

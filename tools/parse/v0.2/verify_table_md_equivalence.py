#!/usr/bin/env python3
"""verify_table_md_equivalence.py -- canonical md の表 <-> e-Gov XML グリッドの構造等価ガード.

Why (FU-515 §4 構造等価・local 専用):
    emit_table_md.py が canonical md に反映した表が、e-Gov XML の本則 TableStruct を
    共通コア (table_core) で展開したグリッドと **構造等価** であることを実証する。
    chunks は同じ XML グリッドから生成されるため、md <-> XML グリッドの一致は
    md <-> chunks の構造等価を推移的に保証する (§3-2)。

    cache/laws (gitignored) を要するため CI ステップではなく push 前ローカル検証
    (run-ci.py の optional step)。CI 内の等価性は committed fixture を使う
    tests/test_emit_table_md.py が担保する。

等価の定義 (§3.5.7):
    md の `## 原文 (日本語)` 内に出現する全パイプ行 (GFM 区切り行 `| --- |` を除外) を
    文書順に並べたものが、当該条文の本則 TableStruct を grid_to_pipe_rows で直列化した
    行列を文書順に連結したものと **完全一致** する。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from emit_table_md import JA_SECTION_RE, collect_main_tables, find_md_dir  # noqa: E402
from extract_table_from_xml import build_law_abbrev_to_id_phase  # noqa: E402
from table_core import grid_to_pipe_rows, is_gfm_separator_line  # noqa: E402

_PIPE_LINE = re.compile(r"^\s*\|.*\|\s*$")


def md_table_rows(md_text: str) -> list[str]:
    """md の `## 原文 (日本語)` から表のパイプ行 (区切り行除外) を文書順に抽出."""
    m = JA_SECTION_RE.search(md_text)
    if not m:
        return []
    rows: list[str] = []
    for line in m.group(1).splitlines():
        if _PIPE_LINE.match(line) and not is_gfm_separator_line(line):
            rows.append(line.strip())
    return rows


def expected_rows_for_article(by_para: dict[int, list[list[list[str]]]]) -> list[str]:
    """XML グリッド由来の期待パイプ行 (paragraph 昇順 -> 文書順の表ごと)."""
    out: list[str] = []
    for _para, grids in sorted(by_para.items()):
        for grid in grids:
            out.extend(grid_to_pipe_rows(grid))
    return out


def check_law(law_abbrev: str, law_id: str, md_dir: Path, xml_dir: Path) -> list[str]:
    """構造等価違反を文字列リストで返す (空なら OK)."""
    failures: list[str] = []
    xml_path = xml_dir / f"{law_id}.xml"
    if not xml_path.exists():
        return [f"{law_abbrev}: XML 不在 {xml_path}"]

    root = ET.parse(xml_path).getroot()
    parent_map: dict[Any, Any] = {child: parent for parent in root.iter() for child in parent}
    tables = collect_main_tables(root, parent_map)

    for art_num, by_para in sorted(tables.items()):
        md_path = md_dir / f"{law_abbrev}-article-{art_num}.md"
        if not md_path.exists():
            continue
        actual = md_table_rows(md_path.read_text(encoding="utf-8"))
        expected = expected_rows_for_article(by_para)
        if not actual:
            # md にまだ表が反映されていない条文は等価検証の対象外 (未展開 = アトミック性)
            continue
        if actual != expected:
            failures.append(
                f"{law_abbrev} art {art_num}: md 表行 {len(actual)} != XML グリッド行 "
                f"{len(expected)} (構造不一致)"
            )
            for i, (a, e) in enumerate(zip(actual, expected, strict=False)):
                if a != e:
                    failures.append(f"    row {i}: md={a!r}\n             xml={e!r}")
                    break
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data/v0.2"))
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--law-only", default=None)
    args = ap.parse_args()

    if not args.xml_dir.exists():
        print(f"SKIP: xml-dir 不在 ({args.xml_dir})。構造等価は cache/laws 必須 (ローカル限定)。")
        return 0

    law_map = build_law_abbrev_to_id_phase(args.data_dir)
    if args.law_only:
        law_map = {args.law_only: law_map[args.law_only]}

    all_failures: list[str] = []
    for law_abbrev, (law_id, _phase) in sorted(law_map.items()):
        md_dir = find_md_dir(args.data_dir, law_abbrev)
        if md_dir is None:
            continue
        all_failures.extend(check_law(law_abbrev, law_id, md_dir, args.xml_dir))

    if all_failures:
        print(f"EQUIVALENCE FAIL ({len(all_failures)} 件):", file=sys.stderr)
        for f in all_failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("EQUIVALENCE OK: 反映済み md 表は XML グリッドと構造等価", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

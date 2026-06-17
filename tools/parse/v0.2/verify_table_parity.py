#!/usr/bin/env python3
"""verify_table_parity.py -- 本則 table chunks の parity guard (ローカル専用・cache/laws 必須).

Why:
    extract_table が本則 <TableStruct> を silent に落としていないかを cache/laws の
    e-Gov XML と build/chunks の双方向で突合する再発防止ガード。cache/laws は
    .gitignore 対象で CI に不在のため、本 script は CI ステップではなく push 前
    ローカル CI 再現 (run-ci.py の optional step) として実行する。

parity 定義 (windowing 耐性・briefing §5):
    1 つの <TableStruct> は行ウィンドウ分割で複数 chunk record になりうる
    (実証: 154条 89 行表 1 つ -> 5 records)。よって record 数と TableStruct 数の
    単純一致は使えない。代わりに:
      (a) article-level coverage: XML で本則 TableStruct を持つ (law_id, article) の
          集合 == *-article-*.table.chunks.jsonl が表す (law_id, article) 集合 (1:1)。
      (b) no-drop: 各 article について XML の本則 TableStruct 数 <= chunk record 数
          (窓分割で record は増えるが減らない = TableStruct が silent に消えていない)。
"""

from __future__ import annotations

import argparse
import json
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
_SHARED_SRC = _HERE.parent.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from extract_table_from_xml import build_law_abbrev_to_id_phase  # noqa: E402


def count_main_tablestruct_per_article(root: Any) -> dict[str, int]:
    """本則 (SupplProvision 配下を除く) の TableStruct 数を article ごとに数える.

    Why: extract_main_table_chunks と同じ ancestry 判定 (SP skip + Article 再解決)
    を使うが、窓分割前の生 TableStruct 数を数える点が異なる (no-drop の分母)。
    """
    parent_map: dict[Any, Any] = {child: parent for parent in root.iter() for child in parent}
    counts: dict[str, int] = {}
    for ts in root.iter("TableStruct"):
        current = ts
        in_sp = False
        while True:
            current = parent_map.get(current)
            if current is None:
                break
            if current.tag == "SupplProvision":
                in_sp = True
                break
        if in_sp:
            continue

        current = ts
        art_elem = None
        while True:
            current = parent_map.get(current)
            if current is None:
                break
            if current.tag == "Article":
                art_elem = current
                break
        if art_elem is None:
            continue
        art_num = art_elem.get("Num", "")
        if not art_num:
            continue
        counts[art_num] = counts.get(art_num, 0) + 1
    return counts


def read_chunk_records_per_article(law_dir: Path) -> dict[str, int]:
    """build/chunks/{abbrev}/ の本則 table chunk ファイルから article -> record 数."""
    out: dict[str, int] = {}
    if not law_dir.is_dir():
        return out
    for f in sorted(law_dir.glob("*-article-*.table.chunks.jsonl")):
        recs = [
            json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        if not recs:
            continue
        art_num = recs[0].get("article_number", "")
        out[art_num] = out.get(art_num, 0) + len(recs)
    return out


def check_parity(data_dir: Path, xml_dir: Path, chunks_dir: Path) -> list[str]:
    """parity 違反を文字列リストで返す (空なら OK)."""
    law_map = build_law_abbrev_to_id_phase(data_dir)
    failures: list[str] = []
    for abbrev, (law_id, _phase) in sorted(law_map.items()):
        xml_path = xml_dir / f"{law_id}.xml"
        if not xml_path.exists():
            continue
        root = ET.parse(xml_path).getroot()
        xml_counts = count_main_tablestruct_per_article(root)
        chunk_counts = read_chunk_records_per_article(chunks_dir / abbrev)
        xml_arts = set(xml_counts)
        chunk_arts = set(chunk_counts)

        for art in sorted(xml_arts - chunk_arts):
            failures.append(
                f"{abbrev} art {art}: XML に本則 TableStruct があるが chunk ファイルが無い (DROP)"
            )
        for art in sorted(chunk_arts - xml_arts):
            failures.append(
                f"{abbrev} art {art}: chunk ファイルがあるが XML に本則 TableStruct が無い"
            )
        for art in sorted(xml_arts & chunk_arts):
            if xml_counts[art] > chunk_counts[art]:
                failures.append(
                    f"{abbrev} art {art}: TableStruct {xml_counts[art]} 個 > "
                    f"record {chunk_counts[art]} 個 (DROP)"
                )
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data/v0.2"))
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    args = ap.parse_args()

    if not args.xml_dir.exists():
        print(
            f"SKIP: xml-dir が見つかりません ({args.xml_dir})。parity は cache/laws "
            "(gitignored) を要するためローカル限定です。",
            file=sys.stderr,
        )
        return 0

    failures = check_parity(args.data_dir, args.xml_dir, args.chunks_dir)
    if failures:
        print(f"PARITY FAIL ({len(failures)} 件):", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1
    print(
        "PARITY OK: 本則 table chunks は XML と article-level coverage + no-drop 一致",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

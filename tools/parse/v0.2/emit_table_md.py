#!/usr/bin/env python3
"""emit_table_md.py -- 本則 TableStruct を canonical v0.2 .md に GFM 表として反映 (FU-515 E-3).

責務 (バイブコーディング 3 原則 #1):
  「e-Gov XML の本則表」を「対応する v0.2 条文 .md の当該項に GFM パイプ表として挿入」
  する純粋なテキスト変換 + その CLI。表構造の直列化は table_core.py に委譲 (DRY)。
  chunk 生成 (extract_table_from_xml.py) / hash 計算 (canonical_hash.py) は範囲外。

Why 専用モジュールにしたか (briefing は extract_table_from_xml への mode 追加を示唆):
  md ファイルの読み書き・項スライスへの挿入は、chunk 生成 (XML->jsonl) とは別の責務。
  SOLID (1 ファイル 1 責務) に従い独立モジュールにし、共通コア table_core.py を両者が
  import する形にした。briefing の意図「E-1 lib を使う md 反映ツール」は満たす。

設計 (format-spec §3.5):
  - 配置: `## 原文 (日本語)` 内、当該項 (`### 第N項`) のテキスト末尾 (導入文直後) に挿入。
  - 形式: 第1グリッド行 -> `| --- | … |` 区切り行 -> 残り全行。前後に空行。
  - セル: table_core.normalize_cell_text (空白畳み + | エスケープ)。Option A (空セル維持)。
  - 後方互換: 表を持たない条文の .md は触らない (hash 不変)。
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

    print(
        "RuntimeWarning: defusedxml 不在、stdlib ElementTree に fallback (XXE/billion-laughs 防御弱)",
        file=sys.stderr,
    )

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED_SRC = _HERE.parent.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from extract_table_from_xml import build_law_abbrev_to_id_phase  # noqa: E402
from juricode_shared import safe_write_text  # noqa: E402
from table_core import table_to_grid_safe  # noqa: E402

# verify.py:34-46 / canonical_hash.py と文字列一致させた項見出し正規表現。
JA_SECTION_RE = re.compile(
    r"##\s*原文\s*\(?日本語\)?\s*\n(.*?)(?=\n##\s|\Z)",
    re.DOTALL,
)
PARAGRAPH_HEADING_RE = re.compile(
    r"^###\s+第[一二三四五六七八九十百千0-9]+条"
    r"(?:の[一二三四五六七八九十百千0-9]+)*"
    r"(?:第([一二三四五六七八九十百千0-9]+)項)?\s*$",
    re.MULTILINE,
)


def resolve_article_and_paragraph(ts: Any, parent_map: dict[Any, Any]) -> tuple[str, int]:
    """TableStruct から (article_num, paragraph_num) を祖先解決する.

    Why paragraph も解決するか: 表は当該項の導入文直後に置くため、どの項
    (### 第N項) に挿入するかを知る必要がある。号 (Item) 内の表は最近接の
    Paragraph を項とみなす。Paragraph が無い (Article 直下) 表は項 1 とする。
    """
    art_num = ""
    para_num = 0
    current = ts
    while True:
        current = parent_map.get(current)
        if current is None:
            break
        if current.tag == "Paragraph" and para_num == 0:
            raw = current.get("Num", "1")
            try:
                para_num = int(raw)
            except (ValueError, TypeError):
                para_num = 1
        if current.tag == "Article" and not art_num:
            # XML の Num は枝番条を underscore で表す (例 15_5) が、md ファイル名・
            # frontmatter article_number は hyphen 形式 (15-5)。ここで正規化する
            # (CLAUDE.md §3.1 / article_number pattern ^[0-9]+(-[0-9]+)*$)。
            art_num = current.get("Num", "").replace("_", "-")
        if current.tag == "SupplProvision":
            # 附則配下はスコープ外: art_num を空にして呼び出し側が捨てる
            return "", 0
    return art_num, (para_num or 1)


def collect_main_tables(
    root: Any, parent_map: dict[Any, Any]
) -> dict[str, dict[int, list[list[list[str]]]]]:
    """本則 TableStruct を article_num -> paragraph_num -> [grid, ...] に収集 (文書順)."""
    out: dict[str, dict[int, list[list[list[str]]]]] = {}
    for ts in root.iter("TableStruct"):
        art_num, para_num = resolve_article_and_paragraph(ts, parent_map)
        if not art_num:
            continue  # 附則 or Article 不明 -> スコープ外
        grid = table_to_grid_safe(ts)
        if not grid:
            continue
        out.setdefault(art_num, {}).setdefault(para_num, []).append(grid)
    return out


def build_gfm_block(grid: list[list[str]]) -> list[str]:
    """グリッドを GFM 表の行リストにする: 第1行 -> | --- | 区切り -> 残り全行.

    Why 区切り行を機械挿入するか (§3.5.2): 法令表に意味的ヘッダは無いが、GFM は
    第1行を header とみなし区切り行が無いと表として描画しない。区切り行は描画用で
    あり round-trip/構造等価では正規化除外される。
    """
    if not grid:
        return []
    ncols = max(len(r) for r in grid)
    norm = [r + [""] * (ncols - len(r)) for r in grid]  # 矩形化 (念のため)
    lines = ["| " + " | ".join(row) + " |" for row in norm]
    separator = "| " + " | ".join(["---"] * ncols) + " |"
    return [lines[0], separator, *lines[1:]]


def insert_tables_into_md(
    md_text: str,
    tables_by_para: dict[int, list[list[list[str]]]],
    warnings: list[str],
) -> str:
    """v0.2 .md の `## 原文 (日本語)` 内、各項テキスト末尾に表ブロックを挿入.

    後方互換: tables_by_para が空なら md_text をそのまま返す (no-op)。
    """
    if not tables_by_para:
        return md_text

    m = JA_SECTION_RE.search(md_text)
    if not m:
        warnings.append("emit_table_md: `## 原文 (日本語)` セクションが無い; 挿入スキップ")
        return md_text

    ja_body = m.group(1)
    ja_start, ja_end = m.start(1), m.end(1)

    headings = list(PARAGRAPH_HEADING_RE.finditer(ja_body))
    if not headings:
        warnings.append("emit_table_md: 項見出しが無い; 挿入スキップ (安全な挿入先なし)")
        return md_text

    intro = ja_body[: headings[0].start()]
    heading_texts: list[str] = []
    para_bodies: list[str] = []
    for i, h in enumerate(headings):
        heading_texts.append(ja_body[h.start() : h.end()])
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(ja_body)
        para_bodies.append(ja_body[start:end])

    for para_num, grids in sorted(tables_by_para.items()):
        pidx = para_num - 1
        if pidx < 0 or pidx >= len(para_bodies):
            warnings.append(
                f"emit_table_md: paragraph_number={para_num} が見出し数 "
                f"{len(para_bodies)} の範囲外; 表 {len(grids)} 個スキップ"
            )
            continue
        slice_text = para_bodies[pidx]
        # 冪等性: 当該項に既にパイプ表があれば二重挿入しない (再実行・逐次展開で安全)。
        if any(ln.lstrip().startswith("|") for ln in slice_text.splitlines()):
            warnings.append(
                f"emit_table_md: paragraph_number={para_num} に既存表あり; "
                "二重挿入回避でスキップ (冪等)"
            )
            continue

        block_lines: list[str] = []
        for grid in grids:
            if block_lines:
                block_lines.append("")  # 複数表は空行で区切る
            block_lines.extend(build_gfm_block(grid))
        if not block_lines:
            continue

        content = slice_text.rstrip("\n")
        trailing = slice_text[len(content) :]  # 末尾の改行群を保存 (次見出しとの区切り)
        if not trailing:
            trailing = "\n"  # 最終項で末尾改行が無い場合の保険
        table_md = "\n\n" + "\n".join(block_lines)
        para_bodies[pidx] = content + table_md + trailing

    rebuilt = intro + "".join(h + b for h, b in zip(heading_texts, para_bodies, strict=True))
    return md_text[:ja_start] + rebuilt + md_text[ja_end:]


def process_law(
    law_abbrev: str,
    law_id: str,
    md_dir: Path,
    xml_dir: Path,
    dry_run: bool,
    articles: set[str] | None = None,
) -> tuple[int, list[str]]:
    """1 法令の本則表を条文 md に反映. (反映条文数, 警告) を返す.

    articles: 指定時はその article_number のみ処理 (アトミックなパイロット/逐次展開用)。
    """
    warnings: list[str] = []
    xml_path = xml_dir / f"{law_id}.xml"
    if not xml_path.exists():
        warnings.append(f"{law_abbrev}: XML 不在 {xml_path}")
        return 0, warnings

    root = ET.parse(xml_path).getroot()
    parent_map: dict[Any, Any] = {child: parent for parent in root.iter() for child in parent}
    tables = collect_main_tables(root, parent_map)
    if not tables:
        return 0, warnings

    updated = 0
    for art_num, by_para in sorted(tables.items()):
        if articles is not None and art_num not in articles:
            continue
        md_path = md_dir / f"{law_abbrev}-article-{art_num}.md"
        if not md_path.exists():
            warnings.append(f"{law_abbrev} art {art_num}: md 不在 {md_path}")
            continue
        original = md_path.read_text(encoding="utf-8")
        new_text = insert_tables_into_md(original, by_para, warnings)
        if new_text == original:
            continue
        updated += 1
        if not dry_run:
            safe_write_text(md_path, new_text)
    return updated, warnings


def find_md_dir(data_dir: Path, law_abbrev: str) -> Path | None:
    """data_dir/phase*/law_abbrev/ を探す."""
    for phase_dir in sorted(data_dir.iterdir()):
        if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
            continue
        cand = phase_dir / law_abbrev
        if cand.is_dir():
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data/v0.2"))
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--law-only", default=None, help="特定 law_abbrev のみ処理")
    ap.add_argument(
        "--articles",
        default=None,
        help="カンマ区切りの article_number のみ処理 (アトミックなパイロット/逐次展開用)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    articles: set[str] | None = None
    if args.articles:
        # underscore/hyphen どちらの入力でも hyphen 形式 (md 規約) に正規化して照合
        articles = {a.strip().replace("_", "-") for a in args.articles.split(",") if a.strip()}

    law_map = build_law_abbrev_to_id_phase(args.data_dir)
    if args.law_only:
        if args.law_only not in law_map:
            print(f"ERROR: law_abbrev not found: {args.law_only}", file=sys.stderr)
            return 1
        law_map = {args.law_only: law_map[args.law_only]}

    total_updated = 0
    all_warnings: list[str] = []
    for law_abbrev, (law_id, _phase) in sorted(law_map.items()):
        md_dir = find_md_dir(args.data_dir, law_abbrev)
        if md_dir is None:
            all_warnings.append(f"{law_abbrev}: md dir 不在")
            continue
        updated, warnings = process_law(
            law_abbrev, law_id, md_dir, args.xml_dir, args.dry_run, articles=articles
        )
        all_warnings.extend(warnings)
        if updated:
            print(f"  {law_abbrev}: {updated} 条文に表を反映", file=sys.stderr)
            total_updated += updated

    print(f"\n=== {total_updated} 条文に本則表を反映 ===", file=sys.stderr)
    if all_warnings:
        print(f"--- warnings ({len(all_warnings)}) ---", file=sys.stderr)
        for w in all_warnings:
            print(f"  - {w}", file=sys.stderr)
    if args.dry_run:
        print("(dry-run, 書き込みなし)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

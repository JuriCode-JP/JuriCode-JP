#!/usr/bin/env python3
"""build_chunks_from_md.py -- 正本 md の frontmatter から retrieval chunk を生成する.

責務: 「正本 md の paragraphs[].segments[]」→「build/chunks/{law}/{law}-article-{N}.chunks.jsonl」。

Why 正本 md を唯一の情報源にするか (★F3 の解消):
    従来、号 (kou) chunk だけは正本 md を経由せず e-Gov XML から**別経路**で生成され
    (extract_kou_from_xml.py)、chunk には号があるのに正本には無い、という乖離が
    21,002 件あった。同じ内容を 2 つの経路で作れば必ずずれる。正本 md を作り直して
    号を入れた今、chunk は正本から一方向に導出する。これで
      「chunk の総和 == 正本本文」(G0-b) と「chunk ⊂ 親条文」(G0-c)
    が構造的に保証される (正本にしか無いものは chunk にも無い、逆も然り)。

スコープ外 (別経路のまま。正本 md に対応物が無いため):
    - 表 chunk (extract_table_from_xml.py)  : md には GFM 表として載るが chunk は別ファイル
    - 附則 chunk (extract_supplproviso_from_xml.py) : 附則は正本 md に存在しない
    - rollup chunk (add_rollup_chunks.py)   : segment の派生 (条・項単位の連結)

★★ `build/chunks/` を丸ごと削除してはならない ★★
    このディレクトリには、**本ツールでは再生成できないストア**が同居している:
      通達 (*-tsutatsu)・タックスアンサー (*-taxanswer)・国税不服審判所の裁決 (kfs-*)
    これらは NTA / KFS の Web から取得してパースしたもので、法令 corpus とは別系統。
    `rm -rf build/chunks` をすると **NTA からの再取得が必要になる** (2026-07-14 に実際に
    消してしまい、退避ディレクトリから復元した)。
    本ツールは法令ストアだけを上書きするので、**消さずにそのまま再実行すればよい**。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pip install pyyaml")

_HERE = Path(__file__).resolve().parent
_SHARED_SRC = _HERE.parent.parent / "shared" / "src"
for _p in (str(_HERE), str(_SHARED_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from juricode_shared import safe_write_jsonl  # noqa: E402

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

#: chunk に写す segment のメタデータ (存在する場合のみ)。
_OPTIONAL_SEGMENT_FIELDS = (
    "item_number",
    "override_flag",
    "override_target",
    "applies_provisions",
    "references",
    "depends_on",
)


def build_chunks_for_article(md_text: str) -> list[dict]:
    """1 条の md から chunk レコード列を作る (文書順)."""
    m = _FRONTMATTER_RE.match(md_text)
    if not m:
        raise ValueError("missing frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}

    common = {
        "article_id": fm.get("article_id"),
        "law_id": fm.get("law_id"),
        "law_name_ja": fm.get("law_name_ja"),
        "article_number": fm.get("article_number"),
    }
    parent_section = fm.get("parent_section")

    chunks: list[dict] = []
    for para in fm.get("paragraphs") or []:
        pnum = para.get("number")
        for seg in para.get("segments") or []:
            chunk = {
                "id": seg["id"],
                **common,
                "paragraph_number": pnum,
                "segment_type": seg["type"],
                "modality": seg.get("modality", "unspecified"),
                "text": seg["text"],
            }
            if parent_section:
                chunk["parent_section"] = parent_section
            for field in _OPTIONAL_SEGMENT_FIELDS:
                if seg.get(field):
                    chunk[field] = seg[field]
            chunks.append(chunk)
    return chunks


def process_law(law_dir: Path, chunks_dir: Path, dry_run: bool) -> tuple[int, int, list[str]]:
    """1 法令の全条の chunk を書き出す. (条数, chunk 数, warnings)."""
    warnings: list[str] = []
    law_abbrev = law_dir.name
    out_dir = chunks_dir / law_abbrev
    n_articles = n_chunks = 0

    for md_path in sorted(law_dir.glob(f"{law_abbrev}-article-*.md")):
        try:
            chunks = build_chunks_for_article(md_path.read_text(encoding="utf-8"))
        except (ValueError, KeyError) as e:
            warnings.append(f"{md_path.name}: {e}")
            continue
        if not chunks:
            warnings.append(f"{md_path.name}: 0 segments (chunk が作られない)")
            continue
        n_articles += 1
        n_chunks += len(chunks)
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{md_path.stem}.chunks.jsonl"
            safe_write_jsonl(out_path, chunks)
    return n_articles, n_chunks, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data/v0.2"))
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    ap.add_argument("--law-only", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    law_dirs = [
        law_dir
        for phase_dir in sorted(args.data_dir.iterdir())
        if phase_dir.is_dir() and phase_dir.name.startswith("phase")
        for law_dir in sorted(phase_dir.iterdir())
        if law_dir.is_dir()
    ]
    if args.law_only:
        law_dirs = [d for d in law_dirs if d.name == args.law_only]
        if not law_dirs:
            print(f"ERROR: law_abbrev not found: {args.law_only}", file=sys.stderr)
            return 1

    total_articles = total_chunks = 0
    all_warnings: list[str] = []
    for law_dir in law_dirs:
        n_art, n_ch, warns = process_law(law_dir, args.chunks_dir, args.dry_run)
        all_warnings.extend(warns)
        total_articles += n_art
        total_chunks += n_ch
        print(f"  {law_dir.name}: {n_art} articles -> {n_ch} chunks", file=sys.stderr)

    print(f"\n=== {total_articles} articles -> {total_chunks} chunks ===", file=sys.stderr)
    if all_warnings:
        print(f"--- warnings ({len(all_warnings)}) ---", file=sys.stderr)
        for w in all_warnings[:40]:
            print(f"  - {w}", file=sys.stderr)
    if args.dry_run:
        print("(dry-run, 書き込みなし)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

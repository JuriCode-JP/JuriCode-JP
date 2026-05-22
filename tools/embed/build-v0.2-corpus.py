#!/usr/bin/env python3
"""build-v0.2-corpus.py — v0.2 chunks を 1 つの corpus JSONL に merge.

build/chunks/{law}/{law}-article-{N}.chunks.jsonl を全てまとめ、
embed.py が期待するフィールド (chunk_id, phase_category, hen_name_ja 等) を
flatten した状態で build/corpus-v0.2.jsonl に出力する.

--augment を付けると text field に「[法令名 第N条 (条見出し) 第N項 segment_label]」の
prefix を付加し、article-context-augmented 版 (corpus-v0.2-augmented.jsonl) を出力する.

使い方:
  python tools/embed/build-v0.2-corpus.py \\
    --chunks-dir build/chunks \\
    --output build/corpus-v0.2.jsonl

  python tools/embed/build-v0.2-corpus.py \\
    --augment \\
    --output build/corpus-v0.2-augmented.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


# law_abbrev → phase の mapping を v0.1 ディレクトリから構築
def build_law_to_phase(data_dir: Path) -> dict[str, str]:
    mapping = {}
    for phase_dir in data_dir.iterdir():
        if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
            continue
        for law_dir in phase_dir.iterdir():
            if not law_dir.is_dir():
                continue
            mapping[law_dir.name] = phase_dir.name
    return mapping


# article_id → article_caption の mapping を v0.1 .md の H1 から抽出
# 例: "# 民法 第415条(債務不履行による損害賠償)" → "債務不履行による損害賠償"
H1_PATTERN = re.compile(r"^#\s+.+?第[\d\-]+条(?:の[\d\-]+)?\s*[(\(（](.+?)[)\)）]")


def build_article_to_caption(data_dir: Path) -> dict[str, str]:
    """v0.1 .md の H1 から article_caption を抽出."""
    mapping: dict[str, str] = {}
    for md_path in data_dir.rglob("*-article-*.md"):
        article_id = None
        caption = None
        try:
            with md_path.open(encoding="utf-8") as fh:
                # frontmatter 跨いで body 内の H1 を探す
                in_frontmatter = False
                fm_end_seen = False
                for line in fh:
                    s = line.rstrip("\n")
                    if s == "---":
                        if not in_frontmatter:
                            in_frontmatter = True
                        else:
                            fm_end_seen = True
                        continue
                    if in_frontmatter and not fm_end_seen:
                        # article_id を抽出
                        m = re.match(r"^article_id:\s*([\w\-]+)", s)
                        if m:
                            article_id = m.group(1)
                        continue
                    if fm_end_seen:
                        m = H1_PATTERN.match(s)
                        if m:
                            caption = m.group(1).strip()
                            break
        except Exception:
            continue
        if article_id and caption:
            mapping[article_id] = caption
    return mapping


# segment_type → 日本語ラベル
SEGMENT_TYPE_LABEL = {
    "simple": "",
    "honbun": "本文",
    "tadashi": "ただし書",
    "zen_dan": "前段",
    "kou_dan": "後段",
    "hashira": "柱書",
    "kou": "号",  # item_number で具体化
    "tokusoku": "特則",
    "junyou": "準用",
    "rollup": "全文",  # 本則 rollup chunk (add_rollup_chunks.py)
}


# Fix 1: supplproviso 固有フィールドを flatten_chunk で pass-through
SUPPLPROVISO_FIELDS = (
    "supplproviso_id", "supplproviso_label",
    "amend_law_num", "amend_era", "amend_year_gengo",
    "amend_year_seireki", "amend_month", "amend_day", "amend_law_num_int",
    "enforcement_date", "effective_status",
    "supplproviso_article_number", "supplproviso_article_caption",
    "topic",
    "target_main_articles_raw", "target_main_article_ids",
)


def make_augmented_text(chunk: dict, caption: str | None) -> str:
    """segment text に context prefix を付加."""
    law_name = chunk.get("law_name_ja") or ""
    segment_type = chunk.get("segment_type") or ""
    text = chunk.get("text") or ""

    # Fix 2: 附則 (supplproviso / supplproviso_rollup) 用 prefix
    if segment_type in ("supplproviso", "supplproviso_rollup"):
        parts: list[str] = []
        if law_name:
            parts.append(law_name)
        parts.append("附則")
        amend_law_num = chunk.get("amend_law_num")
        if amend_law_num:
            parts.append(f"({amend_law_num})")
        sp_art = chunk.get("supplproviso_article_number")
        if sp_art:
            parts.append(f"第{sp_art}条")
        sp_cap = chunk.get("supplproviso_article_caption")
        if sp_cap:
            parts.append(f"({sp_cap})")
        para = chunk.get("paragraph_number")
        if para and segment_type == "supplproviso":
            parts.append(f"第{para}項")
        topic = chunk.get("topic")
        if topic and topic not in ("unspecified", "rollup"):
            parts.append(f"[{topic}]")
        prefix = " ".join(parts) if parts else ""
        if prefix:
            return f"{prefix}\n{text}"
        return text

    # 本則 (article-based segments) 用 prefix (既存ロジック)
    article_number = chunk.get("article_number") or ""
    paragraph_number = chunk.get("paragraph_number")
    item_number = chunk.get("item_number")

    seg_label = SEGMENT_TYPE_LABEL.get(segment_type, segment_type)
    if segment_type == "kou" and item_number is not None:
        seg_label = f"第{item_number}号"

    parts = []
    if law_name:
        parts.append(law_name)
    if article_number:
        parts.append(f"第{article_number}条")
    if caption:
        parts.append(f"({caption})")
    if paragraph_number:
        parts.append(f"第{paragraph_number}項")
    if seg_label:
        parts.append(seg_label)

    prefix = " ".join(parts) if parts else ""
    if prefix:
        return f"{prefix}\n{text}"
    return text


def flatten_chunk(
    chunk: dict,
    phase_category: str,
    augment: bool,
    article_to_caption: dict[str, str],
) -> dict:
    """v0.2 chunk を embed.py が期待する形式に flatten."""
    parent = chunk.get("parent_section") or {}
    article_id = chunk.get("article_id")
    caption = article_to_caption.get(article_id) if article_id else None

    raw_text = chunk.get("text", "")
    if augment:
        embedding_text = make_augmented_text(chunk, caption)
    else:
        embedding_text = raw_text

    flat = {
        # v0.2 segment 固有
        "chunk_id": chunk["id"],
        "segment_id": chunk["id"],
        "segment_type": chunk.get("segment_type"),
        "paragraph_number": chunk.get("paragraph_number"),
        # v0.1 互換
        "article_id": article_id,
        "law_id": chunk.get("law_id"),
        "law_name_ja": chunk.get("law_name_ja"),
        "article_number": chunk.get("article_number"),
        "article_caption": caption,
        "phase_category": phase_category,
        "hen_name_ja": parent.get("hen_name_ja"),
        "shou_name_ja": parent.get("shou_name_ja"),
        "setsu_name_ja": parent.get("setsu_name_ja"),
        "kan_name_ja": parent.get("kan_name_ja"),
        "text": embedding_text,
        "text_raw": raw_text,
        "override_flag": chunk.get("override_flag", False),
        "override_target": chunk.get("override_target", []),
        "applies_provisions": chunk.get("applies_provisions", []),
        "references": chunk.get("references", []),
        "depends_on": chunk.get("depends_on"),
        "item_number": chunk.get("item_number"),
    }
    # Fix 1: supplproviso 固有フィールドを pass-through
    for f in SUPPLPROVISO_FIELDS:
        if f in chunk:
            flat[f] = chunk[f]
    return flat


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--output", type=Path, default=Path("build/corpus-v0.2.jsonl"))
    ap.add_argument("--augment", action="store_true",
                    help="text に [法令名 第N条 (見出し) 第N項 segment_label] prefix を付加")
    args = ap.parse_args()

    if not args.chunks_dir.exists():
        sys.exit(f"ERROR: chunks dir not found: {args.chunks_dir}")

    law_to_phase = build_law_to_phase(args.data_dir)
    print(f"law -> phase mapping: {len(law_to_phase)} laws", file=sys.stderr)

    article_to_caption = {}
    if args.augment:
        print("Building article_id -> caption map from v0.1 .md ...", file=sys.stderr)
        article_to_caption = build_article_to_caption(args.data_dir)
        print(f"  caption map: {len(article_to_caption)} entries", file=sys.stderr)

    chunk_files = sorted(args.chunks_dir.rglob("*.chunks.jsonl"))
    # backup ディレクトリは除外 (2 重 merge 防止)
    chunk_files = [f for f in chunk_files if "backup" not in str(f).lower()]
    print(f"chunk files found: {len(chunk_files)}", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    total_chunks = 0
    type_counts = Counter()
    phase_counts = Counter()
    missing_phase = set()
    augmented_with_caption = 0

    with args.output.open("w", encoding="utf-8") as out:
        for f in chunk_files:
            law_abbrev = f.parent.name
            phase = law_to_phase.get(law_abbrev, "unknown")
            if phase == "unknown":
                missing_phase.add(law_abbrev)
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as e:
                        print(f"WARN {f}: {e}", file=sys.stderr)
                        continue
                    flat = flatten_chunk(chunk, phase, args.augment, article_to_caption)
                    out.write(json.dumps(flat, ensure_ascii=False) + "\n")
                    total_chunks += 1
                    type_counts[flat.get("segment_type") or "None"] += 1
                    phase_counts[phase] += 1
                    if args.augment and flat.get("article_caption"):
                        augmented_with_caption += 1

    print(f"\n=== Merge summary ===", file=sys.stderr)
    print(f"Total chunks: {total_chunks}", file=sys.stderr)
    print(f"Output: {args.output} ({args.output.stat().st_size / 1024 / 1024:.1f} MB)", file=sys.stderr)
    if args.augment:
        print(f"Augment: ON  (chunks with caption: {augmented_with_caption}/{total_chunks})", file=sys.stderr)
    else:
        print(f"Augment: OFF (raw segment text)", file=sys.stderr)
    print(f"\nSegment type distribution:", file=sys.stderr)
    for t, c in type_counts.most_common():
        print(f"  {t:12s}: {c:6d}", file=sys.stderr)
        print(f"  {t:12s}: {c:6d}", file=sys.stderr)
    if missing_phase:
        print(f"\nWARNING: missing phase for laws: {sorted(missing_phase)}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

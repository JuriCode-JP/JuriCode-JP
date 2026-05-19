#!/usr/bin/env python3
"""
JuriCode-JP → BigQuery (Lawsy-Custom-BQ) JSON Lines Exporter
=============================================================

JuriCode-JP の法令データ Markdown ファイルを読み込み、BigQuery 投入用の
JSON Lines (NDJSON) 形式で出力する。これにより以下が同時に実現される:

  1. デジタル庁「源内 (GENAI)」の法制度 AI アプリ Lawsy-Custom-BQ への接続
  2. RAG (Retrieval-Augmented Generation) ready なデータ形式への変換

各 Markdown ファイル (例: examples/keihou/keihou-article-36.md) から、
条文単位 (--chunk=article) または項単位 (--chunk=paragraph) の
レコードを抽出して出力する。

Usage:
    # 既存サンプル 2 件 (刑法36条 + 刑訴法198条) を条文単位で書き出し
    python tools/export/lawsy-bq/export-jsonl.py \\
        --input examples \\
        --output build/juricode-bq.jsonl

    # 項単位 (RAG 用にチャンクを細かくしたい場合)
    python tools/export/lawsy-bq/export-jsonl.py \\
        --input examples \\
        --chunk paragraph

    # 標準出力にそのまま流す (パイプ用)
    python tools/export/lawsy-bq/export-jsonl.py --input examples

Requires: pip install pyyaml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pyyaml not installed. Run: pip install pyyaml")


# ---------------------------------------------------------------------------
# Frontmatter / body parsing
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)

JA_SECTION_RE = re.compile(
    r"##\s*原文\s*\(?日本語\)?\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL
)

# Paragraph heading inside the Japanese-original section, e.g.
#   "### 第三十六条"          -> paragraph 1 (implicit)
#   "### 第三十六条第二項"     -> paragraph 2
#   "### 第百九十八条第3項"    -> paragraph 3
PARAGRAPH_HEADING_RE = re.compile(
    r"^###\s+第[一二三四五六七八九十百千0-9]+条"
    r"(?:第([一二三四五六七八九十百千0-9]+)項)?\s*$",
    re.MULTILINE,
)

KANSUJI_BASIC = {
    "〇": 0, "零": 0,
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def kansuji_to_int(s: str) -> int:
    """Convert simple kansuji or arabic digits to int."""
    s = s.strip()
    if not s:
        return 1
    if s.isdigit():
        return int(s)
    if "百" in s:
        head, _, tail = s.partition("百")
        hundreds = KANSUJI_BASIC.get(head, 1) if head else 1
        return hundreds * 100 + (kansuji_to_int(tail) if tail else 0)
    if "十" in s:
        head, _, tail = s.partition("十")
        tens = KANSUJI_BASIC.get(head, 1) if head else 1
        return tens * 10 + (KANSUJI_BASIC.get(tail, 0) if tail else 0)
    return KANSUJI_BASIC.get(s, 1)


def clean_text(text: str) -> str:
    """Strip trailing horizontal rules ('---') and surrounding whitespace.

    The Japanese-original section often ends with '---' as a Markdown
    horizontal rule before the next section. Strip those so they don't
    leak into the RAG-ready text content.
    """
    lines = text.splitlines()
    while lines and (not lines[-1].strip() or set(lines[-1].strip()) <= {"-"}):
        lines.pop()
    return "\n".join(lines).strip()


def parse_markdown_article(path: Path) -> dict:
    """Read a JuriCode-JP article Markdown file. Returns frontmatter + body."""
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path.name}: missing YAML frontmatter")
    fm = yaml.safe_load(match.group(1)) or {}
    return {"path": path, "frontmatter": fm, "body": match.group(2)}


def extract_japanese_body(body: str) -> str:
    """Extract the '## 原文 (日本語)' section content (Markdown)."""
    m = JA_SECTION_RE.search(body)
    if not m:
        raise ValueError("'## 原文 (日本語)' section not found")
    return clean_text(m.group(1))


def split_paragraphs(ja_body: str) -> list[tuple[int, str]]:
    """Split the Japanese-original section into (paragraph_number, text)."""
    headings = list(PARAGRAPH_HEADING_RE.finditer(ja_body))
    if not headings:
        return [(1, ja_body.strip())]

    paragraphs: list[tuple[int, str]] = []
    for i, h in enumerate(headings):
        para_str = h.group(1)
        para_num = kansuji_to_int(para_str) if para_str else (1 if i == 0 else i + 1)
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(ja_body)
        text = clean_text(ja_body[start:end])
        if text:
            paragraphs.append((para_num, text))
    return paragraphs


# ---------------------------------------------------------------------------
# Record generation
# ---------------------------------------------------------------------------


def _isoformat(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def base_record(fm: dict) -> dict:
    return {
        "article_id": fm.get("article_id"),
        "law_id": fm.get("law_id"),
        "law_name_ja": fm.get("law_name_ja"),
        "law_name_en": fm.get("law_name_en"),
        "article_number": str(fm.get("article_number", "")),
        "source_url": fm.get("source_url"),
        "source_format": fm.get("source_format"),
        "version_date": _isoformat(fm.get("version_date")),
        "last_verified": _isoformat(fm.get("last_verified")),
        "license": fm.get("license", "MIT"),
        "translation_status": fm.get("translation_status", "none"),
        "tags": fm.get("tags", []) or [],
    }


def to_bq_records(parsed: dict, chunk_mode: str) -> list[dict]:
    fm = parsed["frontmatter"]
    ja_body = extract_japanese_body(parsed["body"])
    base = base_record(fm)

    if chunk_mode == "article":
        return [{
            **base,
            "chunk_type": "article",
            "paragraph_number": None,
            "text": ja_body,
        }]

    records = []
    for para_num, text in split_paragraphs(ja_body):
        records.append({
            **base,
            "chunk_type": "paragraph",
            "paragraph_number": para_num,
            "text": text,
        })
    return records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


import contextlib
from typing import Iterator, TextIO


@contextlib.contextmanager
def _open_output(path: Path | None) -> Iterator[TextIO]:
    """Yield an output file handle, falling back to stdout when path is None.

    The context manager closes the file on exit, but never closes stdout.
    This ensures clean handling even when an exception is raised mid-write.

    Args:
        path: Output file path, or None for stdout.

    Yields:
        A writable text stream.
    """
    if path is None:
        yield sys.stdout
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yield fh


def _build_argparser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser. No side effects."""
    ap = argparse.ArgumentParser(
        description="JuriCode-JP Markdown → BigQuery JSON Lines (NDJSON) "
                    "exporter for 'Lawsy-Custom-BQ' (GENAI) ingestion."
    )
    ap.add_argument(
        "--input", type=Path, default=Path("examples"),
        help="Directory to search for *-article-*.md files (default: examples)",
    )
    ap.add_argument(
        "--output", type=Path, default=None,
        help="Output file path. If omitted, writes JSONL to stdout.",
    )
    ap.add_argument(
        "--chunk", choices=["article", "paragraph"], default="article",
        help="Chunk granularity: 'article' (1 record/条) or "
             "'paragraph' (1 record/項). Default: article.",
    )
    return ap


def main() -> int:
    """CLI driver. Returns process exit code."""
    args = _build_argparser().parse_args()

    if not args.input.exists():
        print(f"ERROR: input path does not exist: {args.input}",
              file=sys.stderr)
        return 1
    if not args.input.is_dir():
        print(f"ERROR: --input must be a directory: {args.input}",
              file=sys.stderr)
        return 1

    md_files = sorted(args.input.rglob("*-article-*.md"))
    if not md_files:
        print(f"ERROR: no '*-article-*.md' files found under {args.input}",
              file=sys.stderr)
        return 1

    count = 0
    skipped = 0
    with _open_output(args.output) as out_handle:
        for path in md_files:
            try:
                parsed = parse_markdown_article(path)
                for record in to_bq_records(parsed, args.chunk):
                    out_handle.write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )
                    count += 1
            except (ValueError, OSError, UnicodeDecodeError) as e:
                # Narrow exception list: catch parse / IO failures only,
                # let unexpected errors (e.g. KeyboardInterrupt) propagate.
                print(f"WARN: skipping {path}: {e}", file=sys.stderr)
                skipped += 1

    print(f"OK: {count} record(s) written from {len(md_files) - skipped}/"
          f"{len(md_files)} file(s) in chunk={args.chunk} mode",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

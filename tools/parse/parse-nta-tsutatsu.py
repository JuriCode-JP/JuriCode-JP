#!/usr/bin/env python3
"""parse-nta-tsutatsu.py -- NTA HTML tsutatsu (circular) -> Directive JSONL chunks.

Usage:
    python tools/parse/parse-nta-tsutatsu.py \\
        --cache-dir cache/tsutatsu/hojin/09 \\
        --output-dir build/chunks/hojin-kihon-tsutatsu \\
        --law-abbrev hojin-kihon-tsutatsu \\
        --chapter 09 \\
        --section 02

Output: build/chunks/hojin-kihon-tsutatsu/hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl

One record per directive item (e.g. 9-2-9).
Each record has:
    id              : "hojin-kihon-tsutatsu-9-2-9"  (directive_id)
    directive_id    : same as id
    law_name_ja     : "法人税基本通達"
    law_abbrev      : "hojin-kihon-tsutatsu"
    chapter_section : "9-2" (chapter-section prefix)
    directive_number: "9-2-9"
    title           : "(債務の免除による利益その他の経済的な利益)"
    text            : full body text (Markdown, items as list)
    amendment_note  : raw amendment string e.g. "(平19年課法2-3...)"
    related_articles: list of {law_abbrev, article_id, article_number, raw}
    source_url      : "https://www.nta.go.jp/law/tsutatsu/kihon/hojin/09/09_02_02.htm"
    license         : "public-domain-13-2"
    segment_type    : "tsutatsu"
    article_id      : None  (for retrieve.py compatibility)
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")

# juricode_shared を import 可能にする (DirectiveChunk による出力検証用)。
# 取込ループは main() の sys.path patch より前に走るため module レベルで patch する
# (parse-nta-taxanswer.py と同パターン)。
_SHARED_SRC = Path(__file__).resolve().parents[1] / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LAW_NAME_JA = "法人税基本通達"
SOURCE_URL_BASE = "https://www.nta.go.jp/law/tsutatsu/kihon/hojin"
LICENSE = "public-domain-13-2"

# 出力 JSONL の chunk-level キー順マスタ (出力保持の正本・FU-514)。
# DirectiveChunk.model_dump() (意味フィールド) + 配管フィールドをマージした後、
# この順で再構築して現 dict の interleaved キー順をバイト再現する。
# naive な {**semantic, **pipeline} は配管キーが末尾集中で順序が崩れる (Bug1)。
DIRECTIVE_KEY_ORDER = [
    "id",
    "directive_id",
    "law_name_ja",
    "law_abbrev",
    "directive_number",
    "title",
    "text",
    "amendment_note",
    "related_articles",
    "source_url",
    "license",
    "segment_type",
    "article_id",
    "law_name_ja_display",
]

# Abbreviation prefix -> law_abbrev mapping (R2: 接頭辞明示のみ)
LAW_PREFIX_MAP = {
    "法": "houjin-zei-hou",
    "令": "houjin-zei-hou-shikkourei",
    "規": "houjin-zei-hou-shikoukisoku",
    "措法": "sochi-hou",  # corpus 未収録 -> warn, no link
}
CORPUS_UNREGISTERED = {"sochi-hou"}  # R2: warn + skip link


# ---------------------------------------------------------------------------
# Text normalization helpers (R7, R10)
# ---------------------------------------------------------------------------

# All horizontal bar variants -> ASCII hyphen
_BAR_RE = re.compile(r"[\-\uff0d\u2010\u30fc\u2212\u2014\u2015]")
# Non-breaking space / full-width space -> regular space
_NBSP_RE = re.compile("[\u00a0\u3000 ]")


def _normalize_bars(s: str) -> str:
    """Replace all horizontal bar variants with ASCII hyphen (R7)."""
    return _BAR_RE.sub("-", s)


def _normalize_whitespace(s: str) -> str:
    """Replace non-breaking and full-width spaces with ASCII space (R10)."""
    return _NBSP_RE.sub(" ", s)


def _normalize_text(s: str) -> str:
    return _normalize_whitespace(_normalize_bars(s))


# ---------------------------------------------------------------------------
# Related article extraction (R2, R8, R12)
# ---------------------------------------------------------------------------

# Pattern: 法/令/規/措法 + 第 + article + optional branches + optional paragraph
# R8: relative refs (同条/同法/同項) excluded by requiring explicit prefix
# R12: multi-level no: (?:の\d+)* (not just ?)
_LAW_REF_RE = re.compile(
    r"(法|令|規|措法)第(\d+)条(?:の(\d+))*(?:第(\d+)項)?",
)
# The above only captures last の-branch. Use a more explicit form:
_LAW_REF_FULL_RE = re.compile(
    r"(法|令|規|措法)第(\d+)条((?:の\d+)*)"
    r"(?:第(\d+)項)?",
)


def _extract_related_articles(text: str) -> list[dict]:
    """Extract law article references from text (R2, R8, R12).

    Returns list of dicts with keys: raw, law_abbrev, article_number, article_id.
    Unresolved references (corpus未収録) are included with article_id=None + warn.
    """
    results: list[dict] = []
    seen_raw: set[str] = set()

    for m in _LAW_REF_FULL_RE.finditer(text):
        prefix = m.group(1)  # 法/令/規/措法
        base_num = m.group(2)  # e.g. "34"
        no_suffix = m.group(3) or ""  # e.g. "の2の2" or ""
        # para = m.group(4)  -- not used for article_id

        raw = m.group(0)
        if raw in seen_raw:
            continue
        seen_raw.add(raw)

        law_abbrev = LAW_PREFIX_MAP.get(prefix)
        if law_abbrev is None:
            # Unknown prefix: skip silently (R8: only explicit prefixes)
            continue

        # Build article_number: base + each の-branch as -N
        # "の2の2" -> ["2", "2"]
        branches = re.findall(r"\d+", no_suffix)
        article_number = base_num
        if branches:
            article_number = base_num + "-" + "-".join(branches)

        if law_abbrev in CORPUS_UNREGISTERED:
            warnings.warn(
                f"WARN: {raw!r} -> {law_abbrev} is not in corpus (corpus未収録). "
                "Keeping raw reference without article_id link.",
                stacklevel=2,
            )
            results.append(
                {
                    # disjoint Union の Unlinked 形に合わせ article_id キーは持たせない
                    # (FU-514: DirectiveUnlinkedArticleRef は extra="forbid")。
                    # 現コーパスは unlinked 0 件なので出力 byte は不変。
                    "raw": raw,
                    "law_abbrev": law_abbrev,
                    "article_number": article_number,
                    "unlinked_reason": "corpus_unregistered",
                }
            )
        else:
            article_id = f"{law_abbrev}-art-{article_number}"
            results.append(
                {
                    "raw": raw,
                    "law_abbrev": law_abbrev,
                    "article_number": article_number,
                    "article_id": article_id,
                }
            )

    return results


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

# Directive number pattern after normalization (all bars -> -)
# Full-width digits may appear; normalize before matching
_DIRECTIVE_NUM_RE = re.compile(r"^(\d+-\d+-\d+(?:の\d+)*)\s*$")


def _detect_charset(raw: bytes) -> str:
    """Detect encoding from HTML meta tag or default to cp932 (R1)."""
    # Try HTTP-equiv meta
    m = re.search(rb"charset=([^\s\"'>;]+)", raw[:2000], re.I)
    if m:
        enc = m.group(1).decode("ascii", errors="replace").strip().lower()
        # Normalize shift_jis variants to cp932
        if enc in ("shift_jis", "shift-jis", "sjis", "x-sjis", "shift_jis-2004"):
            return "cp932"
        return enc
    return "cp932"


def _build_directive_record(
    *,
    num: str,
    title: str,
    body: str,
    amendment_note: str,
    related: list[dict],
    source_url: str,
    law_abbrev: str,
) -> dict:
    """Validate via DirectiveChunk (Pydantic IR) and reconstruct the 14-key record.

    Why: routing through DirectiveChunk catches malformed refs at parse time and
    keeps the disjoint linked/unlinked Union honest, while the explicit
    DIRECTIVE_KEY_ORDER reconstruction reproduces the historical interleaved key
    order byte-for-byte. Pipeline fields (id / law_name_ja / law_name_ja_display
    / segment_type / article_id) are merged post-dump (not part of the semantic
    IR), and article_id is injected as None explicitly so the key is always
    present (Bug29: never silently dropped via .get()).
    """
    from juricode_shared.ir import DirectiveChunk

    directive_id = f"{law_abbrev}-{num}"
    chunk = DirectiveChunk(
        directive_id=directive_id,
        directive_number=num,
        law_abbrev=law_abbrev,
        title=title,
        text=body,
        amendment_note=amendment_note,
        related_articles=related,  # dict -> disjoint Union が linked/unlinked を判別
        source_url=source_url,
        license=LICENSE,
    )
    semantic = chunk.model_dump(mode="json")

    # 配管フィールドを明示注入 (retrieve.py 互換)。article_id は None でも必ず入れる。
    merged = {
        **semantic,
        "id": directive_id,
        "law_name_ja": LAW_NAME_JA,
        "law_name_ja_display": f"{LAW_NAME_JA} {num}",
        "segment_type": "tsutatsu",
        "article_id": None,
    }

    # キー順再構築: 全 14 キーが存在する前提 (欠落は KeyError で fail loud)。
    return {k: merged[k] for k in DIRECTIVE_KEY_ORDER}


def _extract_directive_items(soup: BeautifulSoup, source_url: str, law_abbrev: str) -> list[dict]:
    """Parse BeautifulSoup of a single htm page -> list of directive chunk dicts.

    One dict per directive item (e.g. 9-2-9, 9-2-10, ...).
    R4: handles multiple items per page.
    """
    items: list[dict] = []
    current_title: str | None = None
    current_num: str | None = None
    current_body_parts: list[str] = []
    current_amendment: str | None = None

    def _flush(num: str | None, title: str | None, parts: list[str], amend: str | None) -> None:
        if num is None:
            return
        body = "\n".join(parts).strip()
        # Extract amendment note from end of body if not already found
        amendment_note = amend
        if amendment_note is None:
            amend_m = re.search(r"（[^）]*課法[^）]*）\s*$", body)
            if amend_m:
                amendment_note = amend_m.group(0)
                body = body[: amend_m.start()].rstrip()

        # Normalize bars/whitespace in body
        body = _normalize_text(body)
        related = _extract_related_articles(body)

        items.append(
            _build_directive_record(
                num=num,
                title=title or "",
                body=body,
                amendment_note=amendment_note or "",
                related=related,
                source_url=source_url,
                law_abbrev=law_abbrev,
            )
        )

    body_area = soup.find(id="bodyArea") or soup.find(id="contents")
    if body_area is None:
        warnings.warn(f"WARN: bodyArea not found in {source_url}", stacklevel=2)
        return items

    for tag in body_area.find_all(["h1", "h2", "p"]):
        tag_name = tag.name

        if tag_name in ("h1", "h2"):
            # h2 is the title before a directive item. e.g. "（債務の免除による利益...）"
            # h1 is the section header - skip
            if tag_name == "h2":
                current_title = tag.get_text(strip=True)
            continue

        # p tags: check if it starts a new directive item
        strong = tag.find("strong")
        if strong:
            raw_num_text = _normalize_text(strong.get_text())
            num_match = _DIRECTIVE_NUM_RE.match(raw_num_text.strip())
            if num_match:
                # Flush previous item
                _flush(current_num, current_title, current_body_parts, current_amendment)
                # Start new item
                current_num = num_match.group(1)
                current_body_parts = []
                current_amendment = None
                # Get body text after the number (remove strong element text)
                strong.decompose()
                # R13: explicit newline before text (inline -> block)
                remaining = _normalize_text(tag.get_text(separator="\n")).strip()
                if remaining:
                    current_body_parts.append(remaining)
                continue

        # Regular paragraph (indent1/indent2/other)
        if current_num is not None:
            classes = tag.get("class") or []
            raw_text = _normalize_text(tag.get_text(separator="\n")).strip()
            if not raw_text:
                continue
            if "indent2" in classes:
                # R13: items as block lines
                current_body_parts.append(raw_text)
            elif "indent1" in classes:
                current_body_parts.append(raw_text)
            else:
                current_body_parts.append(raw_text)

    # Flush last item
    _flush(current_num, current_title, current_body_parts, current_amendment)

    # Validate: 0 items = parse error
    if not items:
        warnings.warn(f"WARN: no directive items parsed from {source_url}", stacklevel=2)

    return items


def parse_file(htm_path: Path, law_abbrev: str, chapter: str, section: str) -> list[dict]:
    """Parse a single cached HTML file -> list of directive chunk dicts."""
    raw = htm_path.read_bytes()
    enc = _detect_charset(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except (LookupError, UnicodeDecodeError) as e:
        warnings.warn(
            f"WARN: decode error ({e}), falling back to cp932 for {htm_path.name}", stacklevel=2
        )
        text = raw.decode("cp932", errors="replace")

    # Verify known text decoded correctly (R1 sanity check)
    if "経済的" not in text and "役員" not in text and "退職" not in text:
        warnings.warn(
            f"WARN: expected Japanese text not found after decode in {htm_path.name}. "
            f"Charset detected: {enc}",
            stacklevel=2,
        )

    soup = BeautifulSoup(text, "html.parser")

    # Build source URL from filename
    stem = htm_path.stem  # e.g. "09_02_02"
    source_url = f"{SOURCE_URL_BASE}/{chapter}/{stem}.htm"

    items = _extract_directive_items(soup, source_url, law_abbrev)
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse NTA tsutatsu HTML -> directive JSONL chunks.")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("cache/tsutatsu/hojin/09"),
        help="Directory containing cached .htm files.",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/chunks/hojin-kihon-tsutatsu"),
        help="Output directory for JSONL chunk file.",
    )
    ap.add_argument(
        "--law-abbrev",
        default="hojin-kihon-tsutatsu",
        help="Abbreviation for this circular (used in directive_id prefix).",
    )
    ap.add_argument("--chapter", default="09", help="Chapter directory name (e.g. '09').")
    ap.add_argument("--section", default="02", help="Section number prefix (e.g. '02').")
    ap.add_argument(
        "--glob-pattern",
        default="*.htm",
        help="Glob pattern to match HTML files in cache-dir.",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if not args.cache_dir.exists():
        print(f"ERROR: cache-dir not found: {args.cache_dir}", file=sys.stderr)
        return 1

    htm_files = sorted(args.cache_dir.glob(args.glob_pattern))
    if not htm_files:
        print(f"ERROR: no .htm files found in {args.cache_dir}", file=sys.stderr)
        return 1

    print(f"Parsing {len(htm_files)} HTML file(s) from {args.cache_dir}", file=sys.stderr)

    all_items: list[dict] = []
    seen_ids: set[str] = set()
    errors: list[str] = []

    for htm_path in htm_files:
        try:
            items = parse_file(htm_path, args.law_abbrev, args.chapter, args.section)
        except Exception as e:
            msg = f"ERROR: failed to parse {htm_path.name}: {e}"
            print(msg, file=sys.stderr)
            errors.append(msg)
            continue

        if args.verbose:
            print(f"  {htm_path.name}: {len(items)} items", file=sys.stderr)

        for item in items:
            did = item["directive_id"]
            if did in seen_ids:
                print(
                    f"  WARN: duplicate directive_id {did!r} from {htm_path.name}", file=sys.stderr
                )
                continue
            seen_ids.add(did)
            all_items.append(item)

    if not all_items:
        print("ERROR: no directive items produced", file=sys.stderr)
        return 1

    # Sort by directive_number for deterministic output
    # e.g. "9-2-9" < "9-2-9の2" < "9-2-10" < "9-2-12の2"
    def _sort_key(item: dict) -> tuple:
        num = item["directive_number"]  # e.g. "9-2-12の2の3"
        # Split on hyphen first, then on "の" within each part
        parts: list[int] = []
        for segment in num.split("-"):
            for sub in re.split(r"の", segment):
                parts.append(int(sub) if sub.isdigit() else 0)
        # Pad to fixed length for comparison
        while len(parts) < 6:
            parts.append(0)
        return tuple(parts)

    all_items.sort(key=_sort_key)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{args.law_abbrev}.tsutatsu.chunks.jsonl"

    # safe_write via juricode_shared
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "src"))
    from juricode_shared.safe_write import safe_write_jsonl

    safe_write_jsonl(out_path, all_items)

    print(f"Written {len(all_items)} directive chunks -> {out_path}", file=sys.stderr)

    # Summary
    for item in all_items:
        n_refs = len(item["related_articles"])
        linked = sum(1 for r in item["related_articles"] if r.get("article_id"))
        print(
            f"  {item['directive_number']:12s}  refs={n_refs}(linked={linked})  "
            f"chars={len(item['text'])}",
            file=sys.stderr,
        )

    if errors:
        print(f"\n{len(errors)} error(s) during parsing:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

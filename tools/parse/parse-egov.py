#!/usr/bin/env python3
"""parse-egov.py — e-Gov 法令 XML to JuriCode-JP Markdown 変換器.

e-Gov 法令API v2 から取得した法令 XML を JuriCode-JP の 1 条 1 ファイル
Markdown 形式に変換する. _source-manifest.json も同時生成し, Layer 3 の
verify.py で本文改変を検知する.

詳細設計: docs/verification-framework.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import warnings
from datetime import UTC, date, datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pip install pyyaml")

# Security: prefer defusedxml to defend against XXE / billion-laughs / decompression
# bomb. Falls back to stdlib xml.etree with a loud warning.
try:
    import defusedxml.ElementTree as ET  # type: ignore

    _USING_DEFUSEDXML = True
except ImportError:
    import xml.etree.ElementTree as ET  # type: ignore

    _USING_DEFUSEDXML = False
    warnings.warn(
        "defusedxml not installed. Falling back to xml.etree.ElementTree. "
        "Install via: pip install defusedxml",
        RuntimeWarning,
        stacklevel=2,
    )

sys.path.insert(0, str(Path(__file__).parent))
from _canonicalize import canonicalize

PARSER_VERSION = "tools/parse/parse-egov.py@0.2.0"

# Security: --abbrev becomes a path component. Restrict to safe charset.
ABBREV_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

LAW_NAME_EN = {
    "140AC0000000045": "Penal Code",
    "323AC0000000131": "Code of Criminal Procedure",
    "329AC0000000162": "Police Act",
    "323AC0000000136": "Police Duties Execution Act",
    "129AC0000000089": "Civil Code",
    "132AC0000000048": "Commercial Code",
    "417AC0000000086": "Companies Act",
    "405AC0000000088": "Administrative Procedure Act",
    "322AC0000000067": "Local Autonomy Act",
    "426AC0000000068": "Administrative Complaint Review Act",
}

ERA_OFFSET = {"Meiji": 1867, "Taisho": 1911, "Showa": 1925, "Heisei": 1988, "Reiwa": 2018}

KANSUJI = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def extract_all_text(elem):
    """Recursively collect all text content of an XML element + descendants.

    Args:
        elem: ElementTree Element or None.

    Returns:
        Concatenated text content in document order. Empty if elem is None.

    Complexity: O(n) in descendant nodes.
    """
    if elem is None:
        return ""
    parts = [elem.text or ""]
    for child in elem:
        parts.append(extract_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def get_int_attribute(elem, name, default=1):
    """Read an integer attribute with a safe fallback.

    Args:
        elem: XML element.
        name: Attribute name.
        default: Fallback when attribute is missing or non-integer.
    """
    try:
        return int(elem.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# Backward-compatibility aliases (in case earlier code imported these names).
_text = extract_all_text
_attr_int = get_int_attribute


def parse_egov_xml(xml_text):
    """Parse e-Gov 法令 XML (Standard Law Schema v3) into a structured dict.

    Args:
        xml_text: Raw XML text (UTF-8 decoded).

    Returns:
        dict with keys: law_name_ja, promulgation, articles.

    Raises:
        ValueError: Missing <Law>/<LawBody>/<MainProvision>, or empty input.
        ET.ParseError: Malformed XML.

    Security: Uses defusedxml when available.
    """
    if not xml_text or not xml_text.strip():
        raise ValueError("Empty XML input")
    root = ET.fromstring(xml_text)
    if root.tag != "Law":
        law = root.find(".//Law")
        if law is None:
            raise ValueError("No <Law> element found")
        root = law

    law_body = root.find("LawBody")
    if law_body is None:
        raise ValueError("No <LawBody> in XML")

    law_title = (extract_all_text(law_body.find("LawTitle")) or "").strip()

    # Promulgation date best-effort
    promulgation = None
    era = root.get("Era")
    year = root.get("Year")
    month = root.get("PromulgateMonth")
    day = root.get("PromulgateDay")
    if year and month and day:
        try:
            promulgation = date(
                ERA_OFFSET.get(era or "", 0) + int(year),
                int(month),
                int(day),
            )
        except (ValueError, TypeError):
            promulgation = None

    main = law_body.find("MainProvision")
    if main is None:
        raise ValueError("No <MainProvision> in XML")

    return {
        "law_name_ja": law_title,
        "promulgation": promulgation,
        "articles": _walk_articles(main, []),
    }


def _walk_articles(elem, parent_stack):
    """Recurse to collect <Article> entries, tracking parent sections."""
    results = []
    structural = {
        "Part": "hen",
        "Chapter": "shou",
        "Section": "setsu",
        "Subsection": "kan",
        "Division": "moku",
        "Hen": "hen",
        "Shou": "shou",
        "Setsu": "setsu",
        "Kan": "kan",
        "Moku": "moku",
    }
    for child in elem:
        if child.tag == "Article":
            extracted = _extract_article(child, parent_stack)
            if extracted is not None:  # None = skipped (e.g., range article)
                results.append(extracted)
        elif child.tag in structural:
            kind = structural[child.tag]
            num = get_int_attribute(child, "Num", default=len(parent_stack) + 1)
            title_tag = child.find(f"{child.tag}Title")
            name = (extract_all_text(title_tag) or "").strip()
            results.extend(_walk_articles(child, [*parent_stack, (kind, num, name)]))
        else:
            results.extend(_walk_articles(child, parent_stack))
    return results


def _extract_article(art, parent_stack):
    """Extract a single <Article> element to a structured dict.

    Raises:
        ValueError: If <Article Num="..."> is missing/empty.
    """
    # Normalize e-Gov's branch-article notation: e-Gov uses '105_2' for
    # 刑法第105条の2 (Article 105-2 / branch article), but JuriCode-JP IR
    # spec uses hyphen separator ('105-2'). This is a notation difference,
    # not a semantic one. CLAUDE.md §3.1 example explicitly says "36-2".
    num = (art.get("Num") or "").strip().replace("_", "-")
    if not num:
        raise ValueError("<Article> element missing or empty 'Num' attribute")

    # Skip range articles (e.g. Num="73:76" meaning "Articles 73 through 76").
    # e-Gov uses colon notation when a contiguous block of articles is deleted
    # (e.g. 刑法73~76条 大逆罪削除). The body is just "削除" and they don't
    # represent any single article — including them would force an arbitrary
    # numbering choice and confuse downstream consumers.
    if ":" in num:
        return None  # caller filters None

    caption = extract_all_text(art.find("ArticleCaption")).strip() or None
    title = extract_all_text(art.find("ArticleTitle")).strip()

    paragraphs = []
    for i, para in enumerate(art.findall("Paragraph"), start=1):
        p_num = get_int_attribute(para, "Num", default=i)
        sents = para.findall(".//ParagraphSentence/Sentence")
        if not sents:
            sents = para.findall(".//Sentence")
        ptext = "".join(extract_all_text(s) for s in sents).strip()
        if not ptext:
            warnings.warn(
                f"Article {num} paragraph {p_num}: empty text after extraction.",
                RuntimeWarning,
                stacklevel=2,
            )
        paragraphs.append({"number": p_num, "text": ptext})

    if not paragraphs:
        warnings.warn(
            f"Article {num}: no <Paragraph> elements found.",
            RuntimeWarning,
            stacklevel=2,
        )

    parent = {}
    for kind, n, name in parent_stack:
        parent[kind] = n
        parent[f"{kind}_name_ja"] = name
    return {
        "number": num,
        "caption": caption,
        "title": title,
        "paragraphs": paragraphs,
        "parent_section": parent if parent else None,
    }


def _int_to_kansuji(n):
    """1-99 to kansuji, else digits. 0 returns '〇'."""
    if n == 0:
        return "〇"
    if 1 <= n <= 10:
        return KANSUJI[n]
    if 11 <= n <= 19:
        return "十" + KANSUJI[n - 10]
    if 20 <= n <= 99:
        t, o = divmod(n, 10)
        return KANSUJI[t] + "十" + (KANSUJI[o] if o else "")
    return str(n)


def article_to_markdown(article, law_id, law_abbrev, law_name_ja, version_date):
    """Build (filename, markdown_text) for one article.

    Output Markdown layout:
        ---
        <frontmatter YAML>
        ---

        # <law_name_ja> 第<N>条(<caption>)

        ## 原文 (日本語)

        ### 第N条 (or 第N条第M項)

        <paragraph text>
    """
    art_num = article["number"]
    article_id = f"{law_abbrev}-art-{art_num}"
    filename = f"{law_abbrev}-article-{art_num}.md"

    body = []
    title = f"# {law_name_ja} 第{art_num}条"
    if article["caption"]:
        title += f"({article['caption'].strip('()')})"
    body.append(title)
    body.append("")
    body.append("## 原文 (日本語)")
    body.append("")
    multi = len(article["paragraphs"]) > 1
    for p in article["paragraphs"]:
        head_base = article["title"] or f"第{art_num}条"
        if multi:
            heading = f"### {head_base}第{_int_to_kansuji(p['number'])}項"
        else:
            heading = f"### {head_base}"
        body.append(heading)
        body.append("")
        body.append(p["text"])
        body.append("")
    while body and body[-1] == "":
        body.pop()
    md_body = "\n".join(body) + "\n"

    fm = {
        "law_id": law_id,
        "law_name_ja": law_name_ja,
        "law_name_en": LAW_NAME_EN.get(law_id, "(English name pending)"),
        "article_number": str(art_num),
        "article_id": article_id,
        "version_date": version_date.isoformat(),
        "source_url": f"https://laws.e-gov.go.jp/law/{law_id}",
        "source_format": "e-gov-xml",
        "last_verified": date.today().isoformat(),
        "license": "MIT",
        "translation_status": "none",
        "machine_translated": False,
        "paragraphs": [
            {
                "number": p["number"],
                "has_proviso": False,
                "has_items": False,
                "is_added_by_amendment": False,
            }
            for p in article["paragraphs"]
        ],
        "cases": [],
        "amendments": [],
        "tags": ["phase1-police", "auto-generated"],
    }
    if article.get("parent_section"):
        fm["parent_section"] = article["parent_section"]

    yaml_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=1000)
    return filename, f"---\n{yaml_text}---\n\n{md_body}"


def extract_canonical_text(article):
    """Canonical Japanese text for hash verification."""
    return canonicalize("\n\n".join(p["text"] for p in article["paragraphs"]))


def _infer_law_id(abbrev):
    """Look up law_id by abbreviation via fetch-egov map. Returns None if unknown."""
    try:
        sys.path.insert(
            0,
            str(Path(__file__).parent.parent / "fetch-egov" / "src"),
        )
        from fetch_egov.law_id_map import LAW_ID_MAP

        return LAW_ID_MAP.get(abbrev)
    except Exception:
        return None


def _validate_abbrev(abbrev):
    """Validate `abbrev` is safe to use in filenames and paths.

    Raises:
        ValueError: If abbrev contains characters that could escape the
            target directory or violate naming rules.
    """
    if not ABBREV_PATTERN.fullmatch(abbrev):
        raise ValueError(
            f"--abbrev {abbrev!r} not safe. Must match {ABBREV_PATTERN.pattern} "
            f"(lowercase, digits, hyphen; starts with a letter)."
        )


def _resolve_version_date(args_version_date, parsed_promulgation):
    """Resolve version_date with explicit fallback order.

    Raises:
        ValueError: Neither source is available, or args date malformed.
    """
    if args_version_date:
        return date.fromisoformat(args_version_date)
    if parsed_promulgation:
        return parsed_promulgation
    raise ValueError("--version-date required (could not infer from XML)")


def _emit_article(article, law_id, law_abbrev, law_name_ja, version_date, output_dir, force):
    """Write one article Markdown to disk, return manifest entry dict."""
    filename, md_text = article_to_markdown(
        article,
        law_id=law_id,
        law_abbrev=law_abbrev,
        law_name_ja=law_name_ja,
        version_date=version_date,
    )
    out_path = output_dir / filename
    if out_path.exists() and not force:
        print(f"SKIP existing: {out_path}", file=sys.stderr)
    else:
        out_path.write_text(md_text, encoding="utf-8")
        print(f"WROTE {out_path}", file=sys.stderr)

    canon = extract_canonical_text(article)
    ja_sha = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return {
        "article_id": f"{law_abbrev}-art-{article['number']}",
        "article_number": str(article["number"]),
        "filename": filename,
        "ja_text_sha256": ja_sha,
        "ja_text_bytes": len(canon.encode("utf-8")),
        "paragraph_count": len(article["paragraphs"]),
    }


def _build_manifest(
    law_id, law_name_ja, law_abbrev, xml_path, xml_text, xml_sha, version_date, article_entries
):
    """Assemble the _source-manifest.json payload. Side-effect free."""
    return {
        "schema_version": "1.0",
        "law_id": law_id,
        "law_name_ja": law_name_ja,
        "law_abbrev": law_abbrev,
        "source_url": f"https://laws.e-gov.go.jp/api/2/law_data/{law_id}",
        "source_xml_path": str(xml_path),
        "source_xml_sha256": xml_sha,
        "source_xml_bytes": len(xml_text.encode("utf-8")),
        "source_fetched_at": date.today().isoformat(),
        "parser": "tools/parse/parse-egov.py",
        "parser_version": PARSER_VERSION,
        "parsed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "version_date": version_date.isoformat(),
        "article_count": len(article_entries),
        "articles": article_entries,
    }


def _build_argparser():
    """Construct the CLI argument parser."""
    ap = argparse.ArgumentParser(
        description="e-Gov XML to JuriCode-JP Markdown + verification manifest"
    )
    ap.add_argument("--input", type=Path, required=True, help="e-Gov XML file path")
    ap.add_argument("--output", type=Path, required=True, help="Output directory")
    ap.add_argument(
        "--abbrev",
        type=str,
        required=True,
        help="Law abbreviation (lowercase a-z 0-9 -, max 64 chars)",
    )
    ap.add_argument("--law-id", type=str, default=None)
    ap.add_argument("--version-date", type=str, default=None)
    ap.add_argument("--force", action="store_true")
    return ap


def main():
    """CLI driver. Returns process exit code."""
    args = _build_argparser().parse_args()

    try:
        _validate_abbrev(args.abbrev)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 1
    try:
        xml_text = args.input.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"ERROR: failed to read {args.input}: {e}", file=sys.stderr)
        return 1
    xml_sha = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()

    try:
        parsed = parse_egov_xml(xml_text)
    except (ET.ParseError, ValueError) as e:
        print(f"ERROR: XML parse failed: {e}", file=sys.stderr)
        return 1

    law_id = args.law_id or _infer_law_id(args.abbrev)
    if not law_id:
        print("ERROR: cannot determine law_id; pass --law-id", file=sys.stderr)
        return 1

    try:
        version_date = _resolve_version_date(args.version_date, parsed["promulgation"])
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    args.output.mkdir(parents=True, exist_ok=True)

    article_entries = []
    for article in parsed["articles"]:
        entry = _emit_article(
            article,
            law_id=law_id,
            law_abbrev=args.abbrev,
            law_name_ja=parsed["law_name_ja"],
            version_date=version_date,
            output_dir=args.output,
            force=args.force,
        )
        article_entries.append(entry)

    manifest = _build_manifest(
        law_id=law_id,
        law_name_ja=parsed["law_name_ja"],
        law_abbrev=args.abbrev,
        xml_path=args.input,
        xml_text=xml_text,
        xml_sha=xml_sha,
        version_date=version_date,
        article_entries=article_entries,
    )
    manifest_path = args.output / "_source-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"WROTE {manifest_path} ({len(article_entries)} article(s))", file=sys.stderr)
    print(
        f"OK: {len(article_entries)} article(s). "
        f"Run verify.py to confirm hashes. "
        f"(XML guard: {'defusedxml' if _USING_DEFUSEDXML else 'stdlib (unsafe!)'})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

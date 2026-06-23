#!/usr/bin/env python3
"""verify.py -- JuriCode-JP データ検証 (Layer 3).

`data/` 配下を走査し, `_source-manifest.json` ごとに以下を確認する:

  1. マニフェスト記載の各 .md が存在する
  2. .md 本文 SHA-256 を再計算しマニフェストの ja_text_sha256 と一致する
  3. .md frontmatter の article_number / article_id が一致する
  4. 法令ディレクトリ内の .md 数 = マニフェストの article_count
  5. マニフェストの schema が合っている

設計: docs/verification-framework.md (Layer 3)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pyyaml not installed. Run: pip install pyyaml")

sys.path.insert(0, str(Path(__file__).parent))
from _canonicalize import canonicalize

# 表の GFM 区切り行除外は table_core に一本化し canonical_hash.py と共有する
# (案C・FU-515 E-4)。table_core は tools/parse/v0.2/ にある。
_V02_DIR = Path(__file__).resolve().parent / "v0.2"
if str(_V02_DIR) not in sys.path:
    sys.path.insert(0, str(_V02_DIR))
from table_core import is_gfm_separator_line  # noqa: E402

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
JA_SECTION_RE = re.compile(
    r"##\s*原文\s*\(?日本語\)?\s*\n(.*?)(?=\n##\s|\Z)",
    re.DOTALL,
)
PARAGRAPH_HEADING_RE = re.compile(
    r"^###\s+第[一二三四五六七八九十百千0-9]+条"
    # Allow 0 or more branch suffixes like "の二", "の三", "の二の三"
    # (e.g. 刑法第三条の二, 刑法第二十六条の二の二)
    r"(?:の[一二三四五六七八九十百千0-9]+)*"
    # Optional paragraph number "第X項"
    r"(?:第([一二三四五六七八九十百千0-9]+)項)?\s*$",
    re.MULTILINE,
)

REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "law_id",
    "law_name_ja",
    "law_abbrev",
    "source_xml_sha256",
    "article_count",
    "articles",
)
REQUIRED_ARTICLE_MANIFEST_FIELDS = (
    "article_id",
    "article_number",
    "filename",
    "ja_text_sha256",
)

# Security: filename entries must be plain filenames with no traversal.
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")


def _is_safe_filename(name: str) -> bool:
    """Return True iff `name` is a plain filename with no path components."""
    if not name or ".." in name or "/" in name or "\\" in name:
        return False
    return bool(SAFE_FILENAME_RE.fullmatch(name))


@dataclass
class CheckResult:
    """Per-article verification result."""

    manifest_path: Path
    article_id: str
    filename: str
    passed: bool
    messages: list = field(default_factory=list)


def extract_ja_paragraphs_from_md(md_text):
    """Extract canonical Japanese paragraph texts from a generated Markdown."""
    m = JA_SECTION_RE.search(md_text)
    if not m:
        return []
    body = m.group(1).strip()
    headings = list(PARAGRAPH_HEADING_RE.finditer(body))
    if not headings:
        return [body.strip()] if body.strip() else []
    texts = []
    for i, h in enumerate(headings):
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        chunk = body[start:end]
        lines = chunk.splitlines()
        # 案C (FU-515 E-4): GFM 表の区切り行 (| --- |) は描画用装飾なので hash から除外。
        # canonical_hash.py と同一処理 (table_core 共有)。
        lines = [ln for ln in lines if not is_gfm_separator_line(ln)]
        while lines and (not lines[-1].strip() or set(lines[-1].strip()) <= {"-"}):
            lines.pop()
        text = "\n".join(lines).strip()
        if text:
            texts.append(text)
    return texts


def parse_frontmatter(md_text):
    """Return (frontmatter_dict, body_text). Raises ValueError if absent."""
    m = FRONTMATTER_RE.match(md_text)
    if not m:
        raise ValueError("missing YAML frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    return fm, m.group(2)


def verify_one_article(manifest_entry, md_path, manifest_path):
    """Verify a single Markdown article against its manifest entry.

    Security: re-validates manifest_entry['filename'] to prevent path traversal.
    """
    result = CheckResult(
        manifest_path=manifest_path,
        article_id=manifest_entry.get("article_id", "<?>"),
        filename=manifest_entry.get("filename", "<?>"),
        passed=True,
    )

    fname = manifest_entry.get("filename", "")
    if not _is_safe_filename(fname):
        result.passed = False
        result.messages.append(f"UNSAFE FILENAME in manifest: {fname!r}")
        return result

    if not md_path.exists():
        result.passed = False
        result.messages.append(f"FILE MISSING: {md_path}")
        return result

    try:
        md_text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        result.passed = False
        result.messages.append(f"FILE READ ERROR: {e}")
        return result

    try:
        fm, _body = parse_frontmatter(md_text)
    except ValueError as e:
        result.passed = False
        result.messages.append(f"FRONTMATTER PARSE: {e}")
        return result

    if not isinstance(fm, dict):
        result.passed = False
        result.messages.append(f"FRONTMATTER not a mapping (got {type(fm).__name__})")
        return result

    expected_id = manifest_entry["article_id"]
    actual_id = fm.get("article_id")
    if actual_id != expected_id:
        result.passed = False
        result.messages.append(
            f"article_id MISMATCH: frontmatter={actual_id!r}, manifest={expected_id!r}"
        )

    expected_num = str(manifest_entry["article_number"])
    actual_num = str(fm.get("article_number", ""))
    if actual_num != expected_num:
        result.passed = False
        result.messages.append(
            f"article_number MISMATCH: frontmatter={actual_num!r}, manifest={expected_num!r}"
        )

    paragraphs = extract_ja_paragraphs_from_md(md_text)
    canonical = canonicalize("\n\n".join(paragraphs))
    actual_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    expected_sha = manifest_entry["ja_text_sha256"]
    if actual_sha != expected_sha:
        result.passed = False
        result.messages.append(
            f"ja_text_sha256 MISMATCH:\n"
            f"  expected (manifest): {expected_sha}\n"
            f"  actual   (markdown): {actual_sha}\n"
            f"  -> 本文が改変された可能性. 再生成するか revert してください."
        )

    pc_manifest = manifest_entry.get("paragraph_count")
    if pc_manifest is not None:
        pc_md = len(paragraphs)
        if pc_md != pc_manifest:
            result.passed = False
            result.messages.append(
                f"paragraph_count MISMATCH: manifest={pc_manifest}, markdown extracted={pc_md}"
            )

    return result


def verify_manifest(manifest_path):
    """Verify one `_source-manifest.json` and all its articles."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return [
            CheckResult(
                manifest_path=manifest_path,
                article_id="<MANIFEST>",
                filename="-",
                passed=False,
                messages=[f"MANIFEST PARSE ERROR: {e}"],
            )
        ]
    if not isinstance(manifest, dict):
        return [
            CheckResult(
                manifest_path=manifest_path,
                article_id="<MANIFEST>",
                filename="-",
                passed=False,
                messages=[f"MANIFEST is not a JSON object (got {type(manifest).__name__})"],
            )
        ]

    missing = [f for f in REQUIRED_MANIFEST_FIELDS if f not in manifest]
    schema_errs = []
    if missing:
        schema_errs.append(f"MANIFEST missing required fields: {missing}")
    for art in manifest.get("articles", []):
        miss_a = [f for f in REQUIRED_ARTICLE_MANIFEST_FIELDS if f not in art]
        if miss_a:
            schema_errs.append(f"MANIFEST article {art.get('article_id', '?')} missing: {miss_a}")
    if schema_errs:
        return [
            CheckResult(
                manifest_path=manifest_path,
                article_id="<MANIFEST>",
                filename="-",
                passed=False,
                messages=schema_errs,
            )
        ]

    dir_ = manifest_path.parent
    md_files_on_disk = sorted(p.name for p in dir_.glob("*-article-*.md"))
    expected_files = sorted(a["filename"] for a in manifest["articles"])
    count_msgs = []
    extra = set(md_files_on_disk) - set(expected_files)
    if extra:
        count_msgs.append(f"UNTRACKED .md files in {dir_}: {sorted(extra)}")

    results = []
    for art in manifest["articles"]:
        results.append(verify_one_article(art, dir_ / art["filename"], manifest_path))

    if count_msgs:
        results.append(
            CheckResult(
                manifest_path=manifest_path,
                article_id="<COUNT>",
                filename="-",
                passed=False,
                messages=count_msgs,
            )
        )
    return results


def find_manifests(root):
    """Return sorted list of `_source-manifest.json` paths under `root`."""
    return sorted(root.rglob("_source-manifest.json"))


def _build_argparser():
    """Construct the CLI argument parser."""
    ap = argparse.ArgumentParser(description="JuriCode-JP data verifier (Layer 3)")
    ap.add_argument("--path", type=Path, default=Path("data"), help="検索対象ディレクトリ")
    ap.add_argument("--strict", action="store_true", help="マニフェストが無い場合も fail")
    ap.add_argument("--json", dest="as_json", action="store_true", help="JSON 出力")
    return ap


def _emit_text_report(all_results, manifests_count):
    """Print human-readable verification results."""
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    for r in all_results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.manifest_path.parent.name}/{r.filename} ({r.article_id})")
        for m in r.messages:
            for line in m.splitlines():
                print(f"       {line}")
    print()
    print(f"=== Summary: {passed} passed, {failed} failed across {manifests_count} manifest(s) ===")


def _emit_json_report(all_results, manifests_count):
    """Print machine-readable JSON verification results."""
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    out = {
        "summary": {"passed": passed, "failed": failed, "manifests": manifests_count},
        "results": [
            {
                "manifest": str(r.manifest_path),
                "article_id": r.article_id,
                "filename": r.filename,
                "passed": r.passed,
                "messages": r.messages,
            }
            for r in all_results
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main():
    """CLI driver. Returns 0 (PASS) / 1 (FAIL) / 2 (setup error)."""
    args = _build_argparser().parse_args()

    if not args.path.exists():
        print(f"ERROR: path not found: {args.path}", file=sys.stderr)
        return 2

    manifests = find_manifests(args.path)
    if not manifests:
        msg = f"No _source-manifest.json found under {args.path}"
        if args.strict:
            print(f"ERROR: {msg}", file=sys.stderr)
            return 2
        print(f"WARN: {msg}", file=sys.stderr)
        return 0

    all_results = []
    for mp in manifests:
        all_results.extend(verify_manifest(mp))

    if args.as_json:
        _emit_json_report(all_results, len(manifests))
    else:
        _emit_text_report(all_results, len(manifests))

    failed = sum(1 for r in all_results if not r.passed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Pydantic IR から JSON Schema を自動生成して schema/ に出力する.

Usage:
    python tools/shared/scripts/export-schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent.parent.parent
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared.ir import JuriCodeArticle, TaxAnswerChunk  # noqa: E402


def _write_schema(schema: dict, output_path: Path) -> None:
    """Write JSON Schema to file with LF line endings (P4b: CRLF 根絶)."""
    # newline="\n" forces LF on all platforms (including Windows)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
        f.write("\n")


def export_article_schema(output_dir: Path) -> Path:
    """JuriCodeArticle の JSON Schema を出力する."""
    schema = JuriCodeArticle.model_json_schema(
        mode="validation",
        ref_template="#/$defs/{model}",
    )

    original_desc = schema.get("description") or ""

    ordered: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/JuriCode-JP/JuriCode-JP/schema/juricode-article.schema.json",
        "title": "JuriCode-JP Article (IR-derived canonical schema)",
        "description": (
            "Auto-generated JSON Schema from Pydantic IR "
            "(juricode_shared.ir.JuriCodeArticle). "
            "This is the canonical schema for v0.1 onwards. "
            "Edit the Pydantic models in tools/shared/src/juricode_shared/ir.py "
            "instead of this file. "
            f"Original IR description: {original_desc}"
        ),
    }
    for k, v in schema.items():
        if k not in ordered:
            ordered[k] = v

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "juricode-article.schema.json"
    _write_schema(ordered, output_path)
    return output_path


def export_taxanswer_schema(output_dir: Path) -> Path:
    """TaxAnswerChunk の JSON Schema を出力する (R3: article schema とは別ファイル)."""
    schema = TaxAnswerChunk.model_json_schema(
        mode="validation",
        ref_template="#/$defs/{model}",
    )

    original_desc = schema.get("description") or ""

    ordered: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/JuriCode-JP/JuriCode-JP/schema/juricode-taxanswer.schema.json",
        "title": "JuriCode-JP TaxAnswer Chunk (IR-derived canonical schema)",
        "description": (
            "Auto-generated JSON Schema from Pydantic IR "
            "(juricode_shared.ir.TaxAnswerChunk). "
            "Covers NTA TaxAnswer (タックスアンサー) semantic fields only. "
            "Pipeline fields (segment_type / article_id / law_name_ja / text) are "
            "excluded from this schema and merged post-dump by the parser. "
            "Edit the Pydantic models in tools/shared/src/juricode_shared/ir.py "
            "instead of this file. "
            f"Original IR description: {original_desc}"
        ),
    }
    for k, v in schema.items():
        if k not in ordered:
            ordered[k] = v

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "juricode-taxanswer.schema.json"
    _write_schema(ordered, output_path)
    return output_path


def main() -> int:
    schema_dir = _REPO_ROOT / "schema"

    article_path = export_article_schema(schema_dir)
    rel_article = article_path.relative_to(_REPO_ROOT)
    print(f"Exported: {rel_article}")
    print(f"Size: {article_path.stat().st_size:,} bytes")

    taxanswer_path = export_taxanswer_schema(schema_dir)
    rel_taxanswer = taxanswer_path.relative_to(_REPO_ROOT)
    print(f"Exported: {rel_taxanswer}")
    print(f"Size: {taxanswer_path.stat().st_size:,} bytes")

    return 0


if __name__ == "__main__":
    sys.exit(main())

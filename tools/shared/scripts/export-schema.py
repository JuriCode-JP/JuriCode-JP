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

from juricode_shared.ir import JuriCodeArticle  # noqa: E402


def export_schema(output_dir: Path) -> Path:
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

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return output_path


def main() -> int:
    schema_dir = _REPO_ROOT / "schema"
    output_path = export_schema(schema_dir)
    rel = output_path.relative_to(_REPO_ROOT)
    print(f"Exported: {rel}")
    print(f"Size: {output_path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

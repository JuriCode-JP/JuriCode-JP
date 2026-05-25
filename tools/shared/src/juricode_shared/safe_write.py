"""safe_write.py — Safety-guaranteed file writing utility.

Provides functions to prevent corruption (e.g. NUL byte injection, missing newlines,
half-written files, or invalid JSON Lines) through atomic writes and post-write validation.

FU-302 implementation:
  - safe_write_text: atomic write via tempfile, NUL and trailing newline validation, UTF-8 safety.
  - safe_write_jsonl: serializes records, validates loads, and writes atomically.
  - safe_append_jsonl_records: reads existing jsonl, appends records, validates entire dataset, and overwrites atomically.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def safe_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text atomically to disk with NUL byte and newline validations.

    Asserts:
      - Content has no NUL bytes (\\0).
      - Content ends with a trailing newline (\\n) (if not empty).
      - Atomic replacement: writes to a .tmp file, verifies read-back, then renames.
    """
    # Validation checks
    assert "\0" not in content, f"NUL byte detected in content for {path}"
    if content:
        assert content.endswith("\n"), f"Missing trailing newline in content for {path}"

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write via tempfile in the same directory (to ensure same partition for rename)
    dir_path = path.parent
    fd, temp_path_str = tempfile.mkstemp(dir=dir_path, prefix=path.name + ".", suffix=".tmp")
    temp_path = Path(temp_path_str)

    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)

        # Verification check: read back and verify
        verified_content = temp_path.read_text(encoding=encoding)
        assert verified_content == content, (
            f"Verification failed for written content at {temp_path}"
        )

        # Atomic replace
        os.replace(temp_path, path)
    except Exception as e:
        # Clean up temp file on failure
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise e


def safe_write_jsonl(path: Path, records: list[dict], encoding: str = "utf-8") -> None:
    """Serialize records to JSON Lines format, validate each, and write atomically."""
    lines = []
    for idx, record in enumerate(records):
        try:
            line = json.dumps(record, ensure_ascii=False)
            # Verify serialization is loadable
            json.loads(line)
            lines.append(line + "\n")
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to serialize/validate JSON record at index {idx}: {e}")

    content = "".join(lines)
    safe_write_text(path, content, encoding=encoding)


def safe_append_jsonl_records(path: Path, new_records: list[dict], encoding: str = "utf-8") -> None:
    """Read existing jsonl records, append new records, validate all, and rewrite atomically.

    If file does not exist, behaves like safe_write_jsonl.
    """
    records = []
    if path.exists():
        with path.open("r", encoding=encoding) as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Corrupt JSON line found in existing file {path} at line {line_no}: {e}"
                    )

    records.extend(new_records)
    safe_write_jsonl(path, records, encoding=encoding)

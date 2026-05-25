"""Tests for safe_write (FU-302).

Why this test exists:
    The 5 known accidents (a) WSL ruff /mnt/c/ corruption, (b) Edit/Write NUL byte
    padding, (c) cat heredoc duplicate paste, (d) bulk-ingest phase tag drift,
    (g) 4,810 empty chunks bug — all share the same failure mode: a parser writes
    a file that is silently broken (NUL bytes, missing trailing newline, invalid
    JSONL line, or partial write from a crash).

    safe_write_text / safe_write_jsonl / safe_append_jsonl_records are the
    safety net. These tests pin their assertions so that regressions cannot
    re-introduce the failure modes.

    Coverage targets:
      - NUL byte rejection (text + jsonl)
      - Trailing newline enforcement (text)
      - Atomic write: original file is preserved on assertion failure
      - JSONL: each record validates as json.loads-able after json.dumps
      - JSONL append: existing corrupt file is detected, not silently extended
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from juricode_shared.safe_write import (
    safe_append_jsonl_records,
    safe_write_jsonl,
    safe_write_text,
)


# ===========================================================
# safe_write_text — happy path
# ===========================================================


def test_text_writes_simple_content(tmp_path: Path) -> None:
    p = tmp_path / "hello.md"
    safe_write_text(p, "hello world\n")
    assert p.read_text(encoding="utf-8") == "hello world\n"


def test_text_writes_japanese_content(tmp_path: Path) -> None:
    p = tmp_path / "keihou.md"
    safe_write_text(p, "第三十六条 急迫不正の侵害\n")
    assert p.read_text(encoding="utf-8") == "第三十六条 急迫不正の侵害\n"


def test_text_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b" / "c.md"
    safe_write_text(p, "nested\n")
    assert p.exists()
    assert p.read_text(encoding="utf-8") == "nested\n"


def test_text_empty_content_allowed(tmp_path: Path) -> None:
    """Empty content skips the trailing-newline assert (no body to terminate)."""
    p = tmp_path / "empty.md"
    safe_write_text(p, "")
    assert p.read_text(encoding="utf-8") == ""


# ===========================================================
# safe_write_text — failure modes
# ===========================================================


def test_text_rejects_nul_byte(tmp_path: Path) -> None:
    """Accident (b): Edit/Write NUL byte padding must be caught."""
    p = tmp_path / "corrupt.md"
    with pytest.raises(AssertionError, match="NUL byte"):
        safe_write_text(p, "hello\0world\n")
    assert not p.exists(), "no file should be left behind on assertion failure"


def test_text_rejects_missing_trailing_newline(tmp_path: Path) -> None:
    """Accident (c): cat heredoc duplicate paste often loses the final \\n."""
    p = tmp_path / "no-newline.md"
    with pytest.raises(AssertionError, match="trailing newline"):
        safe_write_text(p, "no newline at end")
    assert not p.exists()


def test_text_preserves_original_on_assertion_failure(tmp_path: Path) -> None:
    """If we already have a good file and the new write fails validation,
    the old file must remain intact (atomic-write contract)."""
    p = tmp_path / "exists.md"
    safe_write_text(p, "good content\n")

    with pytest.raises(AssertionError):
        safe_write_text(p, "bad\0content\n")

    # Original content survives
    assert p.read_text(encoding="utf-8") == "good content\n"


def test_text_overwrites_existing_atomically(tmp_path: Path) -> None:
    p = tmp_path / "swap.md"
    safe_write_text(p, "v1\n")
    safe_write_text(p, "v2\n")
    assert p.read_text(encoding="utf-8") == "v2\n"


def test_text_does_not_leak_tmp_files_on_failure(tmp_path: Path) -> None:
    """A failed safe_write_text must not leave .tmp siblings around."""
    p = tmp_path / "doomed.md"
    with pytest.raises(AssertionError):
        safe_write_text(p, "x\0y\n")

    # No siblings beginning with the target name should remain
    siblings = [
        f for f in tmp_path.iterdir() if f.name.startswith(p.name + ".") and f.name.endswith(".tmp")
    ]
    assert siblings == [], f"orphan .tmp files left behind: {siblings}"


# ===========================================================
# safe_write_jsonl — happy path
# ===========================================================


def test_jsonl_writes_records(tmp_path: Path) -> None:
    p = tmp_path / "chunks.jsonl"
    records = [
        {"chunk_id": "art-1-p1", "text": "本文"},
        {"chunk_id": "art-1-p2", "text": "続き"},
    ]
    safe_write_jsonl(p, records)

    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == records[0]
    assert json.loads(lines[1]) == records[1]


def test_jsonl_writes_empty_list(tmp_path: Path) -> None:
    """Empty record list → empty file (degenerate but legal)."""
    p = tmp_path / "empty.jsonl"
    safe_write_jsonl(p, [])
    assert p.read_text(encoding="utf-8") == ""


def test_jsonl_preserves_non_ascii(tmp_path: Path) -> None:
    """ensure_ascii=False must be honored (法令文字は ASCII 外)."""
    p = tmp_path / "ja.jsonl"
    records = [{"text": "第三十六条 急迫不正の侵害"}]
    safe_write_jsonl(p, records)

    raw = p.read_text(encoding="utf-8")
    assert "急迫不正" in raw, "Japanese characters must be preserved unescaped"


# ===========================================================
# safe_write_jsonl — failure modes
# ===========================================================


def test_jsonl_rejects_non_serializable_record(tmp_path: Path) -> None:
    """A record that can't be JSON-serialized must abort, not write a partial file."""
    p = tmp_path / "fail.jsonl"

    class _Opaque:
        pass

    with pytest.raises(ValueError, match="Failed to serialize"):
        safe_write_jsonl(p, [{"ok": 1}, {"bad": _Opaque()}])
    assert not p.exists(), "no partial JSONL should remain"


# ===========================================================
# safe_append_jsonl_records — happy path + edge cases
# ===========================================================


def test_append_creates_new_file(tmp_path: Path) -> None:
    p = tmp_path / "new.jsonl"
    safe_append_jsonl_records(p, [{"a": 1}])
    assert json.loads(p.read_text(encoding="utf-8").strip()) == {"a": 1}


def test_append_extends_existing(tmp_path: Path) -> None:
    p = tmp_path / "extend.jsonl"
    safe_write_jsonl(p, [{"a": 1}])
    safe_append_jsonl_records(p, [{"b": 2}, {"c": 3}])

    lines = p.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"a": 1},
        {"b": 2},
        {"c": 3},
    ]


def test_append_detects_corrupt_existing_file(tmp_path: Path) -> None:
    """If the existing file already has an invalid JSON line, refuse to extend it.

    This protects against accident (g): 4,810 empty chunks were appended onto
    corrupted files for hours before anyone noticed.
    """
    p = tmp_path / "corrupt.jsonl"
    p.write_text("{not valid json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt JSON line"):
        safe_append_jsonl_records(p, [{"new": "record"}])


def test_append_skips_blank_lines_in_existing(tmp_path: Path) -> None:
    """Blank lines in JSONL files are legal (trailing newline / formatting)."""
    p = tmp_path / "blank.jsonl"
    p.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")

    safe_append_jsonl_records(p, [{"c": 3}])

    lines = p.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines if line.strip()] == [
        {"a": 1},
        {"b": 2},
        {"c": 3},
    ]

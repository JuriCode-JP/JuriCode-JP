"""canonical_hash -- v0.2 .md -> canonical 日本語本文 -> SHA-256 + バイト数.

責務 (バイブコーディング 3 原則 #1):
  本 module は「.md ファイル 1 つから (sha256_hex, byte_count, paragraph_count)
  を返す」純粋関数だけを提供。Pydantic モデル化や CLI 引数 parse は範囲外。

Why このロジックは verify.py から複製しているのか:
  manifest 生成時 (本 module) と verify 時 (tools/parse/verify.py) が
  **同じ canonical text と同じ hash** を計算する必要がある (一致しないと
  CI が常に FAIL する)。

  最も clean な解は (a) verify.py の `extract_ja_paragraphs_from_md` /
  `JA_SECTION_RE` / `PARAGRAPH_HEADING_RE` を `juricode_shared` に移し、
  両者で import する、だが本 sprint のスコープ外 (FU-405 で別途)。

  代替として本 module で**ロジック完全同期 (regex 文字列含む)**を維持する。
  unit test `test_canonical_hash.py::test_matches_verify_py_output` で
  verify.py の実装と同じ hash が出ることを保証する。

関連:
  - tools/parse/verify.py:33-46 (JA_SECTION_RE / PARAGRAPH_HEADING_RE)
  - tools/parse/verify.py:86-106 (extract_ja_paragraphs_from_md)
  - tools/parse/_canonicalize.py (canonicalize 関数、これは既に共有済)
  - FU-405 (P1): markdown_regex を juricode_shared に統一する将来 task
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

# tools/parse/_canonicalize.py を共有モジュールとして import する。
# parse-egov.py / verify.py と同じ sys.path 操作 pattern (両 module の冒頭参照)。
_PARSE_DIR = Path(__file__).resolve().parent.parent.parent
if str(_PARSE_DIR) not in sys.path:
    sys.path.insert(0, str(_PARSE_DIR))

from _canonicalize import canonicalize  # noqa: E402  (must follow sys.path tweak)

# ---------------------------------------------------------------------
# Regex 定義 -- verify.py:33-46 と**文字列レベルで完全一致**を維持すること.
# 1 文字違うと hash が変わって CI が落ちる. FU-405 で shared 化予定.
# ---------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
"""Frontmatter デリミタ抽出 (verify.py:33 と一致)."""

_JA_SECTION_RE = re.compile(
    r"##\s*原文\s*\(?日本語\)?\s*\n(.*?)(?=\n##\s|\Z)",
    re.DOTALL,
)
"""「## 原文 (日本語)」セクション本文の抽出 (verify.py:34-37 と一致)."""

_PARAGRAPH_HEADING_RE = re.compile(
    r"^###\s+第[一二三四五六七八九十百千0-9]+条"
    # Allow 0 or more branch suffixes like "の二", "の三", "の二の三"
    # (e.g. 刑法第三条の二, 刑法第二十六条の二の二)
    r"(?:の[一二三四五六七八九十百千0-9]+)*"
    # Optional paragraph number "第X項"
    r"(?:第([一二三四五六七八九十百千0-9]+)項)?\s*$",
    re.MULTILINE,
)
"""項見出し (verify.py:38-46 と一致). 枝番条 + 項番号付きにも対応."""


def extract_ja_paragraphs(md_text: str) -> list[str]:
    """v0.2 .md 全文から canonical Japanese paragraph texts を抽出.

    Args:
        md_text: .md ファイルの全文 (frontmatter + body).

    Returns:
        各項 (paragraph) のテキストを保持する list. 「## 原文 (日本語)」
        セクションが見つからない場合は空 list. 見出し `### 第N条第K項`
        の数だけ要素が返る (見出し無しの場合は body 全体を 1 要素として返す).

    Why この戻り値の形:
        verify.py:86-106 の `extract_ja_paragraphs_from_md` と**完全に同じ
        出力**を返す必要がある (hash 一致のため). 戻り値の list を
        `"\\n\\n".join(...)` で結合してから canonicalize+SHA-256 すると、
        verify.py が再計算する hash と必ず一致する.
    """
    m = _JA_SECTION_RE.search(md_text)
    if not m:
        return []
    body = m.group(1).strip()
    headings = list(_PARAGRAPH_HEADING_RE.finditer(body))
    if not headings:
        return [body.strip()] if body.strip() else []
    texts = []
    for i, h in enumerate(headings):
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        chunk = body[start:end]
        lines = chunk.splitlines()
        # verify.py と同じく、末尾の空行・ハイフン区切り (---) を削る
        while lines and (not lines[-1].strip() or set(lines[-1].strip()) <= {"-"}):
            lines.pop()
        text = "\n".join(lines).strip()
        if text:
            texts.append(text)
    return texts


def compute_ja_text_hash(md_path: Path) -> tuple[str, int, int]:
    """v0.2 .md の canonical 日本語本文の SHA-256 + バイト数 + 段落数.

    Args:
        md_path: v0.2 corpus 配下の .md ファイル絶対パス.

    Returns:
        (sha256_hex, ja_text_bytes, paragraph_count) のタプル.
        sha256_hex は小文字 64 文字、ja_text_bytes は canonical UTF-8 バイト数、
        paragraph_count は extract_ja_paragraphs() 戻り値の長さ.

    Raises:
        FileNotFoundError: md_path が存在しない.
        ValueError: 「## 原文 (日本語)」セクションが見つからない、
                    または paragraph_count == 0.

    Why paragraph_count を返すか:
        verify.py の manifest schema は `paragraph_count` を optional field
        として持っており、parse-egov.py:_emit_article は常に出力している.
        本 module も同じ値を計算しておくことで manifest schema を完全互換に
        できる. 段落数 0 を `ValueError` 化するのは、v0.2 corpus が必ず
        1 つ以上の `### 第N条` 見出しを持つ前提に基づく.

    Example:
        >>> from pathlib import Path
        >>> sha, byte_count, n = compute_ja_text_hash(Path("data/v0.2/.../minpou-article-1.md"))
        >>> len(sha) == 64 and byte_count > 0 and n >= 1
        True
    """
    if not md_path.exists():
        raise FileNotFoundError(f"md_path not found: {md_path}")

    try:
        md_text = md_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{md_path}: invalid UTF-8 encoding: {e}") from e

    paragraphs = extract_ja_paragraphs(md_text)
    if not paragraphs:
        raise ValueError(
            f"{md_path}: 「## 原文 (日本語)」セクションが見つからない、"
            "または本文が空 (v0.2 corpus は必ず 1 つ以上の項を含む前提)"
        )

    # verify.py:177 と同じ結合 + canonicalize 順序
    canonical = canonicalize("\n\n".join(paragraphs))
    canonical_bytes = canonical.encode("utf-8")
    sha256_hex = hashlib.sha256(canonical_bytes).hexdigest()
    return sha256_hex, len(canonical_bytes), len(paragraphs)

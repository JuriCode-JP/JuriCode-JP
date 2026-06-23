"""Tests for manifest/canonical_hash.py.

Coverage targets:
  - happy path: 1 段落 / 複数段落の hash + byte_count + paragraph_count
  - 「## 原文 (日本語)」セクション無し → ValueError
  - frontmatter のみで body 無し → ValueError
  - 段落見出し無し (body 全体を 1 段落扱い) → 1 個返る
  - file 不在 → FileNotFoundError
  - 非 UTF-8 → ValueError
  - 異常な引数 → 適切な例外
  - **重要**: verify.py が同じ .md に対して同じ hash を出す (互換性 test)
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

# manifest パッケージを import 可能にする (parent dir = tools/parse/v0.2/)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from manifest.canonical_hash import (  # noqa: E402
    compute_ja_text_hash,
    extract_ja_paragraphs,
)

# canonicalize 一致性 test 用に verify.py 側のロジックも import
# (sys.path に tools/parse/ を追加).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


# ============================================================
# extract_ja_paragraphs — 純関数 test (file I/O 不要)
# ============================================================


def test_extract_single_paragraph() -> None:
    """単項 (見出し無し) は本文全体を 1 要素として返す."""
    md = (
        "---\nfoo: bar\n---\n\n"
        "# 民法 第90条\n\n"
        "## 原文 (日本語)\n\n"
        "公の秩序又は善良の風俗に反する法律行為は、無効とする。\n"
    )
    paragraphs = extract_ja_paragraphs(md)
    assert paragraphs == ["公の秩序又は善良の風俗に反する法律行為は、無効とする。"]


def test_extract_multiple_paragraphs() -> None:
    """項見出しが複数あるとき、各項を分離して返す."""
    md = (
        "---\nx: 1\n---\n\n"
        "# 民法 第770条\n\n"
        "## 原文 (日本語)\n\n"
        "### 第七百七十条第一項\n\n"
        "夫婦の一方は、次に掲げる場合に限り、離婚の訴えを提起することができる。\n\n"
        "### 第七百七十条第二項\n\n"
        "裁判所は、前項各号の事由があっても、棄却することができる。\n"
    )
    paragraphs = extract_ja_paragraphs(md)
    assert len(paragraphs) == 2
    assert "夫婦の一方は" in paragraphs[0]
    assert "裁判所は" in paragraphs[1]


def test_extract_handles_branch_article_heading() -> None:
    """枝番条 (第N条のM) の項見出しも認識する."""
    md = "---\n---\n\n## 原文 (日本語)\n\n### 第三条の二第一項\n\n枝番条の本文.\n"
    paragraphs = extract_ja_paragraphs(md)
    assert paragraphs == ["枝番条の本文."]


def test_extract_returns_empty_when_no_ja_section() -> None:
    """「## 原文 (日本語)」セクション無し → 空 list."""
    md = "---\n---\n\n# Title\n\n## English Translation\n\nfoo\n"
    assert extract_ja_paragraphs(md) == []


def test_extract_stops_at_next_h2() -> None:
    """「## 原文 (日本語)」の次の H2 で打ち切る (英訳セクション混入防止)."""
    md = (
        "---\n---\n\n"
        "## 原文 (日本語)\n\n"
        "日本語本文.\n\n"
        "## English Translation\n\n"
        "English text (should NOT be included).\n"
    )
    paragraphs = extract_ja_paragraphs(md)
    assert paragraphs == ["日本語本文."]
    assert "English" not in "".join(paragraphs)


def test_extract_strips_trailing_horizontal_rule() -> None:
    """末尾の `---` 区切り行は paragraph に含めない (verify.py の挙動と一致)."""
    md = "---\n---\n\n## 原文 (日本語)\n\n### 第一条\n\n本文.\n\n---\n"
    paragraphs = extract_ja_paragraphs(md)
    assert paragraphs == ["本文."]


# ============================================================
# 案C (FU-515 E-4): 表の GFM 区切り行除外 + 隔離 + 後方互換
# ============================================================

_TABLE_MD = (
    "---\n---\n\n## 原文 (日本語)\n\n"
    "### 第一条\n\n"
    "次の表のとおりとする。\n\n"
    "| 区分 | 税率 |\n"
    "| --- | --- |\n"
    "| 一 | 五万円 |\n"
    "| 二 | 十二万円 |\n"
)


def test_gfm_separator_excluded_from_paragraph() -> None:
    """GFM 区切り行 (| --- |) は hash 対象テキストから除外される (案C・§3.5.7)."""
    (para,) = extract_ja_paragraphs(_TABLE_MD)
    assert "| --- |" not in para
    # データ行・導入文・ヘッダ行は保持される
    assert "次の表のとおりとする。" in para
    assert "| 区分 | 税率 |" in para
    assert "| 一 | 五万円 |" in para
    assert "| 二 | 十二万円 |" in para


def test_separator_does_not_affect_hash() -> None:
    """区切り行の有無で hash が変わらない (markdown 外見への非依存)."""
    md_without_sep = _TABLE_MD.replace("| --- | --- |\n", "")
    a = extract_ja_paragraphs(_TABLE_MD)
    b = extract_ja_paragraphs(md_without_sep)
    assert a == b


def test_data_rows_still_affect_hash() -> None:
    """データセルが変われば抽出テキストは変わる (改変検知は生きている)."""
    md2 = _TABLE_MD.replace("五万円", "六万円")
    assert extract_ja_paragraphs(_TABLE_MD) != extract_ja_paragraphs(md2)


def test_isolation_dash_cells_preserved() -> None:
    """隔離 (Bug10): 全角ダッシュ ― / ASCII - を含むデータセルは除去されない."""
    md = (
        "---\n---\n\n## 原文 (日本語)\n\n### 第一条\n\n"
        "次の表。\n\n"
        "| 甲 | 乙 |\n"
        "| --- | --- |\n"
        "| ― | 二百円 |\n"
        "| - | 四百円 |\n"
    )
    (para,) = extract_ja_paragraphs(md)
    assert "| ― | 二百円 |" in para  # 全角ダッシュ行は保持
    assert "| - | 四百円 |" in para  # ASCII ダッシュ"セル"も pipe 行なので保持
    assert "| --- |" not in para  # 区切り行のみ除外


def test_table_less_paragraph_unchanged_backward_compat() -> None:
    """表を持たない条文の抽出テキストは案C 導入で不変 (後方互換)."""
    md = (
        "---\n---\n\n## 原文 (日本語)\n\n"
        "### 第一条第一項\n\n本文 A。\n\n"
        "### 第一条第二項\n\n本文 B。\n"
    )
    assert extract_ja_paragraphs(md) == ["本文 A。", "本文 B。"]


# ============================================================
# compute_ja_text_hash — file 経由 test
# ============================================================


def _write_md(tmp_path: Path, name: str, body: str) -> Path:
    """テスト用 .md ファイル書出しヘルパ."""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_compute_returns_64_char_hex_sha256(tmp_path: Path) -> None:
    """SHA-256 hex は小文字 64 文字."""
    md = _write_md(
        tmp_path,
        "test-article-1.md",
        "---\n---\n\n## 原文 (日本語)\n\n### 第一条\n\nテスト本文.\n",
    )
    sha, byte_count, n = compute_ja_text_hash(md)
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)
    assert byte_count > 0
    assert n == 1


def test_compute_deterministic_across_runs(tmp_path: Path) -> None:
    """同じ .md は常に同じ hash."""
    md = _write_md(
        tmp_path,
        "test-article-1.md",
        "---\n---\n\n## 原文 (日本語)\n\n### 第一条\n\nテスト.\n",
    )
    sha1, _, _ = compute_ja_text_hash(md)
    sha2, _, _ = compute_ja_text_hash(md)
    assert sha1 == sha2


def test_compute_changes_when_body_changes(tmp_path: Path) -> None:
    """本文が変わると hash が変わる (改変検知)."""
    md1 = _write_md(
        tmp_path,
        "a.md",
        "---\n---\n\n## 原文 (日本語)\n\n### 第一条\n\nテスト A.\n",
    )
    md2 = _write_md(
        tmp_path,
        "b.md",
        "---\n---\n\n## 原文 (日本語)\n\n### 第一条\n\nテスト B.\n",
    )
    sha_a, _, _ = compute_ja_text_hash(md1)
    sha_b, _, _ = compute_ja_text_hash(md2)
    assert sha_a != sha_b


def test_compute_paragraph_count_matches_headings(tmp_path: Path) -> None:
    """項見出し数 = paragraph_count."""
    body = (
        "---\n---\n\n## 原文 (日本語)\n\n"
        "### 第一条第一項\n\nP1.\n\n"
        "### 第一条第二項\n\nP2.\n\n"
        "### 第一条第三項\n\nP3.\n"
    )
    md = _write_md(tmp_path, "test.md", body)
    _, _, n = compute_ja_text_hash(md)
    assert n == 3


def test_compute_raises_on_missing_file(tmp_path: Path) -> None:
    """存在しないファイル → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        compute_ja_text_hash(tmp_path / "does-not-exist.md")


def test_compute_raises_on_missing_ja_section(tmp_path: Path) -> None:
    """「## 原文 (日本語)」セクション無し → ValueError."""
    md = _write_md(
        tmp_path,
        "no-ja.md",
        "---\n---\n\n# Title\n\n## English Translation\n\nfoo\n",
    )
    with pytest.raises(ValueError, match="「## 原文 \\(日本語\\)」セクションが見つからない"):
        compute_ja_text_hash(md)


def test_compute_raises_on_empty_ja_body(tmp_path: Path) -> None:
    """本文だけ空 → ValueError."""
    md = _write_md(
        tmp_path,
        "empty.md",
        "---\n---\n\n## 原文 (日本語)\n\n",
    )
    with pytest.raises(ValueError):
        compute_ja_text_hash(md)


# ============================================================
# 互換性 test: verify.py との hash 一致
# ============================================================


def test_hash_matches_verify_py_algorithm(tmp_path: Path) -> None:
    """compute_ja_text_hash が verify.py の hash 計算 (canonicalize +
    SHA-256) と完全一致することを確認.

    Why このテストは critical か:
        本 module は verify.py から logic を **複製** しており、ドリフトすると
        CI が永久に FAIL する. このテストが落ちたら直ちに修正必要.
    """
    # verify.py が import するモジュールと同じ canonicalize を import
    from _canonicalize import canonicalize

    body = (
        "---\n---\n\n## 原文 (日本語)\n\n"
        "### 第七百七十条第一項\n\n夫婦の一方は離婚を提起できる。\n\n"
        "### 第七百七十条第二項\n\n棄却できる。\n"
    )
    md_path = _write_md(tmp_path, "minpou-article-770.md", body)

    # 本 module の hash
    actual_sha, _, _ = compute_ja_text_hash(md_path)

    # verify.py のロジックを inline で再実装 (verify.py:86-106 のコピー)
    paragraphs = extract_ja_paragraphs(md_path.read_text(encoding="utf-8"))
    expected_canon = canonicalize("\n\n".join(paragraphs))
    expected_sha = hashlib.sha256(expected_canon.encode("utf-8")).hexdigest()

    assert actual_sha == expected_sha, (
        f"hash mismatch: actual={actual_sha}, expected={expected_sha}. "
        "canonical_hash.py が verify.py の hash 計算とドリフトしている. "
        "regex 文字列または canonicalize の挙動を点検すること."
    )


def test_table_extraction_identical_to_verify_py() -> None:
    """表を含む md で canonical_hash.extract_ja_paragraphs と
    verify.py.extract_ja_paragraphs_from_md が **同一 list** を返す (文字列レベル一致).

    Why critical: 案C (E-4) で両者に同じ区切り行除外を入れた. 片方だけ更新すると
    表を持つ条文の round-trip が永久に赤くなる.
    """
    from verify import extract_ja_paragraphs_from_md

    a = extract_ja_paragraphs(_TABLE_MD)
    b = extract_ja_paragraphs_from_md(_TABLE_MD)
    assert a == b, "canonical_hash と verify.py の表抽出がドリフトしている"

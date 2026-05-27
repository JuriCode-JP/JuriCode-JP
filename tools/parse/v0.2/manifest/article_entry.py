"""article_entry -- 1 条分の Pydantic ArticleEntry モデル + 生成関数.

責務 (バイブコーディング 3 原則 #1):
  「v0.2 .md ファイル 1 つ」と「frontmatter dict」から ArticleEntry Pydantic
  モデルを 1 つ作る純関数だけ. CLI / 全 law_dir 走査 / I/O 連鎖は範囲外.

Why 厳格な型 (Pydantic + extra="forbid"):
  manifest entry の field 名がドリフトすると verify.py との互換が壊れる
  (CI が永遠に green を返さなくなる).
  Pydantic v2 `extra="forbid"` + 正規表現 pattern で「不正な値」「typo」を
  build 時に弾く. 同じ思想は juricode_shared.ir.JuriCodeArticle と一貫.

参照する verify.py の制約:
  - tools/parse/verify.py:57-62 (REQUIRED_ARTICLE_MANIFEST_FIELDS)
    article_id / article_number / filename / ja_text_sha256 が必須
  - tools/parse/verify.py:65 (SAFE_FILENAME_RE)
    filename は path traversal 防御の正規表現 pattern を通る必要あり

関連:
  - tools/parse/parse-egov.py:435-442 (_emit_article 戻り値、v0.1 の範型)
  - tools/shared/src/juricode_shared/ir.py (JuriCodeArticle、Pydantic pattern の参考)
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .canonical_hash import compute_ja_text_hash

# verify.py:65 の SAFE_FILENAME_RE と一致する pattern.
# Why: manifest entry の filename は verify.py 側で path traversal 検査される.
# 本 module でも build 時点で同じ pattern を強制し、early fail を実現する.
_SAFE_FILENAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$"

# verify.py:55-62 (REQUIRED_ARTICLE_MANIFEST_FIELDS) と一致する基本構造.
# 加えて article_id / article_number の format も IR spec に合わせる.
_ARTICLE_ID_PATTERN = r"^[a-z][a-z0-9-]*-art-[a-z0-9]+(-[a-z0-9]+)*$"
"""article_id pattern: '{law_abbrev}-art-{N}' or '{law_abbrev}-art-{N}-{branch}'.
   FU-101 (P2) で附則対応のため [a-z0-9] に緩和済の最新 spec を採用."""

_ARTICLE_NUMBER_PATTERN = r"^[0-9]+(-[0-9]+)*$"
"""article_number pattern: '36' or '36-2' (枝番条). CLAUDE.md §3.3 と一致."""

_SHA256_HEX_PATTERN = r"^[a-f0-9]{64}$"


class ArticleEntry(BaseModel):
    """1 条分の manifest entry. verify.py の REQUIRED_ARTICLE_MANIFEST_FIELDS と互換.

    Why frozen=True:
      manifest は「parse 結果のスナップショット」であり、生成後に mutate
      されるべきでない. Pydantic v2 の frozen=True で immutability を保証.

    Why extra="forbid":
      schema 拡張時の typo (`article_idx:` 等) を build 時に弾く.
      FU-308 / IR モデルと一貫した防御策.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    article_id: str = Field(
        pattern=_ARTICLE_ID_PATTERN,
        description="条文の一意 ID. '{law_abbrev}-art-{N}' 形式.",
    )
    article_number: str = Field(
        pattern=_ARTICLE_NUMBER_PATTERN,
        description="条番号. '36' or '36-2' (枝番条).",
    )
    filename: str = Field(
        pattern=_SAFE_FILENAME_PATTERN,
        description=".md ファイル名 (path traversal 防御済). 拡張子 .md を含む.",
    )
    ja_text_sha256: str = Field(
        pattern=_SHA256_HEX_PATTERN,
        description="canonical 日本語本文の SHA-256 hex (小文字 64 文字).",
    )
    ja_text_bytes: int = Field(
        ge=0,
        description="canonical 日本語本文の UTF-8 バイト数.",
    )
    paragraph_count: int = Field(
        ge=1,
        description="extract_ja_paragraphs() が返す段落数. 必ず 1 以上.",
    )


def build_article_entry(
    md_path: Path,
    expected_law_abbrev: str | None = None,
) -> ArticleEntry:
    """v0.2 .md ファイルから ArticleEntry を構築.

    Args:
        md_path: v0.2 corpus 配下の .md ファイル絶対パス.
        expected_law_abbrev: 指定時、md_path のファイル名がこの abbrev で
            始まるかを検証 ('{abbrev}-article-*.md'). path traversal を更に防御.
            None なら検証スキップ.

    Returns:
        構築済 ArticleEntry (frozen).

    Raises:
        FileNotFoundError: md_path 不在.
        ValueError: 本文セクション無し / 段落 0 / frontmatter 不在 /
                    article_id が patterns に違反 / law_abbrev 不一致.

    Why frontmatter から article_id / article_number を読むのか:
        ファイル名 (e.g. 'minpou-article-770.md') からも article_id / number
        は推測可能だが、frontmatter から読む方が「ファイル名と中身の不一致」
        を build 時に検出できる (verify.py の article_id MISMATCH 事前検出).

    Example:
        >>> from pathlib import Path
        >>> entry = build_article_entry(Path("data/v0.2/.../minpou-article-770.md"))
        >>> entry.article_id
        'minpou-art-770'
        >>> entry.article_number
        '770'
    """
    if not md_path.exists():
        raise FileNotFoundError(f"md_path not found: {md_path}")

    md_text = md_path.read_text(encoding="utf-8")

    # frontmatter 読出し. juricode_shared.frontmatter を import するのが本筋だが、
    # ここでは依存を最小化するため inline で簡易 parse (yaml.safe_load で十分).
    # Why: juricode_shared を import すると sys.path 操作が増え、tests の起動
    # コストが上がる. canonical_hash と article_entry は manifest 内部完結が望ましい.
    import yaml

    if not md_text.startswith("---\n"):
        raise ValueError(f"{md_path}: missing frontmatter opening delimiter")
    end_idx = md_text.find("\n---\n", 4)
    if end_idx < 0:
        raise ValueError(f"{md_path}: missing frontmatter closing delimiter")
    fm_yaml = md_text[4:end_idx]
    try:
        fm = yaml.safe_load(fm_yaml) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{md_path}: frontmatter YAML parse error: {e}") from e

    if not isinstance(fm, dict):
        raise ValueError(f"{md_path}: frontmatter is not a mapping (got {type(fm).__name__})")

    article_id = fm.get("article_id")
    article_number = fm.get("article_number")
    if not article_id or not article_number:
        raise ValueError(
            f"{md_path}: frontmatter missing required field "
            f"(article_id={article_id!r}, article_number={article_number!r})"
        )

    # law_abbrev 一致検証 (任意).
    # ファイル名は '{abbrev}-article-{N}.md' 規約 (CLAUDE.md §3.1).
    if expected_law_abbrev is not None:
        expected_prefix = f"{expected_law_abbrev}-article-"
        if not md_path.name.startswith(expected_prefix):
            raise ValueError(
                f"{md_path}: filename does not start with expected "
                f"prefix {expected_prefix!r} (law_abbrev mismatch)"
            )

    sha256_hex, ja_text_bytes, paragraph_count = compute_ja_text_hash(md_path)

    return ArticleEntry(
        article_id=article_id,
        article_number=str(article_number),  # YAML は '36' を str/int 両方で読む可能性
        filename=md_path.name,
        ja_text_sha256=sha256_hex,
        ja_text_bytes=ja_text_bytes,
        paragraph_count=paragraph_count,
    )

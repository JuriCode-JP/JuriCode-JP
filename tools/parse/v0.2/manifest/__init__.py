"""manifest -- v0.2 corpus 用 _source-manifest.json 生成パッケージ.

責務分離 (バイブコーディング 3 原則):
  - canonical_hash: v0.2 .md -> canonical 日本語本文 -> SHA-256 + バイト数
  - article_entry:  1 条分の Pydantic ArticleEntry モデル + 生成関数
  - law_manifest:   1 法令分の Pydantic LawManifest モデル + assembly + write
  - cli:            argparse + 全 law_dir 走査 + main()

設計の Why:
  v0.2 corpus (data/v0.2/) は segment_parser.py により v0.1 から派生したが、
  parse-egov.py の `_build_manifest` が data/phase1-*/ にのみ manifest を
  生成しており、data/v0.2/ には _source-manifest.json が 0 件だった。これにより
  GitHub Actions CI の `verify.py --path data` は v0.2 corpus を silently skip
  しており、嘘の frontmatter (has_proviso/has_items 全 false) を毎回通していた。

  本パッケージは v0.1 互換 schema (verify.py の REQUIRED_MANIFEST_FIELDS と
  REQUIRED_ARTICLE_MANIFEST_FIELDS) で 44 manifests を生成し、CI を v0.2
  corpus に切替える前提を整える。

Why ディレクトリ名 (`tools/parse/v0.2/manifest/`):
  親 `v0.2` のドットにより `tools.parse.v0.2.manifest` 形式の import はできない
  (Python module パスでドットは module separator として予約)。本パッケージは
  filesystem path で参照され、テストや CLI からは sys.path に
  `tools/parse/v0.2/` を追加して `from manifest import ...` で import する。
  これは隣接モジュール (segment_parser.py / extract_kou_from_xml.py /
  extract_supplproviso_from_xml.py / add_rollup_chunks.py) と同じ pattern。

関連:
  - business/v02-corpus-quality-investigation-2026-05-25.md (sprint 設計)
  - tools/parse/parse-egov.py (v0.1 parser、_build_manifest が範型)
  - tools/parse/verify.py (round-trip 検証側、schema 互換が必須)
  - FU-405: PARAGRAPH_HEADING_RE / 漢数字変換を shared 化 (将来統合予定)
"""

from __future__ import annotations

from .article_entry import ArticleEntry, build_article_entry
from .canonical_hash import compute_ja_text_hash, extract_ja_paragraphs
from .law_manifest import LawManifest, assemble_law_manifest, write_law_manifest

__all__ = [
    "ArticleEntry",
    "LawManifest",
    "assemble_law_manifest",
    "build_article_entry",
    "compute_ja_text_hash",
    "extract_ja_paragraphs",
    "write_law_manifest",
]

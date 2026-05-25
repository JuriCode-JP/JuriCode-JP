"""law_manifest — 1 法令分の Pydantic LawManifest モデル + assembly + write.

責務 (バイブコーディング 3 原則 #1):
  「1 つの law_dir (e.g. data/v0.2/phase1-practitioner/minpou/) 配下の全 .md」と
  「対応する e-Gov XML cache path」から LawManifest を組み立てて write する.
  全 phase 走査や CLI 引数 parse は cli.py に分離.

Why 厳格な型 (Pydantic + extra="forbid"):
  verify.py:48-56 (REQUIRED_MANIFEST_FIELDS) との互換が破れると CI が
  永久に FAIL する. v0.1 schema_version="1.0" と完全一致させる.

参照する verify.py の制約:
  - verify.py:48-56 REQUIRED_MANIFEST_FIELDS
    schema_version / law_id / law_name_ja / law_abbrev / source_xml_sha256 /
    article_count / articles が必須
  - verify.py:65 SAFE_FILENAME_RE
    filename field は path traversal 防御済 (ArticleEntry 側で validate)
  - verify.py:246-251 (article_count vs disk files の照合)

XML 不在時の挙動 (Why WARN + 空 hash):
  data/v0.2/{phase}/{law}/ に .md があるが cache/laws/{law_id}.xml が
  ない場合がある (XML を取得せず、コミュニティ contributor が手動で書いた条文等).
  この場合 source_xml_sha256 を空にして WARN を出すと、後で XML 取得し直したとき
  に manifest 再生成すれば自動で埋まる. ERROR にしないのは、Phase 1 投入完了後
  に source XML を消すケース (ライセンス再確認等) も想定するため.
"""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from datetime import date, datetime

# Python 3.11+ exports `datetime.UTC`. Cowork sandbox uses 3.10 which lacks it.
# CI runs 3.11/3.12 where the direct import works. Backport keeps both happy.
try:
    from datetime import UTC
except ImportError:  # pragma: no cover (3.10 sandbox only)
    from datetime import timezone as _tz

    UTC = _tz.utc  # noqa: UP017  (3.10 fallback; ruff can't see the try branch above)
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .article_entry import ArticleEntry, build_article_entry

# juricode_shared.safe_write を import (FU-302、atomic write 必須).
# Why: manifest が壊れると verify.py の本文改変検知が無効化される.
_SHARED_SRC = Path(__file__).resolve().parents[3] / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import safe_write_text  # noqa: E402  (must follow sys.path tweak)

# ---------------------------------------------------------------------
# Constants — verify.py の SAFE/required と一致させる
# ---------------------------------------------------------------------

_PARSER_NAME = "tools/parse/v0.2/segment_parser.py"
"""v0.2 corpus を生成した parser. parse-egov.py:54 の PARSER_VERSION と
   思想統一: 「現在の corpus は誰が・どの version で作ったか」を manifest に
   ハードコーディングする (verify.py 側では使わないが、人間レビュー用)."""

_LAW_ABBREV_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
"""tools/parse/parse-egov.py:57 の ABBREV_PATTERN と一致 (path traversal 防御)."""

_LAW_ID_PATTERN = r"^[A-Z0-9_]+$"
"""e-Gov 法令 ID format (e.g. '129AC0000000089'). FU-105 (P2) で厳格化予定."""

_SHA256_HEX_PATTERN = r"^[a-f0-9]{64}$"
_EMPTY_OR_SHA256_PATTERN = r"^([a-f0-9]{64}|)$"  # XML 不在時は空文字列許容


class LawManifest(BaseModel):
    """1 法令分の _source-manifest.json. v0.1 schema_version=1.0 と互換.

    Field 順序は parse-egov.py:_build_manifest の出力と意図的に合わせている
    (人間が diff したとき視認しやすい).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(
        default="1.0",
        pattern=r"^1\.[0-9]+$",
        description="manifest schema version. v0.1 互換のため 1.0 系を維持.",
    )
    law_id: str = Field(
        pattern=_LAW_ID_PATTERN,
        description="e-Gov 法令 ID (e.g. '129AC0000000089').",
    )
    law_name_ja: str = Field(
        min_length=1,
        description="法令名 (日本語、正式名称).",
    )
    law_abbrev: str = Field(
        pattern=_LAW_ABBREV_PATTERN,
        description="法令略称 (ローマ字、CLAUDE.md §3.1 glossary 準拠).",
    )
    source_url: str = Field(
        description="e-Gov API URL (https://laws.e-gov.go.jp/api/2/law_data/{law_id}).",
    )
    source_xml_path: str = Field(
        description="ローカル cache の XML path (e.g. 'cache/laws/{law_id}.xml').",
    )
    source_xml_sha256: str = Field(
        pattern=_EMPTY_OR_SHA256_PATTERN,
        description="XML の SHA-256 hex. XML 不在時は空文字列 (WARN 出力).",
    )
    source_xml_bytes: int = Field(
        ge=0,
        description="XML の UTF-8 バイト数. XML 不在時は 0.",
    )
    source_fetched_at: str = Field(
        description="manifest 生成時の日付 (ISO 8601 date).",
    )
    parser: str = Field(
        description="corpus を生成した parser (path-like string).",
    )
    parser_version: str = Field(
        min_length=1,
        description="parser のバージョン文字列 (e.g. 'tools/parse/v0.2/segment_parser.py@0.1.0').",
    )
    parsed_at: str = Field(
        description="manifest 生成時の datetime (ISO 8601 UTC).",
    )
    version_date: str = Field(
        description="法令の現行条文施行日 (ISO 8601 date).",
    )
    article_count: int = Field(
        ge=0,
        description="manifest に含まれる条文数 (= len(articles)).",
    )
    articles: list[ArticleEntry] = Field(
        description="条文 entry の list. 順序は filename の string sort.",
    )


def _compute_xml_sha256(xml_path: Path) -> tuple[str, int]:
    """XML ファイルの SHA-256 hex + バイト数を計算.

    Returns:
        (sha256_hex, byte_count). XML 不在時は ('', 0) を返し WARN を出す.

    Why WARN にする (raise しない):
        コミュニティ contributor が XML 無しで .md を手書きするケースを許容するため.
        この場合 source_xml_sha256 は空欄になるが、本文 hash (ja_text_sha256) は
        ArticleEntry 側で計算済なので round-trip 検証は機能する.
    """
    if not xml_path.exists():
        warnings.warn(
            f"XML cache not found: {xml_path}. "
            "source_xml_sha256 will be empty. "
            "Re-run after `tools/fetch-egov/bulk-ingest.py` to populate.",
            RuntimeWarning,
            stacklevel=2,
        )
        return "", 0

    xml_bytes = xml_path.read_bytes()
    return hashlib.sha256(xml_bytes).hexdigest(), len(xml_bytes)


def _detect_law_metadata(law_dir: Path) -> tuple[str, str, str, str]:
    """law_dir 配下の最初の .md から (law_id, law_name_ja, law_abbrev, version_date) を読む.

    Why 最初の .md から読むのか:
        v0.2 corpus は 1 つの法令ディレクトリ内で全 .md が同じ
        law_id / law_name_ja / law_abbrev / version_date を持つ前提
        (parse-egov.py が各条で同じ値を frontmatter に書く). 1 件読めば十分.

        Phase 2.5 self-review 観点 #2 (エッジケース): 後続 .md で値が不一致だった
        場合は ValueError. これは extract_kou_from_xml.py の
        build_law_abbrev_to_id_phase と同じ pattern.

    Returns:
        (law_id, law_name_ja, law_abbrev, version_date_iso).

    Raises:
        FileNotFoundError: law_dir に .md が 1 件も無い.
        ValueError: frontmatter から必須 field が読めない.
    """
    import yaml

    mds = sorted(law_dir.glob("*-article-*.md"))
    if not mds:
        raise FileNotFoundError(f"No '*-article-*.md' files in {law_dir}")

    first = mds[0]
    text = first.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{first}: missing frontmatter opening delimiter")
    end_idx = text.find("\n---\n", 4)
    if end_idx < 0:
        raise ValueError(f"{first}: missing frontmatter closing delimiter")
    fm = yaml.safe_load(text[4:end_idx]) or {}
    if not isinstance(fm, dict):
        raise ValueError(f"{first}: frontmatter is not a mapping")

    required = ("law_id", "law_name_ja", "version_date")
    missing = [k for k in required if not fm.get(k)]
    if missing:
        raise ValueError(f"{first}: frontmatter missing required fields: {missing}")

    # law_abbrev は frontmatter には無く、article_id から導出 ({abbrev}-art-{N}).
    article_id = fm.get("article_id", "")
    if "-art-" not in article_id:
        raise ValueError(f"{first}: article_id missing '-art-' separator: {article_id!r}")
    law_abbrev = article_id.rsplit("-art-", 1)[0]

    version_date = fm["version_date"]
    if isinstance(version_date, date):
        version_date = version_date.isoformat()
    else:
        version_date = str(version_date)

    return fm["law_id"], fm["law_name_ja"], law_abbrev, version_date


def assemble_law_manifest(
    law_dir: Path,
    xml_path: Path,
    parser_version: str,
) -> LawManifest:
    """law_dir 配下の全 .md と xml_path から LawManifest を組み立てる.

    Args:
        law_dir: v0.2 法令ディレクトリ (e.g. data/v0.2/phase1-practitioner/minpou/).
        xml_path: 対応する e-Gov XML cache path (e.g. cache/laws/{law_id}.xml).
            存在しなくても WARN のみで処理続行 (_compute_xml_sha256 参照).
        parser_version: corpus を生成した parser のバージョン文字列.

    Returns:
        構築済 LawManifest (frozen).

    Raises:
        FileNotFoundError: law_dir に .md が 0 件.
        ValueError: 重複 article_id が検出された、または law metadata 読出し失敗.

    Why 重複 article_id をエラー化するのか:
        同じ article_id を持つ 2 ファイルが law_dir に居ると、verify.py 側で
        どちらの .md を hash 照合対象とするか定まらない (silently どちらか
        無視される). build 時に弾く方が事故が早く露見する.
    """
    law_id, law_name_ja, law_abbrev, version_date = _detect_law_metadata(law_dir)
    xml_sha, xml_bytes = _compute_xml_sha256(xml_path)

    entries: list[ArticleEntry] = []
    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()

    for md_path in sorted(law_dir.glob("*-article-*.md")):
        entry = build_article_entry(md_path, expected_law_abbrev=law_abbrev)
        if entry.article_id in seen_ids:
            raise ValueError(
                f"Duplicate article_id in {law_dir}: {entry.article_id!r} (file: {md_path.name})"
            )
        if entry.filename in seen_filenames:
            raise ValueError(f"Duplicate filename in {law_dir}: {entry.filename!r}")
        seen_ids.add(entry.article_id)
        seen_filenames.add(entry.filename)
        entries.append(entry)

    return LawManifest(
        law_id=law_id,
        law_name_ja=law_name_ja,
        law_abbrev=law_abbrev,
        source_url=f"https://laws.e-gov.go.jp/api/2/law_data/{law_id}",
        source_xml_path=str(xml_path),
        source_xml_sha256=xml_sha,
        source_xml_bytes=xml_bytes,
        source_fetched_at=date.today().isoformat(),
        parser=_PARSER_NAME,
        parser_version=parser_version,
        parsed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        version_date=version_date,
        article_count=len(entries),
        articles=entries,
    )


def write_law_manifest(manifest: LawManifest, output_path: Path) -> None:
    """LawManifest を _source-manifest.json として atomic write.

    Args:
        manifest: 書き出す manifest.
        output_path: 通常 `{law_dir}/_source-manifest.json`.

    Why safe_write_text:
        FU-302 で全 parser に atomic write 必須化. manifest 破損で verify.py
        が機能停止すると本文改変検知が無効化されるため、特に重要.

    Why mode='json' + indent=2:
        parse-egov.py:566-569 と同じ format. Diff 可読性 + GitHub での
        review しやすさ.
    """
    data = manifest.model_dump(mode="json")
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    safe_write_text(output_path, text)

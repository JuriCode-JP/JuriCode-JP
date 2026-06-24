#!/usr/bin/env python3
"""parse-nta-tsutatsu.py -- NTA HTML tsutatsu (circular) -> Directive JSONL chunks.

Usage:
    python tools/parse/parse-nta-tsutatsu.py \\
        --circular hojin \\
        --cache-dir cache/tsutatsu/hojin/09 \\
        --output-dir build/chunks/hojin-kihon-tsutatsu \\
        --chapter 09

The circular's law_name / NTA URL base / reference-prefix map come from its
CircularConfig (selected by --circular); law_abbrev is derived from that config.

Output: build/chunks/hojin-kihon-tsutatsu/hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl

One record per directive item (e.g. 9-2-9).
Each record has:
    id              : "hojin-kihon-tsutatsu-9-2-9"  (directive_id)
    directive_id    : same as id
    law_name_ja     : "法人税基本通達"
    law_abbrev      : "hojin-kihon-tsutatsu"
    chapter_section : "9-2" (chapter-section prefix)
    directive_number: "9-2-9"
    title           : "(債務の免除による利益その他の経済的な利益)"
    text            : full body text (Markdown, items as list)
    amendment_note  : raw amendment string e.g. "(平19年課法2-3...)"
    related_articles: list of {law_abbrev, article_id, article_number, raw}
    source_url      : "https://www.nta.go.jp/law/tsutatsu/kihon/hojin/09/09_02_02.htm"
    license         : "public-domain-13-2"
    segment_type    : "tsutatsu"
    article_id      : None  (for retrieve.py compatibility)
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")

# juricode_shared を import 可能にする (DirectiveChunk による出力検証用)。
# 取込ループは main() の sys.path patch より前に走るため module レベルで patch する
# (parse-nta-taxanswer.py と同パターン)。
_SHARED_SRC = Path(__file__).resolve().parents[1] / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LICENSE = "public-domain-13-2"


# ---------------------------------------------------------------------------
# Per-circular config (法人税 / 消費税 ... を 1 セレクタで切替・Bug37 回避)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CircularConfig:
    """1 通達分の取込パラメータ (法人税固定の解消・FU-514 後段)。

    Why: parser ロジックは通達非依存だが、通達名・NTA URL ベース・参照接頭辞マップ
    だけが通達ごとに違う。これらをコード内 config 定数として束ね `--circular` で
    選択する (CLI に dict を渡さない=デシリアライズ不要で型不整合 Bug を構造的に回避)。
    ref_map は必須フィールド (mutable default を持たせない)。corpus 未登録の参照先は
    corpus_unregistered に列挙し unlinked として扱う。
    """

    law_name_ja: str
    law_abbrev: str
    source_url_base: str
    ref_map: Mapping[str, str]  # {"法": <law>, "令": <shikkourei>, "規": <shikoukisoku>, ...}
    corpus_unregistered: frozenset[str] = field(default_factory=frozenset)
    license: str = LICENSE
    # 本文末尾の改正注記を抽出する NTA 内部記号 (法人税="課法" / 消費税="課消")。
    # 「（<元号><年>課<部門><番号>…）」形式。通達ごとに部門記号が違うため config 化。
    amendment_marker: str = "課法"


# 法人税基本通達 (既定・byte 回帰で固定。値は移行前の module 定数と完全一致)。
HOJIN_CONFIG = CircularConfig(
    law_name_ja="法人税基本通達",
    law_abbrev="hojin-kihon-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kihon/hojin",
    ref_map={
        "法": "houjin-zei-hou",
        "令": "houjin-zei-hou-shikkourei",
        "規": "houjin-zei-hou-shikoukisoku",
        "措法": "sochi-hou",  # corpus 未収録 -> warn, no link
    },
    corpus_unregistered=frozenset({"sochi-hou"}),
)

# 消費税法基本通達。source_url_base の NTA パスは "shohi" (実 URL で確認済・我々の
# abbrev "shouhi" とは独立)。参照接頭辞は corpus 実在の shouhi-zei-hou 系に対応。
# 第1章は 法/令 のみ参照 (規/措法なし) で全件 corpus 内 -> corpus_unregistered 空。
SHOUHI_CONFIG = CircularConfig(
    law_name_ja="消費税法基本通達",
    law_abbrev="shouhi-kihon-tsutatsu",
    source_url_base="https://www.nta.go.jp/law/tsutatsu/kihon/shohi",
    ref_map={
        "法": "shouhi-zei-hou",
        "令": "shouhi-zei-hou-shikkourei",
        "規": "shouhi-zei-hou-shikoukisoku",
    },
    corpus_unregistered=frozenset(),
    amendment_marker="課消",  # 消費税通達の改正注記記号 (例: 平28課消1-57)
)

# --circular セレクタの登録簿。
CIRCULAR_CONFIGS: dict[str, CircularConfig] = {
    "hojin": HOJIN_CONFIG,
    "shouhi": SHOUHI_CONFIG,
}


# 出力 JSONL の chunk-level キー順マスタ (出力保持の正本・FU-514)。
# DirectiveChunk.model_dump() (意味フィールド) + 配管フィールドをマージした後、
# この順で再構築して現 dict の interleaved キー順をバイト再現する。
# naive な {**semantic, **pipeline} は配管キーが末尾集中で順序が崩れる (Bug1)。
DIRECTIVE_KEY_ORDER = [
    "id",
    "directive_id",
    "law_name_ja",
    "law_abbrev",
    "directive_number",
    "title",
    "text",
    "amendment_note",
    "related_articles",
    "source_url",
    "license",
    "segment_type",
    "article_id",
    "law_name_ja_display",
]

# ---------------------------------------------------------------------------
# Text normalization helpers (R7, R10)
# ---------------------------------------------------------------------------

# All horizontal bar variants -> ASCII hyphen
_BAR_RE = re.compile(r"[\-\uff0d\u2010\u30fc\u2212\u2014\u2015]")
# Non-breaking space / full-width space -> regular space
_NBSP_RE = re.compile("[\u00a0\u3000 ]")


def _normalize_bars(s: str) -> str:
    """Replace all horizontal bar variants with ASCII hyphen (R7)."""
    return _BAR_RE.sub("-", s)


def _normalize_whitespace(s: str) -> str:
    """Replace non-breaking and full-width spaces with ASCII space (R10)."""
    return _NBSP_RE.sub(" ", s)


def _normalize_text(s: str) -> str:
    return _normalize_whitespace(_normalize_bars(s))


# ---------------------------------------------------------------------------
# Related article extraction (R2, R8, R12)
# ---------------------------------------------------------------------------

# Pattern: 法/令/規/措法 + 第 + article + optional branches + optional paragraph
# R8: relative refs (同条/同法/同項) excluded by requiring explicit prefix
# R12: multi-level no: (?:の\d+)* (not just ?)
_LAW_REF_RE = re.compile(
    r"(法|令|規|措法)第(\d+)条(?:の(\d+))*(?:第(\d+)項)?",
)
# The above only captures last の-branch. Use a more explicit form:
_LAW_REF_FULL_RE = re.compile(
    r"(法|令|規|措法)第(\d+)条((?:の\d+)*)"
    r"(?:第(\d+)項)?",
)


def _extract_related_articles(text: str, config: CircularConfig) -> list[dict]:
    """Extract law article references from text (R2, R8, R12).

    Returns list of dicts with keys: raw, law_abbrev, article_number, article_id.
    Unresolved references (corpus未収録) are included with article_id=None + warn.
    接頭辞 -> law_abbrev の対応と corpus 未登録判定は config に従う (通達ごとに切替)。
    """
    results: list[dict] = []
    seen_raw: set[str] = set()

    for m in _LAW_REF_FULL_RE.finditer(text):
        prefix = m.group(1)  # 法/令/規/措法
        base_num = m.group(2)  # e.g. "34"
        no_suffix = m.group(3) or ""  # e.g. "の2の2" or ""
        # para = m.group(4)  -- not used for article_id

        raw = m.group(0)
        if raw in seen_raw:
            continue
        seen_raw.add(raw)

        law_abbrev = config.ref_map.get(prefix)
        if law_abbrev is None:
            # Unknown prefix: skip silently (R8: only explicit prefixes)
            continue

        # Build article_number: base + each の-branch as -N
        # "の2の2" -> ["2", "2"]
        branches = re.findall(r"\d+", no_suffix)
        article_number = base_num
        if branches:
            article_number = base_num + "-" + "-".join(branches)

        if law_abbrev in config.corpus_unregistered:
            warnings.warn(
                f"WARN: {raw!r} -> {law_abbrev} is not in corpus (corpus未収録). "
                "Keeping raw reference without article_id link.",
                stacklevel=2,
            )
            results.append(
                {
                    # disjoint Union の Unlinked 形に合わせ article_id キーは持たせない
                    # (FU-514: DirectiveUnlinkedArticleRef は extra="forbid")。
                    # 現コーパスは unlinked 0 件なので出力 byte は不変。
                    "raw": raw,
                    "law_abbrev": law_abbrev,
                    "article_number": article_number,
                    "unlinked_reason": "corpus_unregistered",
                }
            )
        else:
            article_id = f"{law_abbrev}-art-{article_number}"
            results.append(
                {
                    "raw": raw,
                    "law_abbrev": law_abbrev,
                    "article_number": article_number,
                    "article_id": article_id,
                }
            )

    return results


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

# Directive number pattern after normalization (all bars -> -)
# Full-width digits may appear; normalize before matching
_DIRECTIVE_NUM_RE = re.compile(r"^(\d+-\d+-\d+(?:の\d+)*)\s*$")

# 段落テキスト先頭の項番号 (split-strong 形式の検出用)。
# NTA の消費税通達では番号が <strong>1</strong>－3－2 ... のように分割され、
# strong だけでは番号全体にならない項がある (法人税通達は番号全体が strong 内)。
# CASE A (番号全体が strong) が外れたときのみ本パターンで段落先頭から番号を拾う。
_LEADING_DIRECTIVE_RE = re.compile(r"^(\d+-\d+-\d+(?:の\d+)*)\s")

# 多章モードで cache root 直下から「章ディレクトリ」だけを拾うフィルタ。
# 章は 2 桁ゼロ詰め (01..21)。前文ページ (shohi/02.htm = root 直下の .htm で
# parts[0]="02.htm" → 非該当) や旧版アーカイブ (shohi/20230930/ = 8 桁 → 非該当) を
# fullmatch で機械的に除外する。
_CHAPTER_DIR_RE = re.compile(r"\d{2}")

# directive_id の命名規則 (ユニークさとは別の形式ゲート・査読項11)。
# {law_abbrev}-{章}-{節}-{項}(の{枝番})* の形だけを許し、章跨ぎ取込で番号抽出が
# 崩れた record (節欠落・全角混入等) を fail-loud で止める。
_DIRECTIVE_ID_TAIL_RE = re.compile(r"\d+-\d+-\d+(?:の\d+)*")


def _directive_id_ok(directive_id: str, config: CircularConfig) -> bool:
    """True if directive_id == '{law_abbrev}-{N-N-N(のN)*}' (査読項11)."""
    prefix = f"{config.law_abbrev}-"
    if not directive_id.startswith(prefix):
        return False
    return _DIRECTIVE_ID_TAIL_RE.fullmatch(directive_id[len(prefix) :]) is not None


def _detect_charset(raw: bytes) -> str:
    """Detect encoding from HTML meta tag or default to cp932 (R1)."""
    # Try HTTP-equiv meta
    m = re.search(rb"charset=([^\s\"'>;]+)", raw[:2000], re.I)
    if m:
        enc = m.group(1).decode("ascii", errors="replace").strip().lower()
        # Normalize shift_jis variants to cp932
        if enc in ("shift_jis", "shift-jis", "sjis", "x-sjis", "shift_jis-2004"):
            return "cp932"
        return enc
    return "cp932"


def _build_directive_record(
    *,
    num: str,
    title: str,
    body: str,
    amendment_note: str,
    related: list[dict],
    source_url: str,
    config: CircularConfig,
) -> dict:
    """Validate via DirectiveChunk (Pydantic IR) and reconstruct the 14-key record.

    Why: routing through DirectiveChunk catches malformed refs at parse time and
    keeps the disjoint linked/unlinked Union honest, while the explicit
    DIRECTIVE_KEY_ORDER reconstruction reproduces the historical interleaved key
    order byte-for-byte. Pipeline fields (id / law_name_ja / law_name_ja_display
    / segment_type / article_id) are merged post-dump (not part of the semantic
    IR), and article_id is injected as None explicitly so the key is always
    present (Bug29: never silently dropped via .get()).
    """
    from juricode_shared.ir import DirectiveChunk

    directive_id = f"{config.law_abbrev}-{num}"
    chunk = DirectiveChunk(
        directive_id=directive_id,
        directive_number=num,
        law_abbrev=config.law_abbrev,
        title=title,
        text=body,
        amendment_note=amendment_note,
        related_articles=related,  # dict -> disjoint Union が linked/unlinked を判別
        source_url=source_url,
        license=config.license,
    )
    semantic = chunk.model_dump(mode="json")

    # 配管フィールドを明示注入 (retrieve.py 互換)。article_id は None でも必ず入れる。
    merged = {
        **semantic,
        "id": directive_id,
        "law_name_ja": config.law_name_ja,
        "law_name_ja_display": f"{config.law_name_ja} {num}",
        "segment_type": "tsutatsu",
        "article_id": None,
    }

    # キー順再構築: 全 14 キーが存在する前提 (欠落は KeyError で fail loud)。
    return {k: merged[k] for k in DIRECTIVE_KEY_ORDER}


def _extract_directive_items(
    soup: BeautifulSoup, source_url: str, config: CircularConfig
) -> list[dict]:
    """Parse BeautifulSoup of a single htm page -> list of directive chunk dicts.

    One dict per directive item (e.g. 9-2-9, 9-2-10, ...).
    R4: handles multiple items per page.
    """
    items: list[dict] = []
    # current_title = 直近に出現した見出し (h2) = 次に始まる項の見出し (pending)。
    # current_item_title = いま蓄積中の項に確定済みの見出し。
    # 番号検出時に current_title を current_item_title へ束縛することで「項に対し
    # 直前の見出し」を正しく割当てる (旧実装は flush 時の current_title を使い、既に
    # 次項の見出しへ進んでいたため +1 ズレていた)。
    current_title: str | None = None
    current_item_title: str | None = None
    current_num: str | None = None
    current_body_parts: list[str] = []
    current_amendment: str | None = None

    def _flush(num: str | None, title: str | None, parts: list[str], amend: str | None) -> None:
        if num is None:
            return
        body = "\n".join(parts).strip()
        # Extract amendment note from end of body if not already found.
        # marker は通達ごと (課法/課消)。hojin の "課法" は従来正規表現と同一 -> byte 不変。
        amendment_note = amend
        if amendment_note is None:
            amend_re = rf"（[^）]*{re.escape(config.amendment_marker)}[^）]*）\s*$"
            amend_m = re.search(amend_re, body)
            if amend_m:
                amendment_note = amend_m.group(0)
                body = body[: amend_m.start()].rstrip()

        # Normalize bars/whitespace in body
        body = _normalize_text(body)
        related = _extract_related_articles(body, config)

        items.append(
            _build_directive_record(
                num=num,
                title=title or "",
                body=body,
                amendment_note=amendment_note or "",
                related=related,
                source_url=source_url,
                config=config,
            )
        )

    body_area = soup.find(id="bodyArea") or soup.find(id="contents")
    if body_area is None:
        warnings.warn(f"WARN: bodyArea not found in {source_url}", stacklevel=2)
        return items

    for tag in body_area.find_all(["h1", "h2", "p"]):
        tag_name = tag.name

        if tag_name in ("h1", "h2"):
            # h2 is the title before a directive item. e.g. "（債務の免除による利益...）"
            # h1 is the section header - skip
            if tag_name == "h2":
                current_title = tag.get_text(strip=True)
            continue

        # p tags: check if it starts a new directive item
        strong = tag.find("strong")
        if strong:
            raw_num_text = _normalize_text(strong.get_text())
            num_match = _DIRECTIVE_NUM_RE.match(raw_num_text.strip())
            if num_match:
                # CASE A: 番号全体が <strong> 内 (法人税通達・一部の消費税通達)。
                # Flush previous item (確定済み見出し current_item_title を使う)。
                _flush(current_num, current_item_title, current_body_parts, current_amendment)
                # Start new item: この番号の直前見出しを確定束縛 (title-lag 修正)。
                # 見出しは「直後の1番号」専用。束縛後 None に戻すことで、自前見出しの
                # ない「削除」通達が前項の見出しを継承しない (第2エッジ・タイトルなし)。
                current_num = num_match.group(1)
                current_item_title = current_title
                current_title = None
                current_body_parts = []
                current_amendment = None
                # Get body text after the number (remove strong element text)
                strong.decompose()
                # R13: explicit newline before text (inline -> block)
                remaining = _normalize_text(tag.get_text(separator="\n")).strip()
                if remaining:
                    current_body_parts.append(remaining)
                continue

            # CASE B: split-strong (消費税通達 <strong>1</strong>－3－2 ...)。
            # strong だけでは番号にならないため、段落テキスト先頭の番号を拾う。
            # 番号を含まない段落 (indent2 の「(1)…」等) は先頭が番号にならず非該当。
            plain = _normalize_text(tag.get_text()).strip()
            lead_match = _LEADING_DIRECTIVE_RE.match(plain)
            if lead_match:
                _flush(current_num, current_item_title, current_body_parts, current_amendment)
                current_num = lead_match.group(1)
                current_item_title = current_title
                current_title = None  # consume-once (第2エッジ: 削除通達はタイトルなし)
                current_body_parts = []
                current_amendment = None
                remaining = plain[lead_match.end() :].strip()
                if remaining:
                    current_body_parts.append(remaining)
                continue

        # Regular paragraph (indent1/indent2/other)
        if current_num is not None:
            classes = tag.get("class") or []
            raw_text = _normalize_text(tag.get_text(separator="\n")).strip()
            if not raw_text:
                continue
            if "indent2" in classes:
                # R13: items as block lines
                current_body_parts.append(raw_text)
            elif "indent1" in classes:
                current_body_parts.append(raw_text)
            else:
                current_body_parts.append(raw_text)

    # Flush last item (確定済み見出しを使う)。
    _flush(current_num, current_item_title, current_body_parts, current_amendment)

    # Validate: 0 items = parse error
    if not items:
        warnings.warn(f"WARN: no directive items parsed from {source_url}", stacklevel=2)

    return items


def _build_source_url(config: CircularConfig, rel_path: Path) -> str:
    """NTA source URL from a path relative to the chapter root.

    Why: source_url must preserve the full chapter/section/目 sub-path so that
    4-level files (e.g. 09/01/01.htm under 第9章第1節第1目) map to the correct NTA
    URL. The old flat formula ``{base}/{chapter}/{stem}.htm`` dropped the 目 level
    and would have produced /shohi/09/01.htm for 09/01/01.htm. as_posix() keeps the
    URL separator '/' on every OS (Bug: Windows backslash leaking into URLs).
    """
    return f"{config.source_url_base}/{rel_path.as_posix()}"


def parse_file(htm_path: Path, config: CircularConfig, source_url: str) -> list[dict]:
    """Parse a single cached HTML file -> list of directive chunk dicts.

    source_url is computed by the caller (single-chapter: from --chapter + stem;
    multi-chapter: from the file path relative to the cache root via
    _build_source_url, preserving the 目 sub-path). Passing it in keeps this
    function path-policy-free and lets the single-chapter path stay byte-identical.
    """
    raw = htm_path.read_bytes()
    enc = _detect_charset(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except (LookupError, UnicodeDecodeError) as e:
        warnings.warn(
            f"WARN: decode error ({e}), falling back to cp932 for {htm_path.name}", stacklevel=2
        )
        text = raw.decode("cp932", errors="replace")

    # Decode sanity check (R1). cp932 decode with errors="replace" inserts U+FFFD
    # on byte failure; a correctly-decoded NTA page has zero. The old check looked
    # for hojin-specific keywords (経済的/役員/退職) which are absent in most 消費税
    # chapters -> false-positive warnings that could mask a real decode failure.
    # Replacement-char detection is circular-agnostic and fires only on real mojibake.
    n_repl = text.count("\ufffd")
    if n_repl:
        warnings.warn(
            f"WARN: {n_repl} replacement char(s) after decode in {htm_path.name} "
            f"(charset detected: {enc}) -- possible mojibake.",
            stacklevel=2,
        )

    soup = BeautifulSoup(text, "html.parser")
    items = _extract_directive_items(soup, source_url, config)
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse NTA tsutatsu HTML -> directive JSONL chunks.")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("cache/tsutatsu/hojin/09"),
        help="Single-chapter mode: directory of cached .htm files (uses --chapter for the URL).",
    )
    ap.add_argument(
        "--cache-root",
        type=Path,
        default=None,
        help=(
            "Multi-chapter mode: root holding <chapter>/<...>.htm. When set, all chapters "
            "under it are parsed, merged, globally numeric-sorted, and written to one file; "
            "source_url is derived per-file from its path (preserves the 目 sub-path). "
            "Takes precedence over --cache-dir/--chapter."
        ),
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/chunks/hojin-kihon-tsutatsu"),
        help="Output directory for JSONL chunk file.",
    )
    ap.add_argument(
        "--circular",
        choices=sorted(CIRCULAR_CONFIGS),
        default="hojin",
        help="Which circular's config to use (law_name / NTA URL base / ref_map).",
    )
    ap.add_argument("--chapter", default="09", help="Chapter directory name (e.g. '09').")
    ap.add_argument("--section", default="02", help="Section number prefix (e.g. '02').")
    ap.add_argument(
        "--glob-pattern",
        default="*.htm",
        help="Glob pattern to match HTML files in cache-dir.",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    config = CIRCULAR_CONFIGS[args.circular]

    # 取込対象ファイルと、各ファイル -> source_url の解決方法をモード別に確定する。
    # 単一章 (--cache-dir + --chapter): 非再帰 glob・URL は {base}/{chapter}/{stem}.htm
    #   (従来式そのまま -> hojin / 消費税第1章 byte 不変)。
    # 多章 (--cache-root): rglob・URL は root からの相対パス (目サブパス保持)。
    if args.cache_root is not None:
        root = args.cache_root
        if not root.exists():
            print(f"ERROR: cache-root not found: {root}", file=sys.stderr)
            return 1
        htm_files = sorted(
            p
            for p in root.rglob(args.glob_pattern)
            if _CHAPTER_DIR_RE.fullmatch(p.relative_to(root).parts[0])
        )
        src_label = str(root)

        def _src_url(p: Path) -> str:
            return _build_source_url(config, p.relative_to(root))
    else:
        if not args.cache_dir.exists():
            print(f"ERROR: cache-dir not found: {args.cache_dir}", file=sys.stderr)
            return 1
        htm_files = sorted(args.cache_dir.glob(args.glob_pattern))
        src_label = str(args.cache_dir)

        def _src_url(p: Path) -> str:
            return _build_source_url(config, Path(args.chapter) / f"{p.stem}.htm")

    if not htm_files:
        print(f"ERROR: no .htm files found in {src_label}", file=sys.stderr)
        return 1

    print(f"Parsing {len(htm_files)} HTML file(s) from {src_label}", file=sys.stderr)

    all_items: list[dict] = []
    seen_ids: set[str] = set()
    errors: list[str] = []

    for htm_path in htm_files:
        try:
            items = parse_file(htm_path, config, _src_url(htm_path))
        except Exception as e:
            msg = f"ERROR: failed to parse {htm_path.name}: {e}"
            print(msg, file=sys.stderr)
            errors.append(msg)
            continue

        if args.verbose:
            print(f"  {htm_path.name}: {len(items)} items", file=sys.stderr)

        for item in items:
            did = item["directive_id"]
            if not _directive_id_ok(did, config):
                # 形式ゲート (査読項11): 番号抽出が崩れた record を fail-loud で止める。
                print(
                    f"ERROR: directive_id {did!r} from {htm_path.name} violates the naming "
                    f"rule '{config.law_abbrev}-<chap>-<sec>-<item>(の<branch>)*'",
                    file=sys.stderr,
                )
                return 1
            if did in seen_ids:
                # fail-loud (Bug36): 「目」階層・枝番で directive_id が衝突すると
                # サイレント上書き/欠落になる。重複は黙って捨てず即エラーで止める。
                print(
                    f"ERROR: duplicate directive_id {did!r} from {htm_path.name} "
                    "(directive_id must be unique across the circular)",
                    file=sys.stderr,
                )
                return 1
            seen_ids.add(did)
            all_items.append(item)

    if not all_items:
        print("ERROR: no directive items produced", file=sys.stderr)
        return 1

    # Sort by directive_number for deterministic output
    # e.g. "9-2-9" < "9-2-9の2" < "9-2-10" < "9-2-12の2"
    def _sort_key(item: dict) -> tuple:
        num = item["directive_number"]  # e.g. "9-2-12の2の3"
        # Split on hyphen first, then on "の" within each part
        parts: list[int] = []
        for segment in num.split("-"):
            for sub in re.split(r"の", segment):
                parts.append(int(sub) if sub.isdigit() else 0)
        # Pad to fixed length for comparison
        while len(parts) < 6:
            parts.append(0)
        return tuple(parts)

    all_items.sort(key=_sort_key)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{config.law_abbrev}.tsutatsu.chunks.jsonl"

    # safe_write via juricode_shared
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "src"))
    from juricode_shared.safe_write import safe_write_jsonl

    safe_write_jsonl(out_path, all_items)

    print(f"Written {len(all_items)} directive chunks -> {out_path}", file=sys.stderr)

    # Summary
    for item in all_items:
        n_refs = len(item["related_articles"])
        linked = sum(1 for r in item["related_articles"] if r.get("article_id"))
        print(
            f"  {item['directive_number']:12s}  refs={n_refs}(linked={linked})  "
            f"chars={len(item['text'])}",
            file=sys.stderr,
        )

    if errors:
        print(f"\n{len(errors)} error(s) during parsing:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

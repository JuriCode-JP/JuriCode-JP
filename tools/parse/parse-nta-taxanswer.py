#!/usr/bin/env python3
"""parse-nta-taxanswer.py -- NTA TaxAnswer HTML -> TaxAnswer JSONL chunks.

Usage:
    python tools/parse/parse-nta-taxanswer.py \\
        --cache-dir cache/taxanswer/hojin \\
        --output-dir build/chunks/hojin-taxanswer \\
        --law-abbrev hojin-taxanswer \\
        --tax-category hojin

Output: build/chunks/hojin-taxanswer/hojin-taxanswer.taxanswer.chunks.jsonl

One record per TaxAnswer page (e.g. No.5200).
Each record has:
    id                  : "hojin-taxanswer-5200"
    code                : "5200"
    title               : "役員の範囲"
    body                : main body text (Markdown)
    version_date        : "2025-04-01" (from [令和7年4月1日現在法令等], or None)
    related_articles    : list of {raw, law_abbrev, article_id}
    related_directives  : list of {raw, directive_id, law_abbrev}
    related_qa          : list of str (codes, e.g. ["5210", "5211"])
    license             : "cc-by-jp-nta"
    attribution         : "国税庁タックスアンサー"
    source_url          : "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5200.htm"
    source_format       : "nta-html"
    segment_type        : "taxanswer"
    article_id          : None  (retrieve.py compatibility)
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import warnings
from pathlib import Path
from urllib.parse import urljoin

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")

# juricode_shared is available once sys.path is patched in main(); lazy import at module level
# would fail in test context -- defer import to _build_chunk_record() called from parse_file().
_SHARED_SRC = Path(__file__).resolve().parents[1] / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_URL_BASE = "https://www.nta.go.jp/taxes/shiraberu/taxanswer"
LICENSE = "cc-by-jp-nta"
ATTRIBUTION = "国税庁タックスアンサー"  # 国税庁タックスアンサー
SOURCE_FORMAT = "nta-html"

# Abbreviation prefix -> (law_abbrev, id_prefix) mapping
LAW_PREFIX_MAP: dict[str, tuple[str, str]] = {
    "法法": ("houjin-zei-hou", "houjin-zei-hou-art"),  # 法法
    "法令": ("houjin-zei-hou-shikkourei", "houjin-zei-hou-shikkourei-art"),  # 法令
    "法規": ("houjin-zei-hou-shikoukisoku", "houjin-zei-hou-shikoukisoku-art"),  # 法規
    "法基通": ("hojin-kihon-tsutatsu", "hojin-kihon-tsutatsu"),  # 法基通
}

# Prefixes that are not in corpus (unlinked + warn)
CORPUS_UNREGISTERED_PREFIXES = {
    "措法",  # 措法
}

# Prefixes for 改正附則 (amendment proviso) - always unlinked
_KAISEI_RE = re.compile(
    r"^(?:平\d+|令\d+)改正"  # 平N改正 or 令N改正
)

# ---------------------------------------------------------------------------
# Text normalization (R7, R10) -- cp932-safe: use Unicode escapes
# ---------------------------------------------------------------------------

_BAR_RE = re.compile(r"[\-\uff0d\u2010\u30fc\u2212\u2014\u2015]")
_NBSP_RE = re.compile("[\u00a0\u3000\ufeff]")
_WAVE_RE = re.compile(r"[～〜]")  # ～ and 〜 -> ~


def _normalize_bars(s: str) -> str:
    return _BAR_RE.sub("-", s)


def _normalize_whitespace(s: str) -> str:
    return _NBSP_RE.sub(" ", s)


def _normalize_wave(s: str) -> str:
    return _WAVE_RE.sub("~", s)


def _normalize_text(s: str) -> str:
    return _normalize_whitespace(_normalize_bars(_normalize_wave(s)))


# ---------------------------------------------------------------------------
# Version date extraction (R23: Optional)
# ---------------------------------------------------------------------------

# e.g. "[令和7年4月1日現在法令等]" or "[平成28年4月1日現在法令等]"
_VERSION_DATE_RE = re.compile(r"[\[［]\s*(?:(令和)(\d+)|(平成)(\d+))年(\d+)月(\d+)日現在")

_REIWA_START = 2018  # 令和元年 = 2019 (offset from era year 1)
_HEISEI_START = 1988  # 平成元年 = 1989


def _parse_version_date(text: str) -> str | None:
    """Extract version_date from '[令和7年4月1日現在法令等]' pattern."""
    m = _VERSION_DATE_RE.search(text)
    if not m:
        return None
    reiwa_era, reiwa_year, _heisei_era, heisei_year, month, day = m.groups()
    if reiwa_era:
        year = _REIWA_START + int(reiwa_year)
    else:
        year = _HEISEI_START + int(heisei_year)
    return f"{year:04d}-{int(month):02d}-{int(day):02d}"


# ---------------------------------------------------------------------------
# Related extraction: articles, directives, qa (R2/R8/R12/R22/R29/R34/R41-44)
# ---------------------------------------------------------------------------

# Tsutatsu directive number pattern: N-N-N(のN)*
_TSUTATSU_NUM_RE = re.compile(r"(\d+-\d+-\d+(?:の\d+)*)")  # 9-2-9 or 9-2-12の2

# Range pattern: N~M (after normalization, ~ = wave)
_RANGE_RE = re.compile(r"^(\d+(?:-\d+)*(?:の\d+)*~(\d+))$")  # e.g. 9-2-9~11

# の-branch pattern in article numbers
_NO_BRANCH_RE = re.compile(r"(\d+)(?:の(\d+))+")  # 54の2, 22の3, 71の2

# Tokens that look like amendment proviso: 平N改正xxx附則
_FUNSOKU_TOKEN_RE = re.compile(r"附則")  # 附則


def _build_article_id(id_prefix: str, raw_num: str) -> str:
    """Build article_id from prefix and raw number like '54の2' -> '...art-54-2'."""
    # Normalize の -> - in article number
    num = re.sub(r"の", "-", raw_num)  # の -> -
    num = _normalize_bars(num)
    return f"{id_prefix}-{num}"


def _build_directive_id(law_abbrev: str, directive_num: str) -> str:
    """Build directive_id: hojin-kihon-tsutatsu-9-2-9 (R41: dynamic segment decomposition)."""
    # directive_num is already normalized (e.g. "9-2-9" or "9-2-12の2")
    # Normalize の -> - for ID
    num_id = re.sub(r"の", "-", directive_num)
    num_id = _normalize_bars(num_id)
    return f"{law_abbrev}-{num_id}"


def _is_amendment_token(token: str) -> bool:
    """Return True if token is an amendment proviso (改正法/令/規則附則 N)."""
    return bool(_KAISEI_RE.match(token)) or "附則" in token


def _expand_range(prefix_str: str, range_raw: str, law_abbrev: str, id_prefix: str) -> list[dict]:
    """Expand range like '9-2-9~11' or '9-2-35~38' into individual directive entries.

    R42: Only expand if BOTH endpoints are pure integers (no の-branch) AND same chapter-section.
    Returns [] (empty = unlinked) for invalid ranges.
    """
    # Normalize: after _normalize_wave, ~ is already ASCII ~
    m = re.match(r"^(.+)~(\d+)$", range_raw)
    if not m:
        return []

    start_part = m.group(1)  # e.g. "9-2-9" or "9-2-9の2"
    end_int = int(m.group(2))  # e.g. 11 or 38

    # R42: start endpoint must be a plain integer (no の-branch)
    # Split on - to get segments
    segs = start_part.split("-")
    last_seg = segs[-1]
    prefix_segs = segs[:-1]  # e.g. ["9","2"]

    if "の" in last_seg:  # の in last segment = branch endpoint = forbidden
        return []

    try:
        start_int = int(last_seg)
    except ValueError:
        return []

    if end_int <= start_int:
        return []

    prefix_part = "-".join(prefix_segs)  # e.g. "9-2"
    results = []
    for n in range(start_int, end_int + 1):
        directive_num = f"{prefix_part}-{n}"
        did = _build_directive_id(law_abbrev, directive_num)
        results.append(
            {
                "raw": range_raw,
                "directive_num": directive_num,
                "law_abbrev": law_abbrev,
                "directive_id": did,
            }
        )
    return results


# Known tsutatsu corpus (loaded at runtime from build/chunks if available)
_TSUTATSU_CORPUS: set[str] | None = None


def _load_tsutatsu_corpus() -> set[str]:
    global _TSUTATSU_CORPUS
    if _TSUTATSU_CORPUS is not None:
        return _TSUTATSU_CORPUS
    import json

    chunks = (
        Path(__file__).resolve().parents[2]
        / "build"
        / "chunks"
        / "hojin-kihon-tsutatsu"
        / "hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    )
    nums: set[str] = set()
    if chunks.exists():
        for line in chunks.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    nums.add(r["directive_number"])
                except Exception:
                    pass
    _TSUTATSU_CORPUS = nums
    return nums


def extract_related_from_kikon(raw_kikon: str) -> dict:
    """Parse 根拠法令等 raw text into related_articles / related_directives / unlinked.

    Args:
        raw_kikon: raw text of 根拠法令等 section, e.g. "法法22、34、法令69、70、法基通9-2-9～11"

    Returns:
        dict with keys:
            related_articles: list of {raw, law_abbrev, article_number, article_id}
            related_directives: list of {raw, law_abbrev, directive_id} (linked only)
            unlinked: list of {raw, reason} (unlinked entries)
    """
    text = _normalize_text(raw_kikon)

    # Split on Japanese comma (、) or ASCII comma
    tokens = [t.strip() for t in re.split(r"[、,]", text) if t.strip()]

    related_articles: list[dict] = []
    related_directives: list[dict] = []
    unlinked: list[dict] = []

    current_prefix: str | None = None  # last seen explicit prefix (for inheritance)
    current_law_abbrev: str | None = None
    current_id_prefix: str | None = None

    tsutatsu_corpus = _load_tsutatsu_corpus()

    for token in tokens:
        token = token.strip()
        if not token:
            continue

        # Detect amendment proviso tokens -> always unlinked (R40)
        if _is_amendment_token(token):
            unlinked.append({"raw": token, "reason": "kaisei_funsoku"})
            # Keep current_prefix (amendment prefix does not override, e.g. 改正法附則14、15)
            # But 15 after 改正法附則14 should also be unlinked (no prefix, inherit amendment)
            # We flag the prefix as "amendment" so continuation is also unlinked
            current_prefix = "__amendment__"
            current_law_abbrev = None
            current_id_prefix = None
            continue

        # If previous was amendment, continuation is also unlinked
        if current_prefix == "__amendment__":
            # Check if this token looks like a bare number (amendment continuation)
            if re.match(r"^\d+$", token):
                unlinked.append({"raw": token, "reason": "kaisei_funsoku_continuation"})
                continue
            # Otherwise it may start a new prefix -- fall through

        # Try to match known prefixes at start of token
        matched_prefix = None
        for pfx in sorted(LAW_PREFIX_MAP.keys(), key=len, reverse=True):
            if token.startswith(pfx):
                matched_prefix = pfx
                break

        if matched_prefix is None:
            for pfx in sorted(CORPUS_UNREGISTERED_PREFIXES, key=len, reverse=True):
                if token.startswith(pfx):
                    matched_prefix = pfx
                    break

        if matched_prefix:
            remainder = token[len(matched_prefix) :].strip()

            # Corpus unregistered (措法)
            if matched_prefix in CORPUS_UNREGISTERED_PREFIXES:
                warnings.warn(
                    f"WARN: {token!r} -> {matched_prefix} is not in corpus. Keeping as unlinked.",
                    stacklevel=2,
                )
                unlinked.append({"raw": token, "reason": "corpus_unregistered"})
                current_prefix = matched_prefix
                current_law_abbrev = None
                current_id_prefix = None
                continue

            law_abbrev, id_prefix = LAW_PREFIX_MAP[matched_prefix]
            current_prefix = matched_prefix
            current_law_abbrev = law_abbrev
            current_id_prefix = id_prefix

            # Process the remainder
            _process_remainder(
                remainder,
                token,
                matched_prefix,
                law_abbrev,
                id_prefix,
                tsutatsu_corpus,
                related_articles,
                related_directives,
                unlinked,
            )
        else:
            # No explicit prefix: inherit from current_prefix
            if current_prefix is None or current_prefix == "__amendment__":
                # No known context -- skip with warn
                warnings.warn(
                    f"WARN: token {token!r} has no prefix and no prior context. Skipping.",
                    stacklevel=2,
                )
                continue

            if current_prefix in CORPUS_UNREGISTERED_PREFIXES:
                unlinked.append({"raw": token, "reason": "corpus_unregistered_continuation"})
                continue

            # Inherit current prefix
            _process_remainder(
                token,
                token,
                current_prefix,
                current_law_abbrev,
                current_id_prefix,
                tsutatsu_corpus,
                related_articles,
                related_directives,
                unlinked,
            )

    return {
        "related_articles": related_articles,
        "related_directives": related_directives,
        "unlinked": unlinked,
    }


def _process_remainder(
    remainder: str,
    raw_token: str,
    prefix: str,
    law_abbrev: str,
    id_prefix: str,
    tsutatsu_corpus: set[str],
    related_articles: list,
    related_directives: list,
    unlinked: list,
) -> None:
    """Process the remainder of a token after stripping prefix."""
    remainder = remainder.strip()
    if not remainder:
        return

    is_tsutatsu = prefix == "法基通"  # 法基通

    if is_tsutatsu:
        _process_tsutatsu_remainder(
            remainder, raw_token, law_abbrev, tsutatsu_corpus, related_directives, unlinked
        )
    else:
        # Article reference
        # Strip trailing 丸数字 (①②...) from remainder
        remainder = re.sub(
            r"[\u2460-\u2473\u24ff\u3251-\u3257\u3280-\u32b0]", "", remainder
        ).strip()
        article_id = _build_article_id(id_prefix, remainder)
        related_articles.append(
            {
                "raw": raw_token,
                "law_abbrev": law_abbrev,
                "article_number": remainder,
                "article_id": article_id,
            }
        )


def _process_tsutatsu_remainder(
    remainder: str,
    raw_token: str,
    law_abbrev: str,
    tsutatsu_corpus: set[str],
    related_directives: list,
    unlinked: list,
) -> None:
    """Process tsutatsu directive number (may include range like 9-2-9~11)."""
    # Check for range (~ after normalization)
    if "~" in remainder:
        expanded = _expand_range(law_abbrev, remainder, law_abbrev, law_abbrev)
        if not expanded:
            # Non-expandable range (の-branch or invalid) -> unlinked (R34)
            warnings.warn(
                f"WARN: tsutatsu range {remainder!r} cannot be expanded (R34). Unlinked.",
                stacklevel=3,
            )
            unlinked.append({"raw": raw_token, "reason": "range_not_expandable"})
            return
        for entry in expanded:
            directive_num = entry["directive_num"]
            did = entry["directive_id"]
            if directive_num in tsutatsu_corpus:
                related_directives.append(
                    {
                        "raw": raw_token,
                        "directive_number": directive_num,
                        "law_abbrev": law_abbrev,
                        "directive_id": did,
                    }
                )
            else:
                warnings.warn(
                    f"WARN: tsutatsu {directive_num!r} not in corpus. Unlinked.",
                    stacklevel=3,
                )
                unlinked.append({"raw": raw_token, "reason": "tsutatsu_not_in_corpus"})
    else:
        # Single directive number
        directive_num = remainder
        did = _build_directive_id(law_abbrev, directive_num)
        if directive_num in tsutatsu_corpus:
            related_directives.append(
                {
                    "raw": raw_token,
                    "directive_number": directive_num,
                    "law_abbrev": law_abbrev,
                    "directive_id": did,
                }
            )
        else:
            warnings.warn(
                f"WARN: tsutatsu {directive_num!r} not in corpus. Unlinked.",
                stacklevel=3,
            )
            unlinked.append({"raw": raw_token, "reason": "tsutatsu_not_in_corpus"})


# ---------------------------------------------------------------------------
# related_qa extraction (R44: href-based only)
# ---------------------------------------------------------------------------

# Why: 枝番コード (base-branch, 例 '5364-2') への related_qa リンクを取りこぼさない
# よう 1 段の枝番を許容する。メインコードはファイル名 stem 由来だが related_qa は
# href 由来ゆえこの regex を通る。
_CODE_FROM_HREF_RE = re.compile(r"/(\d{4,5}(?:-\d+)?)\.htm$", re.I)
_CODE_FROM_HREF_REL_RE = re.compile(r"^(\d{4,5}(?:-\d+)?)\.htm$", re.I)


def extract_related_qa_from_html(html_fragment: str) -> list[str]:
    """Extract related QA codes from 関連コード section hrefs (R44).

    Only reads <a href=...> anchors; never reads body text.
    """
    soup = BeautifulSoup(html_fragment, "html.parser")

    # Find 関連コード h2 and extract anchors after it
    h2_related = None
    for h2 in soup.find_all("h2"):
        if "関連コード" in h2.get_text():  # 関連コード
            h2_related = h2
            break

    codes: list[str] = []
    seen: set[str] = set()

    if h2_related:
        # Collect all <a> tags after this h2 until next h2
        cur = h2_related.find_next_sibling()
        while cur:
            if cur.name == "h2":
                break
            for a in cur.find_all("a") if cur.name != "a" else [cur]:
                href = a.get("href", "")
                code = _extract_code_from_href(href)
                if code and code not in seen:
                    seen.add(code)
                    codes.append(code)
            cur = cur.find_next_sibling()
    else:
        # No h2 section: scan all <a> tags with taxanswer hrefs
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "taxanswer" in href or re.match(r"^\d{4,5}(?:-\d+)?\.htm$", href):
                code = _extract_code_from_href(href)
                if code and code not in seen:
                    seen.add(code)
                    codes.append(code)

    return codes


def _extract_code_from_href(href: str) -> str | None:
    """Extract 4-5 digit code (optional 1-level branch) from href like .../hojin/5210.htm."""
    m = _CODE_FROM_HREF_RE.search(href)
    if m:
        return m.group(1)
    m = _CODE_FROM_HREF_REL_RE.match(href.split("/")[-1])
    if m:
        return m.group(1)
    return None


def _code_sort_key(code: str) -> tuple[int, int]:
    """'5364-2' -> (5364, 2), '5200' -> (5200, 0)。枝番コードを数値順に並べる.

    Why: all_items のソートで int(code) 直キャストは '5364-2' が ValueError。
    base と枝番を分解して (base, branch) の辞書順で 5364 < 5364-2 < 5365 を得る。
    """
    if "-" in code:
        base, branch = code.split("-", 1)
        return (int(base), int(branch))
    return (int(code), 0)


# ---------------------------------------------------------------------------
# HTML parsing: single TaxAnswer page
# ---------------------------------------------------------------------------


def _norm_h2(s: str) -> str:
    """h2 見出しを NFKC + 内部空白除去して正規化 (完全一致判定用).

    Why: 部分一致 (`in`) は「リンク集」が「関連リンク集」を誤打ち切りする等の事故源。
    全角/半角・空白ゆらぎを NFKC + 空白除去で吸収し、STOP 集合と完全一致で比較する。
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


# 本文抽出は許可リストでなくブロックリスト設計 (FU-526 Phase 2)。
# Why: 許可リスト {概要,対象税目} + 「in_body 中に別 h2 で停止」だと 計算方法/具体例/
# 手続き 等の実体的コンテンツ節を本文ごと落としていた (税理士実務の核が欠落)。最初の
# content h2 で in_body、根拠法令等/boilerplate で停止、それ以外の h2 (未知節含む) は
# fail-open で本文に取り込む。ナビ/リンク列 (関連コード/関連リンク/QAリンク) は corpus
# 構造上すべて 根拠法令等 より後ろに現れるため、この STOP 境界で自然に除外される
# (2026-07-01 実測: 89/89 が根拠法令等の後方)。
_STOP_H2_KEYS = frozenset(
    _norm_h2(x)
    for x in (
        "根拠法令等",  # 根拠法令等 (本文の終端・必ず存在)
        "お問い合わせ先",  # お問い合わせ先
        "税の情報・手続・用紙",  # 税の情報・手続・用紙
        "リンク集",  # リンク集 (実データには未出現だが将来の boilerplate 変種に備え保持)
        "サイトマップ（コンテンツ一覧）",  # サイトマップ (NFKC で半角括弧に正規化)
    )
)


def _detect_charset(raw: bytes) -> str:
    m = re.search(rb"charset=([^\s\"';>]+)", raw[:2000], re.I)
    if m:
        enc = m.group(1).decode("ascii", errors="replace").strip().lower()
        if enc in ("shift_jis", "shift-jis", "sjis", "x-sjis"):
            return "cp932"
        return enc
    return "utf-8"


def parse_file(htm_path: Path, code: str, tax_category: str) -> dict:
    """Parse a single TaxAnswer HTML file -> dict record."""
    raw = htm_path.read_bytes()
    enc = _detect_charset(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except (LookupError, UnicodeDecodeError) as e:
        warnings.warn(f"WARN: decode error ({e}), fallback utf-8 for {htm_path.name}", stacklevel=2)
        text = raw.decode("utf-8", errors="replace")

    soup = BeautifulSoup(text, "html.parser")

    # Title from h1
    h1 = soup.find("h1")
    title_raw = h1.get_text(strip=True) if h1 else ""
    # Strip "No.NNNN " prefix if present (枝番コードは "No.5364-2" ゆえ枝番も剥がす。
    # Why: `^No\.\d+\s*` だと枝番 '-2' が title に残る。非枝番は optional 群が空で不変)。
    title = re.sub(r"^No\.\d+(?:-\d+)?\s*", "", title_raw).strip()

    # version_date from full text (R23: Optional)
    full_text = soup.get_text()
    version_date = _parse_version_date(full_text)

    # Extract body sections (概要 and sub-h3 sections only)
    page_url = f"{SOURCE_URL_BASE}/{tax_category}/{code}.htm"
    body_parts: list[str] = []
    in_body = False
    terminated = False  # 最初の STOP 見出し以降は trailer (関連コード/リンク/boilerplate)
    for tag in soup.find_all(["h2", "h3", "p", "ul", "li", "table", "img"]):
        if tag.name == "h2":
            # ブロックリスト: 最初の STOP 見出し (根拠法令等/boilerplate) で本文を終端し、
            # 以降の h2 では本文を再開しない (根拠法令等の後方に来る 関連コード/関連リンク/
            # QAリンク の trailer を取り込まないため)。それ以外の h2 は content として本文
            # 開始 (fail-open)。h2 見出し自体は本文に含めない。
            if terminated:
                continue
            if _norm_h2(tag.get_text(strip=True)) in _STOP_H2_KEYS:
                in_body = False
                terminated = True
            else:
                in_body = True
            continue
        if not in_body:
            continue

        if tag.name == "h3":
            heading = tag.get_text(strip=True)
            if heading:
                body_parts.append(f"\n### {heading}")
        elif tag.name in ("p",):
            t = _normalize_text(tag.get_text(separator="\n")).strip()
            if t:
                body_parts.append(t)
        elif tag.name in ("ul", "li"):
            t = _normalize_text(tag.get_text(separator="\n")).strip()
            if t and tag.name == "li":
                body_parts.append(f"- {t}")
        elif tag.name == "table":
            t = _table_to_markdown(tag)
            if t:
                body_parts.append(t)
        elif tag.name == "img":
            # content 画像 (計算表・別表・フローチャート) を選択的に保持。ナビ/装飾
            # (/template/ 配下の navi_*.png 等) は drop する (無差別保持は全チャンクに
            # ゴミを注入するため)。Why: 画像は法人税の計算例として意味を持つが alt
            # のみでは失われるため絶対 URL の markdown 画像で残す。
            src = tag.get("src", "")
            if src and "/template/" not in src:
                alt = _normalize_text(tag.get("alt") or "").strip() or "図表"
                body_parts.append(f"![{alt}]({urljoin(page_url, src)})")

    body = "\n".join(body_parts).strip()

    # 根拠法令等 raw text
    kikon_raw = ""
    for h2 in soup.find_all("h2"):
        if "根拠法令等" in h2.get_text():  # 根拠法令等
            nxt = h2.find_next_sibling()
            if nxt:
                kikon_raw = _normalize_text(nxt.get_text(strip=True))
            break

    # Extract related
    related_result = (
        extract_related_from_kikon(kikon_raw)
        if kikon_raw
        else {
            "related_articles": [],
            "related_directives": [],
            "unlinked": [],
        }
    )

    # related_qa from full HTML (関連コード section hrefs, R44)
    related_qa = extract_related_qa_from_html(text)

    # Build record via TaxAnswerChunk (type-safe IR)
    source_url = f"{SOURCE_URL_BASE}/{tax_category}/{code}.htm"
    record_id = f"hojin-taxanswer-{code}"

    return _build_chunk_record(
        record_id=record_id,
        code=code,
        title=title,
        body=body,
        version_date=version_date,
        related_articles=related_result["related_articles"],
        related_directives=related_result["related_directives"],
        unlinked_refs=related_result["unlinked"],
        related_qa=related_qa,
        kikon_raw=kikon_raw,
        source_url=source_url,
    )


def _build_chunk_record(
    *,
    record_id: str,
    code: str,
    title: str,
    body: str,
    version_date: str | None,
    related_articles: list[dict],
    related_directives: list[dict],
    unlinked_refs: list[dict],
    related_qa: list[str],
    kikon_raw: str,
    source_url: str,
) -> dict:
    """Validate via TaxAnswerChunk Pydantic model and return JSONL-ready dict.

    Why: Pydantic validation catches malformed related refs at parse time rather
    than silently propagating bad data into the corpus. Pipeline fields
    (segment_type / article_id / law_name_ja / law_name_ja_display / text) are
    merged after model_dump to keep them out of the semantic IR layer.
    """
    from juricode_shared.ir import (
        TaxAnswerArticleRef,
        TaxAnswerChunk,
        TaxAnswerDirectiveRef,
        TaxAnswerUnlinkedRef,
    )

    article_refs = [TaxAnswerArticleRef(**a) for a in related_articles]
    directive_refs = [TaxAnswerDirectiveRef(**d) for d in related_directives]
    unlinked_ref_models = [TaxAnswerUnlinkedRef(**u) for u in unlinked_refs]

    chunk = TaxAnswerChunk(
        id=record_id,
        code=code,
        title=title,
        body=body,
        version_date=version_date,
        related_articles=article_refs,
        related_directives=directive_refs,
        unlinked_refs=unlinked_ref_models,
        related_qa=related_qa,
        kikon_raw=kikon_raw,
        source_url=source_url,
        source_format=SOURCE_FORMAT,
        license=LICENSE,
        attribution=ATTRIBUTION,
    )

    # model_dump(mode="json") -> current json.dumps -> ensure key order matches original
    semantic = chunk.model_dump(mode="json")

    # Merge pipeline fields (retrieval pipeline convention, not part of semantic IR)
    pipeline: dict = {
        "segment_type": "taxanswer",
        "article_id": None,  # retrieve.py compatibility
        "law_name_ja": "タックスアンサー",  # タックスアンサー
        "law_name_ja_display": f"タックスアンサー No.{code}",
        "text": body,  # for corpus embedding
    }

    return {**semantic, **pipeline}


def _table_to_markdown(table_tag) -> str:
    """Convert <table> to Markdown. Fallback to plaintext on complex colspan/rowspan (R21/R28)."""
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    grid: list[list[str]] = []
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        row = [_normalize_text(c.get_text(separator=" ")).strip() for c in cells]
        grid.append(row)

    if not grid:
        return ""

    # Check for colspan/rowspan complexity
    has_span = any(
        c.get("colspan") or c.get("rowspan") for tr in rows for c in tr.find_all(["th", "td"])
    )
    if has_span:
        # Warn and use plaintext fallback (R28/R36)
        warnings.warn(
            "WARN: table with colspan/rowspan detected; using plaintext fallback (R28).",
            stacklevel=3,
        )
        return "\n".join(" | ".join(row) for row in grid)

    # Simple table -> Markdown
    col_count = max(len(r) for r in grid)
    # Pad rows
    for row in grid:
        while len(row) < col_count:
            row.append("")

    lines = []
    lines.append(" | ".join(grid[0]))
    lines.append(" | ".join(["---"] * col_count))
    for row in grid[1:]:
        lines.append(" | ".join(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse NTA TaxAnswer HTML -> JSONL chunks.")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("cache/taxanswer/hojin"),
        help="Directory containing cached .htm files.",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/chunks/hojin-taxanswer"),
        help="Output directory for JSONL chunk file.",
    )
    ap.add_argument(
        "--law-abbrev",
        default="hojin-taxanswer",
        help="Abbreviation for this QA set (used in id prefix).",
    )
    ap.add_argument(
        "--tax-category",
        default="hojin",
        help="Tax category path segment (e.g. 'hojin').",
    )
    ap.add_argument(
        "--glob-pattern",
        default="*.htm",
        help="Glob pattern to match HTML files.",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if not args.cache_dir.exists():
        print(f"ERROR: cache-dir not found: {args.cache_dir}", file=sys.stderr)
        return 1

    htm_files = sorted(args.cache_dir.glob(args.glob_pattern))
    if not htm_files:
        print(f"ERROR: no .htm files found in {args.cache_dir}", file=sys.stderr)
        return 1

    print(f"Parsing {len(htm_files)} HTML file(s) from {args.cache_dir}", file=sys.stderr)

    all_items: list[dict] = []
    seen_ids: set[str] = set()
    errors: list[str] = []
    unlinked_total = 0

    for htm_path in htm_files:
        # Extract code from filename (e.g. 5200.htm -> "5200", 5364-2.htm -> "5364-2").
        # Why: NTA は枝番コード (base-branch) を持つ (法人税で 5364-2 等 5 件)。base のみ
        # 許容する `^\d{4,5}$` だと枝番ファイルを SKIP して silent に落とすため、1 段の
        # 枝番を許容する。base と枝番のソートは _code_sort_key で数値順にする (int() 直
        # キャストは '5364-2' で ValueError)。
        code = htm_path.stem
        if not re.match(r"^\d{4,5}(?:-\d+)?$", code):
            print(f"  SKIP: unexpected filename {htm_path.name}", file=sys.stderr)
            continue

        try:
            item = parse_file(htm_path, code, args.tax_category)
        except Exception as e:
            msg = f"ERROR: failed to parse {htm_path.name}: {e}"
            print(msg, file=sys.stderr)
            errors.append(msg)
            continue

        rid = item["id"]
        if rid in seen_ids:
            print(f"  WARN: duplicate id {rid!r} from {htm_path.name}", file=sys.stderr)
            continue
        seen_ids.add(rid)
        all_items.append(item)
        unlinked_total += len(item.get("unlinked_refs", []))

        if args.verbose:
            arts = len(item["related_articles"])
            direcs = len(item["related_directives"])
            qa = len(item["related_qa"])
            unlinked = len(item.get("unlinked_refs", []))
            print(
                f"  {code}: articles={arts} directives={direcs} qa={qa} "
                f"unlinked={unlinked} body={len(item['body'])}chars",
                file=sys.stderr,
            )

    if not all_items:
        print("ERROR: no TaxAnswer items produced", file=sys.stderr)
        return 1

    # Sort by code (numeric, branch-aware). Why: int() on '5364-2' raises ValueError;
    # split base/branch so 5364 < 5364-2 < 5365 sorts as intended.
    all_items.sort(key=lambda x: _code_sort_key(x["code"]))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{args.law_abbrev}.taxanswer.chunks.jsonl"

    from juricode_shared.safe_write import safe_write_jsonl

    safe_write_jsonl(out_path, all_items)

    print(f"Written {len(all_items)} TaxAnswer chunks -> {out_path}", file=sys.stderr)
    print(f"Total unlinked refs: {unlinked_total}", file=sys.stderr)

    if unlinked_total > 0:
        print(
            "  (unlinked refs include amendment provisions and missing corpus entries)",
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

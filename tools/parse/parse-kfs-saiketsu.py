#!/usr/bin/env python3
"""parse-kfs-saiketsu.py -- KFS 公表裁決事例要旨リーフ HTML -> RulingReference (裁決) 群.

Usage:
    python tools/parse/parse-kfs-saiketsu.py \\
        --leaf-html cache/kfs/03/0204040000.html \\
        --issue-code 0204040000 \\
        --tax-item 法人税 \\
        --output-dir build/chunks/kfs-hojin \\
        --appendix build/chunks/kfs-hojin/appendix-0204040000.json

出力:
    <output-dir>/kfs-<issue_code>.saiketsu.jsonl  : 1 裁決 1 レコード (RulingReference + 解決詳細)
    <appendix>                                    : 佐藤 review 用の全裁決 全 field JSON (§7)

Why (パイプライン実証・法人税裁決パイロット・briefing 2026-07-04):
    国税不服審判所の公表裁決要旨 (PDL1.0) を IR の RulingReference (case_type=ruling) 化し、
    《参照条文等》ブロックのある裁決だけを参照条文へ link する (D1/D4)。要旨本文は原典忠実
    (byte 一致・§8)。link は「存在する条のみ」= 偽リンク 0 (corpus 実在ガード)。1 裁決が複数条を
    参照する場合は各条 md に複製 (denormalize・D2) するため、per-entry に link 対象条の集合を持つ。

    参照条文の表記は taxanswer (略号 法令54) と異なり **正式名＋第N条** (法人税法施行令第54条
    第1項) ゆえ、taxanswer resolver の LAW_PREFIX_MAP は直接使えない (2026-07-04 P0 実測)。本
    パーサは正式名→law_abbrev の専用マッパー (FULLNAME_LAW_MAP) を持ち、corpus 実在ガードのみ
    taxanswer と同型で流用する (佐藤裁定・専用マッパー / 地方税法もリンク)。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

# juricode_shared を import 可能にする (safe_write 経由でファイル書き込み)。
_SHARED_SRC = REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KFS_SERVICE_BASE = "https://www.kfs.go.jp/service"
CASE_TYPE = "ruling"
SOURCE_LICENSE = "pdl-1.0"  # 公表裁決要旨は PDL1.0 (docs/licensing.md)
SUMMARY_SOURCE = "official_pdl"  # 公表要旨をそのまま (要約は自前でなく公表要旨)
DEFAULT_RELEVANCE = "medium"  # D3: 機械 default。佐藤が high/low 補正

# 正式名 -> law_abbrev マッパー (差①・佐藤裁定 専用マッパー)。longest-prefix-first で照合する
# (法人税法施行令 は 法人税法 を接頭に含むため長い順に試す)。値は data/v0.2 の実ディレクトリ名。
FULLNAME_LAW_MAP: dict[str, str] = {
    "法人税法施行令": "houjin-zei-hou-shikkourei",  # 法人税法施行令
    "法人税法施行規則": "houjin-zei-hou-shikoukisoku",  # 法人税法施行規則
    "法人税法": "houjin-zei-hou",  # 法人税法
    "地方税法施行令": "chihou-zei-hou-shikkourei",  # 地方税法施行令
    "地方税法施行規則": "chihou-zei-hou-shikoukisoku",  # 地方税法施行規則
    "地方税法": "chihou-zei-hou",  # 地方税法 (差②・佐藤裁定 リンクする)
    # 相続税 bulk (MP/04・2026-07-04): 相続税法関係の 3 法令を純加算 (longest-first で照合)。
    "相続税法施行令": "souzoku-zei-hou-shikkourei",  # 相続税法施行令
    "相続税法施行規則": "souzoku-zei-hou-shikoukisoku",  # 相続税法施行規則
    "相続税法": "souzoku-zei-hou",  # 相続税法
    # 相続裁決の cross-law 参照 (dry-run で unresolved_law が surface・corpus 実在分のみ・2026-07-04)。
    # 偽リンク0: 民事訴訟法 等の未収録法令は追加せず忠実に非リンク。longest-first で照合。
    "国税通則法": "kokuzei-tsuusoku-hou",  # 国税通則法
    "借地借家法": "shakuchi-shakka-hou",  # 借地借家法
    "民法": "minpou",  # 民法
}

# 元号 -> 西暦 offset (§4)。era 明示の日付は offset 加算で確定 (元号跨ぎは月日でなく元号表記で判定
# 済ゆえ offset で十分)。元年 = year 1。昭和47=1972 / 平成24=2012 / 令和2=2020。
_ERA_OFFSET = {"昭和": 1925, "平成": 1988, "令和": 2018}

# 裁決日 (例 平成24年7月5日裁決)。元号名 + 年 + 月 + 日 + '裁決'。
_SAIKETSU_DATE_RE = re.compile(r"(昭和|平成|令和)\s*(元|\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日\s*裁決")
# 和暦日付 (「裁決」語を伴わない・例 平成26年7月28日)。最新形式の article_point アンカーが
# 日付のみで「裁決」を付けない事例があるため (bulk で 1 件検出・2026-07-07)。誤検出防止のため
# article_point アンカー全体との fullmatch にのみ使う (本文中の別日付を拾わない)。
_WAREKI_DATE_RE = re.compile(r"(昭和|平成|令和)\s*(元|\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")

# 空白除去 (要旨完全性監査の byte 照合用)。
_WS_RE = re.compile(r"\s")
# 完全性監査で照合する <li>/<td>/<th> の最小文字数 (見出し・記号セルの誤検出回避)。
_MIN_AUDIT_FRAG = 6
# 裁決事例集 No.X - Y頁 (article_point の掲載情報)。全角/半角ダッシュを許容。
# cp932-safe: ダッシュ類は Unicode escape で記す (U+2013/U+2014 等の literal は cp932-unsafe・FU-505)。
_SAIKETSU_NO_RE = re.compile(
    r"No\.\s*(\d+)\s*[\-\uff0d\u2010\u2212\u2013\u2014\u2015]\s*(\d+)\s*頁"
)
# permalink 相対 (../../JP/88/09/index.html) -> (巻号, 通番)。
_PERMALINK_RE = re.compile(r"JP/(\d+)/(\d+)/index\.html")

# 第N条(のM)* 第K項 (参照条文の条番号)。号は relevant_paragraph に使わない。
_ARTICLE_RE = re.compile(r"第(\d+(?:の\d+)*)条(?:第(\d+)項)?")

# ダッシュ類 -> ASCII '-' (通達番号 7－3－16の2 の正規化)。cp932-safe: Unicode escape 使用。
_BAR_RE = re.compile(r"[\-\uff0d\u2010\u2013\u2014\u2015\u30fc\u2212]")


def _normalize_bars(s: str) -> str:
    return _BAR_RE.sub("-", s)


# ---------------------------------------------------------------------------
# 和暦 -> 西暦 (§4)
# ---------------------------------------------------------------------------


def wareki_to_iso(era: str, year_raw: str, month: int, day: int) -> str:
    """和暦 (元号/年/月/日) を ISO (YYYY-MM-DD) へ変換する.

    Why: KFS の裁決日は和暦表記 (平成24年7月5日)。IR の decision_date は date ゆえ西暦に確定する。
    元年 (year_raw='元') は 1 とする。元号は明示されるため offset 加算で一意 (昭和64=平成元=1989
    のような跨ぎは元号名で既に区別済)。
    """
    if era not in _ERA_OFFSET:
        raise ValueError(f"unknown era: {era!r}")
    year = 1 if year_raw == "元" else int(year_raw)
    seireki = _ERA_OFFSET[era] + year
    return f"{seireki:04d}-{month:02d}-{day:02d}"


def _parse_saiketsu_date(text: str) -> str | None:
    """テキストから最初の裁決日 (和暦) を ISO で返す。無ければ None。"""
    m = _SAIKETSU_DATE_RE.search(text)
    if not m:
        return None
    era, year_raw, month, day = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
    return wareki_to_iso(era, year_raw, month, day)


# ---------------------------------------------------------------------------
# 参照条文 (《参照条文等》) 解決: 正式名マッパー + corpus 実在ガード
# ---------------------------------------------------------------------------

# corpus 実在ガード用の article_id 集合 (data/v0.2)。tests は本 global を直接注入して hermetic 化
# する (_SOCHI_CORPUS_IDS と同型・taxanswer 流用)。data/v0.2 は gitignore 対象外ゆえ CI でも実在。
_ARTICLE_CORPUS: set[str] | None = None


def _load_article_corpus() -> set[str]:
    """FULLNAME_LAW_MAP の全 law_abbrev の article_id を data/v0.2 から集合で返す (実在ガード).

    Why: 生成した article_id を照合し、corpus に無い条へは link しない (偽リンク 0・corpus_gap)。
    filename `<abbrev>-article-<N>.md` から article_id `<abbrev>-art-<N>` を機械導出する
    (frontmatter を開かずファイル名だけで O(1)・parse-egov と同じ命名規約)。
    """
    global _ARTICLE_CORPUS
    if _ARTICLE_CORPUS is not None:
        return _ARTICLE_CORPUS
    ids: set[str] = set()
    data_root = REPO_ROOT / "data" / "v0.2"
    if data_root.exists():
        wanted = set(FULLNAME_LAW_MAP.values())
        for law_dir in data_root.glob("*/*"):
            if not law_dir.is_dir() or law_dir.name not in wanted:
                continue
            for md in law_dir.glob(f"{law_dir.name}-article-*.md"):
                # <abbrev>-article-<N>.md -> <abbrev>-art-<N>
                stem = md.stem  # houjin-zei-hou-shikkourei-article-54
                ids.add(stem.replace("-article-", "-art-", 1))
    _ARTICLE_CORPUS = ids
    return ids


def _match_law_fullname(line: str) -> tuple[str, str] | None:
    """行頭の正式法令名を longest-first で照合し (matched_name, law_abbrev) を返す。無ければ None。"""
    for name in sorted(FULLNAME_LAW_MAP, key=len, reverse=True):
        if line.startswith(name):
            return name, FULLNAME_LAW_MAP[name]
    return None


def resolve_sanshou_jouken(lines: list[str]) -> dict:
    """《参照条文等》の各行を link / tag / unlinked に分類する (D1/D2/偽リンク0).

    Args:
        lines: 《参照条文等》ブロックの各行 (マーカ除去済・例 ['法人税法施行令第54条',
            '法人税基本通達7-3-16の2', '地方税法第343条'])。

    Returns:
        dict: {
          "links": [{raw, law_abbrev, article_id, relevant_paragraph|None}],  # corpus 実在の条のみ
          "tags": [str],                                                      # 参照通達:... (D1)
          "unlinked": [{raw, reason}],                                        # corpus_gap / unresolved
        }
    """
    from juricode_shared.text_norm import normalize_fullwidth_digits

    corpus = _load_article_corpus()
    links: list[dict] = []
    tags: list[str] = []
    unlinked: list[dict] = []

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        # D1: 通達 (基本通達等) は link せず tags に記録する。
        if "通達" in raw:
            tags.append(f"参照通達:{_normalize_bars(raw)}")
            continue

        matched = _match_law_fullname(raw)
        if matched is None:
            # 正式名マッパーに無い法令 (未知) -> 偽リンクを作らず記録のみ。
            unlinked.append({"raw": raw, "reason": "unresolved_law"})
            continue
        name, law_abbrev = matched

        # 全角数字を ASCII 化してから条番号を抽出する (相続裁決は 第２条 等の全角表記があり、
        # 非正規化だと article_id が art-２ になって corpus 実在ガードで偽陰性 corpus_gap になる・
        # 2026-07-04 実測)。ASCII 表記 (法人税) には無影響 = no-op。
        am = _ARTICLE_RE.search(normalize_fullwidth_digits(raw[len(name) :]))
        if am is None:
            unlinked.append({"raw": raw, "reason": "no_article_number"})
            continue
        art_num = am.group(1).replace("の", "-")  # 54 / 54の2 -> 54 / 54-2
        paragraph = int(am.group(2)) if am.group(2) else None
        article_id = f"{law_abbrev}-art-{art_num}"

        if article_id not in corpus:
            # 存在しない条 -> dangling link にせず記録 (corpus_gap・偽リンク0 ゲート)。
            warnings.warn(f"WARN: {raw!r} -> {article_id} not in corpus. Unlinked.", stacklevel=2)
            unlinked.append({"raw": raw, "reason": "corpus_gap"})
            continue

        links.append(
            {
                "raw": raw,
                "law_abbrev": law_abbrev,
                "article_id": article_id,
                "relevant_paragraph": paragraph,
            }
        )

    return {"links": links, "tags": tags, "unlinked": unlinked}


# ---------------------------------------------------------------------------
# エントリ (裁決) 抽出
# ---------------------------------------------------------------------------

_MARKER_YOUSHI = "《要旨》"  # 《要旨》
_MARKER_SANSHOU = "《参照条文等》"  # 《参照条文等》
_MARKER_SANKO = "《参考判決・裁決》"  # 《参考判決・裁決》 (引用エッジ・cited_refs)


def _extract_marker_block(article_div, marker: str) -> list[str] | None:
    """div.article 内で marker で始まる <p> を探し、marker を除いた各行 (<br> 区切り) を返す。

    Why: 《参照条文等》/《要旨》は <p class="marginT1em"> に 'marker<br>　行<br>　行' 形で入る
    (2026-07-04 P0 実測)。get_text('\n') で <br> を改行に落とし、marker 行を除去する。
    """
    for p in article_div.find_all("p"):
        text = p.get_text("\n")
        if text.lstrip().startswith(marker):
            raw_lines = text.split("\n")
            out: list[str] = []
            for ln in raw_lines:
                ln = ln.strip().lstrip("　").strip()
                if not ln or ln == marker:
                    continue
                out.append(ln)
            return out
    return None


_BODY_BLOCK_TAGS = ["p", "ol", "ul", "table", "dl"]


def _clean_body_text(text: str) -> str:
    """複数行テキストの各行から先頭全角空白/前後空白を除き、空行を落として \n 連結する。"""
    lines = [ln.strip().lstrip("　").strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _top_level_blocks(article_div) -> list:
    """div.article 内の最上位本文ブロック (<p>/<ol>/<ul>/<table>/<dl>) を document 順で返す.

    Why: <p> だけ走査すると番号付き grounds を持つ <ol>/<table> を落とす (bulk で 15 件・
    2026-07-07)。入れ子ブロック (例 <td> 内 <p>) は最上位祖先の get_text で拾われるため、
    ブロック祖先を持つ要素は除外して二重計上を防ぐ (recursive=False より入れ子に頑健)。
    """
    blocks = []
    for el in article_div.find_all(_BODY_BLOCK_TAGS):
        if el.find_parent(_BODY_BLOCK_TAGS) is not None:
            continue  # 別ブロックの入れ子 -> 祖先側で拾う
        blocks.append(el)
    return blocks


def _extract_summary(article_div, article_point) -> str:
    """要旨本文 (summary_ja) を byte 忠実に抽出する (§8).

    新しい裁決は 《要旨》<p>、古い裁決は article_point 直後の本文ブロック群 (<p> だけでなく
    <ol>/<ul>/<table>/<dl> の番号付き grounds も含む・裁決日行/《...》マーカ除く)。
    """
    youshi = _extract_marker_block(article_div, _MARKER_YOUSHI)
    if youshi is not None:
        return "\n".join(youshi).strip()
    # 古い裁決: div 直下の本文ブロックを document 順に集める (list/table も対象)。
    parts: list[str] = []
    for el in _top_level_blocks(article_div):
        if el is article_point:
            continue
        cls = el.get("class") or []
        if "article_point" in cls or "article_date" in cls:
            continue
        text = el.get_text("\n").strip()
        if not text or text.startswith("《"):
            continue
        # 単独の裁決日行 (例 '昭和47年5月12日裁決') は本文でない。
        if _SAIKETSU_DATE_RE.fullmatch(text.replace("　", "").replace("\n", "").strip()):
            continue
        parts.append(_clean_body_text(text))
    return "\n".join(parts).strip()


def audit_summary_completeness(article_div, summary_ja: str | None) -> list[str]:
    """summary_ja が <ol>/<ul>/<table>/<dl> の grounds を取りこぼしていないか監査する.

    Why (2026-07-07 佐藤補強②): byte substring 監査は「中間 drop」しか検知できず、末尾/先頭の
    list/table drop を見逃した (bulk で 15 件素通し = 検証ハーネス自体の穴)。抽出ロジックとは
    独立に、原典の各 <li>/<td>/<th> テキストが summary_ja に内包されるかを直接照合し、抽出が
    将来壊れても loud に落ちるようにする (次税目 bulk での同クラス drop 再発防止)。

    Returns: 取りこぼした grounds テキストの list (空 = 完全)。
    """
    summ_norm = _WS_RE.sub("", summary_ja or "")
    missing: list[str] = []
    for cell in article_div.find_all(["li", "td", "th"]):
        frag = _WS_RE.sub("", cell.get_text(""))
        if len(frag) >= _MIN_AUDIT_FRAG and frag not in summ_norm:
            missing.append(cell.get_text(" ", strip=True))
    return missing


def parse_leaf(html_bytes: bytes, issue_code: str, tax_item: str, leaf_path: str) -> list[dict]:
    """リーフ HTML (raw bytes) から全裁決の RulingReference (+ 解決詳細) を昇順で返す.

    Args:
        leaf_path: リーフの service/ 以下の正式パス (例 'MP/03/0204040000')。permalink なしの古い
            裁決の url アンカー基底に使う。**issue_code から導出しない** - 先頭セグメント (MP/03 の
            03=法人税関係カテゴリ) は争点コード (0204040000) と無関係ゆえ (2026-07-04 P0 実測)。

    Why raw bytes: KFS は Shift_JIS。charset を検出して per-file デコードし、要旨を byte 忠実に
    保つ (再エンコードの非可逆変換を避ける)。
    """
    enc = _detect_charset(html_bytes)
    text = html_bytes.decode(enc, errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    leaf_url = f"{KFS_SERVICE_BASE}/{leaf_path}.html"  # provenance URL の基底 (アンカー用)

    entries: list[dict] = []
    for h2 in soup.find_all("h2", class_="likeH3"):
        title = h2.get_text(strip=True)
        h2_id = h2.get("id") or ""
        article_div = h2.find_next("div", class_="article")
        if article_div is None:
            continue
        article_point = article_div.find("p", class_="article_point")
        ap_text = article_point.get_text(" ", strip=True) if article_point else ""

        # permalink (巻号/通番) を article_point のアンカーから取る。
        maki = tsuu = None
        if article_point:
            a = article_point.find("a", href=True)
            if a:
                pm = _PERMALINK_RE.search(a["href"])
                if pm:
                    maki, tsuu = int(pm.group(1)), int(pm.group(2))

        # 裁決日: article_point (新しい裁決は日付アンカー) を優先し、無ければ div 全体から拾う
        # (古い裁決は末尾に単独日付 <p>)。《参考判決・裁決》の別日付を拾わないため article_point
        # -> 単独日付 <p> の順で探し、div 全体の search は最後の手段にしない。
        decision_date = _parse_saiketsu_date(ap_text)
        if decision_date is None and article_point is not None:
            # 最新形式: article_point アンカーが日付のみ (「裁決」語なし・例 平成26年7月28日)。
            # アンカー全体との fullmatch に限定し本文中の別日付を拾わない (bulk で 1 件・2026-07-07)。
            anchor = article_point.find("a")
            anchor_text = anchor.get_text(strip=True).replace("　", "") if anchor else ""
            am_date = _WAREKI_DATE_RE.fullmatch(anchor_text)
            if am_date:
                decision_date = wareki_to_iso(
                    am_date.group(1), am_date.group(2), int(am_date.group(3)), int(am_date.group(4))
                )
        if decision_date is None:
            for p in article_div.find_all("p"):
                if p is article_point:
                    continue
                ptext = p.get_text(strip=True)
                if _SAIKETSU_DATE_RE.fullmatch(ptext) and "参考" not in ptext:
                    decision_date = _parse_saiketsu_date(ptext)
                    break

        # 裁決事例集 No.X - Y頁 (article_point テキスト)。新しい裁決 (88/92) は非掲載 -> None。
        saiketsu_ref = None
        no_from_text = page_from_text = None
        nom = _SAIKETSU_NO_RE.search(ap_text)
        if nom:
            no_from_text, page_from_text = int(nom.group(1)), int(nom.group(2))
            saiketsu_ref = f"No.{no_from_text}-{page_from_text}頁"

        # case_id: permalink あり = 巻号+通番、無し = No+頁 (§5)。
        no = maki if maki is not None else no_from_text
        suffix = tsuu if tsuu is not None else page_from_text
        case_id = None
        if decision_date and no is not None and suffix is not None:
            case_id = f"ntt-{decision_date}-j{no}-{suffix}"

        # url: permalink あり = permalink、無し = リーフ URL + アンカー (h2 id)。
        if maki is not None:
            url = f"{KFS_SERVICE_BASE}/JP/{maki}/{tsuu:02d}/index.html"
        elif h2_id:
            url = f"{leaf_url}#{h2_id}"
        else:
            url = leaf_url

        summary_ja = _extract_summary(article_div, article_point)
        # 完全性監査 (補強②): 抽出とは独立に <li>/<td>/<th> grounds の取りこぼしを検出する。
        summary_missing = audit_summary_completeness(article_div, summary_ja)

        # 《参照条文等》 (D1/D2/D4)。無い裁決は metadata のみ (link しない)。
        sanshou_lines = _extract_marker_block(article_div, _MARKER_SANSHOU)
        has_sanshou = sanshou_lines is not None
        resolved = resolve_sanshou_jouken(sanshou_lines or [])

        # 《参考判決・裁決》= 引用エッジ (cited_refs)。今回は raw 保持 (case_id 解決は後段 FU・
        # briefing §8)。判決参照は ntt- 化不能・裁決参照も曖昧ゆえ忠実取込に留める。
        cited_refs = _extract_marker_block(article_div, _MARKER_SANKO) or []

        entries.append(
            {
                "case_id": case_id,
                "case_type": CASE_TYPE,
                "decision_date": decision_date,
                "url": url,
                "relevance": DEFAULT_RELEVANCE,
                "source_license": SOURCE_LICENSE,
                "summary_source": SUMMARY_SOURCE,
                "case_name_ja": title,
                "summary_ja": summary_ja,
                "saiketsu_ref": saiketsu_ref,
                "issue_code": issue_code,
                "tax_item": tax_item,
                "tags": list(resolved["tags"]),
                # --- 内部 (review + 条文 md 付与用・schema field ではない) ---
                "_h2_id": h2_id,
                "_has_sanshou": has_sanshou,
                "_links": resolved["links"],
                "_unlinked": resolved["unlinked"],
                "_summary_missing": summary_missing,
                "_cited_refs": cited_refs,
            }
        )
    return entries


def _detect_charset(raw: bytes) -> str:
    m = re.search(rb"charset=([^\s\"';>]+)", raw[:2000], re.I)
    if m:
        enc = m.group(1).decode("ascii", errors="replace").strip().lower()
        if enc in ("shift_jis", "shift-jis", "sjis", "x-sjis"):
            return "cp932"
        return enc
    return "cp932"  # KFS は Shift_JIS が既定


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from juricode_shared import safe_write_jsonl, safe_write_text

    parser = argparse.ArgumentParser(
        description="Parse KFS 裁決要旨 leaf -> RulingReference JSONL."
    )
    parser.add_argument("--leaf-html", required=True, help="リーフ HTML の cache パス。")
    parser.add_argument(
        "--leaf-path",
        required=True,
        help="リーフの service/ 以下の正式パス (例 MP/03/0204040000)。",
    )
    parser.add_argument(
        "--issue-code", default=None, help="争点コード (既定は --leaf-path の末尾セグメント)。"
    )
    parser.add_argument("--tax-item", default="法人税", help="税目 (既定 法人税)。")
    parser.add_argument("--output-dir", required=True, help="JSONL 出力先ディレクトリ。")
    parser.add_argument(
        "--appendix", default=None, help="佐藤 review 用 付録 JSON の出力先 (任意)。"
    )
    args = parser.parse_args(argv)

    issue_code = args.issue_code or args.leaf_path.rsplit("/", 1)[-1]
    html_bytes = Path(args.leaf_html).read_bytes()
    entries = parse_leaf(html_bytes, issue_code, args.tax_item, args.leaf_path)

    out_dir = Path(args.output_dir)
    jsonl_path = out_dir / f"kfs-{issue_code}.saiketsu.jsonl"
    safe_write_jsonl(jsonl_path, entries)

    n_link = sum(1 for e in entries if e["_has_sanshou"])
    n_targets = sum(len(e["_links"]) for e in entries)
    print(f"parsed {len(entries)} 裁決 -> {jsonl_path}")
    print(f"  《参照条文等》あり: {n_link} 裁決 / link 対象条 (denormalize 前): {n_targets}")

    if args.appendix:
        safe_write_text(
            Path(args.appendix), json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
        )
        print(f"  付録 JSON (佐藤 review 用): {args.appendix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

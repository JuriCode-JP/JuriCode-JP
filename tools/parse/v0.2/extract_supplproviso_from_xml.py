#!/usr/bin/env python3
"""extract_supplproviso_from_xml.py -- e-Gov XML から附則 (SupplProvision) を抽出 v2.

ご提示の設計 (4 観点) に基づく:
  1. 構造ベースのチャンク化: Article (or Paragraph) 単位
  2. メタデータ豊富化: target_main_articles, topic, amend_law_num 等
  3. Parent-Child: 子 chunk (Paragraph) + 親 rollup chunk (SupplProvision 全体)
  4. 元号 -> 西暦変換 (前処理の一部、enforcement_date 推定)

出力: build/chunks/{law}/{law}-supplproviso.chunks.jsonl (flat 配置)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

# tools/shared/src を sys.path に追加して juricode_shared を import 可能にする
_SHARED_SRC = Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import safe_write_jsonl  # noqa: E402, I001  (must follow sys.path tweak)


# ============================================================
# 法令名マッピング (v0.1 .md frontmatter から動的構築)
# ============================================================
# Fix 3: ハードコーディング 30 法令 -> data/{phase}/{law}/ の v0.1 .md から動的取得
# Note: build_law_id_to_name_ja() を main() で呼び出して埋める


def build_law_id_to_name_ja(data_dir: Path) -> dict[str, str]:
    """各法令の law_id -> law_name_ja を v0.1 .md frontmatter から取得.

    全 43 法令 (含む新規 fetch した 5 法令) を網羅。
    """
    out: dict[str, str] = {}
    for phase_dir in data_dir.iterdir():
        if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
            continue
        for law_dir in phase_dir.iterdir():
            if not law_dir.is_dir():
                continue
            mds = sorted(law_dir.glob("*-article-*.md"))
            if not mds:
                continue
            try:
                with mds[0].open(encoding="utf-8") as fh:
                    law_id = None
                    law_name = None
                    for line in fh:
                        s = line.rstrip("\n")
                        if s == "---" and (law_id or law_name):
                            break
                        m = re.match(r"^law_id:\s*([A-Z0-9_]+)", s)
                        if m:
                            law_id = m.group(1)
                            continue
                        m = re.match(r"^law_name_ja:\s*['\"]?(.+?)['\"]?$", s)
                        if m:
                            law_name = m.group(1).strip()
                    if law_id and law_name:
                        out[law_id] = law_name
            except Exception:
                continue
    return out


# 起動時に main() で初期化される (default は空 dict)
LAW_NAME_JA: dict[str, str] = {}


# ============================================================
# 元号 -> 西暦変換
# ============================================================

ERA_OFFSET = {
    "明治": 1867,
    "大正": 1911,
    "昭和": 1925,
    "平成": 1988,
    "令和": 2018,
}

KANSUJI_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def kansuji_to_int(s: str) -> int | None:
    """漢数字を int に変換. 「二〇」=20, 「一〇〇」=100, 「二二」=22.

    注意: e-Gov の AmendLawNum では位取り表記 (一二三 = 123) が多い。
    十百千を含む場合と位取りの両方に対応。
    """
    if not s:
        return None
    s = s.strip()
    # 純粋な数字なら直接
    if s.isdigit():
        return int(s)
    # 位取り (一二三) のみの場合
    if all(c in KANSUJI_DIGITS for c in s):
        digits = "".join(str(KANSUJI_DIGITS[c]) for c in s)
        try:
            return int(digits)
        except ValueError:
            return None
    # 十百千を含む場合 (簡易、〜万まで)
    total = 0
    current = 0
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    for ch in s:
        if ch in KANSUJI_DIGITS:
            current = current * 10 + KANSUJI_DIGITS[ch] if current else KANSUJI_DIGITS[ch]
        elif ch in unit_map:
            unit = unit_map[ch]
            current = current if current else 1
            total += current * unit
            current = 0
        else:
            # 想定外の文字 -> 中止
            return None
    total += current
    return total if total > 0 else None


# AmendLawNum 解析パターン: 「(元号)(年)年(月)月(日)日(法令種別)第(号)号」
# 例: "昭和二二年一〇月二六日法律第一二四号"
#     "令和七年法律第二十六号" (日付なし型)
#
# FU-304: literal alternation で 7 種の法令種別のみマッチ。旧 regex の
# `[^第]*第N号` は greedy match で「雑種」のような未対応 prefix まで
# 法令番号として吸い込んでいた。対象種別を明示することで、現状未対応の
# ものは law_num = None として下流で安全に弾けるようにする。
AMEND_LAW_NUM_PATTERN = re.compile(
    r"(明治|大正|昭和|平成|令和)([零〇一二三四五六七八九十百千万\d]+)年"
    r"(?:([零〇一二三四五六七八九十百千万\d]+)月([零〇一二三四五六七八九十百千万\d]+)日)?"
    r"(?:(?:法律|政令|規則|省令|府令|告示|条約)第([零〇一二三四五六七八九十百千万\d]+)号)?"
)


def parse_amend_law_num(amend_str: str) -> dict:
    """改正法令番号から年月日と法令番号を抽出. 失敗時は空 dict.

    返却例 (フル):
        {"era": "昭和", "year_gengo": 22, "year_seireki": 1947,
         "month": 10, "day": 26, "law_num": "124"}
    """
    if not amend_str:
        return {}
    m = AMEND_LAW_NUM_PATTERN.search(amend_str)
    if not m:
        return {}
    era = m.group(1)
    year_str = m.group(2)
    month_str = m.group(3)
    day_str = m.group(4)
    num_str = m.group(5)

    year_gengo = kansuji_to_int(year_str)
    if year_gengo is None:
        return {}

    out: dict = {"era": era, "year_gengo": year_gengo}
    offset = ERA_OFFSET.get(era)
    if offset:
        out["year_seireki"] = offset + year_gengo

    if month_str:
        month = kansuji_to_int(month_str)
        if month and 1 <= month <= 12:
            out["month"] = month
    if day_str:
        day = kansuji_to_int(day_str)
        if day and 1 <= day <= 31:
            out["day"] = day
    if num_str:
        num = kansuji_to_int(num_str)
        if num:
            out["law_num"] = str(num)
    return out


def make_enforcement_date(amend_info: dict) -> str | None:
    """amend_info から ISO date string を作成. 月日不明なら None."""
    y = amend_info.get("year_seireki")
    m = amend_info.get("month")
    d = amend_info.get("day")
    if not (y and m and d):
        return None
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def classify_effective_status(
    enforcement_date_str: str | None, amend_year_seireki: int | None
) -> str:
    """effective_status を判定.

    - current: 直近 5 年以内に施行
    - historical: 5 年以上前 (経過措置が今も生きている可能性あり)
    - unknown: 日付不明
    """
    if enforcement_date_str:
        try:
            y, m, d = (int(x) for x in enforcement_date_str.split("-"))
            enforce = date(y, m, d)
            today = date.today()
            delta_days = (today - enforce).days
            if delta_days < 0:
                return "future"
            return "current" if delta_days < 365 * 5 else "historical"
        except (ValueError, AttributeError):
            pass
    if amend_year_seireki:
        today = date.today()
        if today.year - amend_year_seireki < 5:
            return "current"
        return "historical"
    return "unknown"


# ============================================================
# Topic 分類
# ============================================================

TOPIC_FROM_CAPTION = [
    ("施行期日", ["施行期日", "施行日"]),
    ("経過措置", ["経過措置", "経過規定"]),
    ("罰則の適用", ["罰則の適用", "罰則"]),
    ("検討規定", ["検討", "見直し"]),
    ("適用区分", ["適用区分", "適用関係", "適用する場合", "適用しない場合"]),
    ("読替規定", ["読替え", "読み替え"]),
    ("税制特例", ["特例", "特別措置"]),
]


def detect_topic_from_caption(caption: str) -> str:
    """ArticleCaption から topic を判定."""
    if not caption:
        return "unspecified"
    for topic, keywords in TOPIC_FROM_CAPTION:
        for kw in keywords:
            if kw in caption:
                return topic
    return "unspecified"


def detect_topic_from_text(text: str) -> str:
    """text 内容から topic を heuristic 判定 (caption 無い old style 用)."""
    if not text:
        return "unspecified"
    # 施行期日
    if any(
        p in text
        for p in ["公布の日から起算して", "から施行する", "から、これを施行する", "から施行"]
    ):
        if not any(p in text for p in ["については、なお", "経過措置"]):
            return "施行期日"
    # 経過措置
    if any(
        p in text for p in ["なお従前の例による", "については、この法律施行前", "については、新法"]
    ):
        return "経過措置"
    # 罰則
    if "罰則の適用" in text or "の刑に処する" in text:
        return "罰則の適用"
    # 検討規定
    if "検討を加え" in text or "を踏まえ、必要な措置を講ずる" in text:
        return "検討規定"
    # 適用
    if "の規定は、" in text and ("適用" in text):
        return "適用区分"
    return "unspecified"


# ============================================================
# target_main_articles 抽出
# ============================================================

# 本則条文参照パターン (漢数字 + 算用数字対応、枝番ノ/の対応)
MAIN_ARTICLE_REF_PATTERN = re.compile(
    r"第[零〇一二三四五六七八九十百千万\d]+条"
    r"(?:[ノの][零〇一二三四五六七八九十百千万\d]+)?"
    r"(?:第[零〇一二三四五六七八九十百千万\d]+項)?"
    r"(?:第[零〇一二三四五六七八九十百千万\d]+号)?"
)


def extract_main_article_refs(text: str) -> list[str]:
    """text から本則条文参照を抽出 (生表記、重複排除、出現順保持)."""
    if not text:
        return []
    matches = MAIN_ARTICLE_REF_PATTERN.findall(text)
    seen = set()
    out = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


# Fix 4: 表記揺れ正規化 -- 「第二十六条第二項」 -> article_id "{law}-art-26"
NORMALIZE_REF_PATTERN = re.compile(
    r"^第([零〇一二三四五六七八九十百千万\d]+)条"
    r"(?:[ノの]([零〇一二三四五六七八九十百千万\d]+))?"
    r"(?:第([零〇一二三四五六七八九十百千万\d]+)項)?"
    r"(?:第([零〇一二三四五六七八九十百千万\d]+)号)?$"
)


def normalize_article_ref(ref: str) -> dict | None:
    """生表記「第二十六条第二項」を正規化された dict に変換.

    Returns:
        {'article_number': '26', 'paragraph_number': 2, 'item_number': None}
        失敗時は None
    """
    if not ref:
        return None
    m = NORMALIZE_REF_PATTERN.match(ref.strip())
    if not m:
        return None
    art_num = kansuji_to_int(m.group(1))
    sub_num = kansuji_to_int(m.group(2)) if m.group(2) else None
    para_num = kansuji_to_int(m.group(3)) if m.group(3) else None
    item_num = kansuji_to_int(m.group(4)) if m.group(4) else None
    if art_num is None:
        return None
    # article_number string (枝番付き対応)
    art_num_str = f"{art_num}-{sub_num}" if sub_num else str(art_num)
    out: dict = {"article_number": art_num_str}
    if para_num is not None:
        out["paragraph_number"] = para_num
    if item_num is not None:
        out["item_number"] = item_num
    return out


def build_target_article_ids(text: str, law_abbrev: str) -> list[str]:
    """text 内の本則参照 -> article_id 形式に正規化したリスト.

    例: 「第二十六条第二項...第三十四条ノ二の改正...」 (law: keihou) ->
        ["keihou-art-26", "keihou-art-34-2"]
    """
    refs = extract_main_article_refs(text)
    seen = set()
    out = []
    for ref in refs:
        n = normalize_article_ref(ref)
        if not n:
            continue
        aid = f"{law_abbrev}-art-{n['article_number']}"
        if aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


# ============================================================
# XML utilities
# ============================================================


def get_text_recursive(elem) -> str:
    """Element の全 text content を recursive に結合 (Rt は skip)."""
    if elem is None:
        return ""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag == "Rt":
            continue
        parts.append(get_text_recursive(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def normalize_caption(caption: str) -> str:
    """「（〜）」を剥いて中身だけ返す."""
    if not caption:
        return ""
    return re.sub(r"^[\(（](.+?)[\)）]$", r"\1", caption.strip()).strip()


# ============================================================
# law_abbrev -> law_id mapping
# ============================================================


def build_law_abbrev_to_id_phase(data_dir: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for phase_dir in data_dir.iterdir():
        if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
            continue
        for law_dir in phase_dir.iterdir():
            if not law_dir.is_dir():
                continue
            mds = sorted(law_dir.glob("*-article-*.md"))
            if not mds:
                continue
            try:
                with mds[0].open(encoding="utf-8") as fh:
                    for line in fh:
                        m = re.match(r"^law_id:\s*([A-Z0-9_]+)", line.strip())
                        if m:
                            out[law_dir.name] = (m.group(1), phase_dir.name)
                            break
            except Exception:
                continue
    return out


# ============================================================
# Chunk 構築
# ============================================================

MAX_TEXT_LEN = 6000  # Gemini embedding 8192 tokens の安全マージン


def make_chunk(
    chunk_id: str,
    text: str,
    segment_type: str,
    law_abbrev: str,
    law_id: str,
    law_name_ja: str,
    sp_idx: int,
    sp_label: str,
    amend_law_num: str,
    amend_info: dict,
    enforcement_date: str | None,
    effective_status: str,
    article_number: str | None,
    article_caption: str | None,
    paragraph_number: int | None,
    topic: str,
    target_main_articles_raw: list[str],
    target_main_article_ids: list[str],
) -> dict:
    """SupplProvision chunk を作る."""
    # text 長さ制限
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN] + "…"
    chunk: dict = {
        "id": chunk_id,
        "segment_type": segment_type,
        "modality": "unspecified",
        "law_id": law_id,
        "law_name_ja": law_name_ja,
        "law_abbrev": law_abbrev,
        "supplproviso_id": sp_idx,
        "supplproviso_label": sp_label,
        "amend_law_num": amend_law_num or None,
        "topic": topic,
        "text": text,
    }
    # amend_info 展開
    if amend_info:
        chunk["amend_era"] = amend_info.get("era")
        chunk["amend_year_gengo"] = amend_info.get("year_gengo")
        chunk["amend_year_seireki"] = amend_info.get("year_seireki")
        if "month" in amend_info:
            chunk["amend_month"] = amend_info["month"]
        if "day" in amend_info:
            chunk["amend_day"] = amend_info["day"]
        if "law_num" in amend_info:
            chunk["amend_law_num_int"] = amend_info["law_num"]
    if enforcement_date:
        chunk["enforcement_date"] = enforcement_date
    chunk["effective_status"] = effective_status
    if article_number is not None:
        chunk["supplproviso_article_number"] = article_number
    if article_caption:
        chunk["supplproviso_article_caption"] = article_caption
    if paragraph_number is not None:
        chunk["paragraph_number"] = paragraph_number
    if target_main_articles_raw:
        chunk["target_main_articles_raw"] = target_main_articles_raw
    if target_main_article_ids:
        chunk["target_main_article_ids"] = target_main_article_ids
    return chunk


# ============================================================
# 1 XML から SupplProvision chunks を抽出
# ============================================================


def extract_supplproviso_chunks(
    xml_path: Path,
    law_abbrev: str,
    law_id: str,
) -> list[dict]:
    try:
        tree = ET.parse(xml_path)
    except Exception as e:
        print(f"WARN: XML parse error for {xml_path}: {e}", file=sys.stderr)
        return []
    root = tree.getroot()
    law_name_ja = LAW_NAME_JA.get(law_id, "")
    chunks: list[dict] = []

    for sp_idx, sp in enumerate(root.iter("SupplProvision"), 1):
        # 共通 metadata
        amend_law_num = sp.get("AmendLawNum", "")
        amend_info = parse_amend_law_num(amend_law_num)
        enforcement_date = make_enforcement_date(amend_info)
        eff_status = classify_effective_status(enforcement_date, amend_info.get("year_seireki"))
        sp_label_elem = sp.find("SupplProvisionLabel")
        sp_label = get_text_recursive(sp_label_elem).strip() if sp_label_elem is not None else ""

        sp_paragraphs_added = 0

        # --- Old style: SupplProvision の直接子 <Paragraph> ---
        # findall は直接子のみ (iter とは違う)
        direct_paragraphs = sp.findall("Paragraph")
        for p_idx, para in enumerate(direct_paragraphs, 1):
            text = get_text_recursive(para).strip()
            if not text:
                continue
            topic = detect_topic_from_text(text)
            targets_raw = extract_main_article_refs(text)
            target_ids = build_target_article_ids(text, law_abbrev)
            chunk_id = f"{law_abbrev}-supplproviso-{sp_idx}-p{p_idx}"
            chunk = make_chunk(
                chunk_id=chunk_id,
                text=text,
                segment_type="supplproviso",
                law_abbrev=law_abbrev,
                law_id=law_id,
                law_name_ja=law_name_ja,
                sp_idx=sp_idx,
                sp_label=sp_label,
                amend_law_num=amend_law_num,
                amend_info=amend_info,
                enforcement_date=enforcement_date,
                effective_status=eff_status,
                article_number=None,
                article_caption=None,
                paragraph_number=p_idx,
                topic=topic,
                target_main_articles_raw=targets_raw,
                target_main_article_ids=target_ids,
            )
            chunks.append(chunk)
            sp_paragraphs_added += 1

        # --- New style: SupplProvision > Article > Paragraph ---
        for art in sp.findall("Article"):
            art_num = art.get("Num", "")
            cap_elem = art.find("ArticleCaption")
            art_caption_raw = get_text_recursive(cap_elem).strip() if cap_elem is not None else ""
            art_caption = normalize_caption(art_caption_raw)
            topic_from_cap = detect_topic_from_caption(art_caption)

            art_paragraphs = art.findall("Paragraph")
            for p_idx, para in enumerate(art_paragraphs, 1):
                text = get_text_recursive(para).strip()
                if not text:
                    continue
                topic = (
                    topic_from_cap
                    if topic_from_cap != "unspecified"
                    else detect_topic_from_text(text)
                )
                targets_raw = extract_main_article_refs(text)
                target_ids = build_target_article_ids(text, law_abbrev)
                chunk_id = f"{law_abbrev}-supplproviso-{sp_idx}-art{art_num}-p{p_idx}"
                chunk = make_chunk(
                    chunk_id=chunk_id,
                    text=text,
                    segment_type="supplproviso",
                    law_abbrev=law_abbrev,
                    law_id=law_id,
                    law_name_ja=law_name_ja,
                    sp_idx=sp_idx,
                    sp_label=sp_label,
                    amend_law_num=amend_law_num,
                    amend_info=amend_info,
                    enforcement_date=enforcement_date,
                    effective_status=eff_status,
                    article_number=art_num,
                    article_caption=art_caption,
                    paragraph_number=p_idx,
                    topic=topic,
                    target_main_articles_raw=targets_raw,
                    target_main_article_ids=target_ids,
                )
                chunks.append(chunk)
                sp_paragraphs_added += 1

        # --- Rollup chunk: SupplProvision 全体 ---
        # 子 chunk が 1 つも作れなかった場合は rollup 不要
        if sp_paragraphs_added == 0:
            continue
        rollup_text = get_text_recursive(sp).strip()
        if not rollup_text:
            continue
        rollup_chunk = make_chunk(
            chunk_id=f"{law_abbrev}-supplproviso-{sp_idx}-rollup",
            text=rollup_text,
            segment_type="supplproviso_rollup",
            law_abbrev=law_abbrev,
            law_id=law_id,
            law_name_ja=law_name_ja,
            sp_idx=sp_idx,
            sp_label=sp_label,
            amend_law_num=amend_law_num,
            amend_info=amend_info,
            enforcement_date=enforcement_date,
            effective_status=eff_status,
            article_number=None,
            article_caption=None,
            paragraph_number=None,
            topic="rollup",
            target_main_articles_raw=extract_main_article_refs(rollup_text),
            target_main_article_ids=build_target_article_ids(rollup_text, law_abbrev),
        )
        chunks.append(rollup_chunk)

    return chunks


# ============================================================
# main
# ============================================================


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--law-only", default=None, help="特定 law_abbrev のみ (テスト用)")
    args = ap.parse_args()

    print("Building law_abbrev -> (law_id, phase) map ...", file=sys.stderr)
    law_map = build_law_abbrev_to_id_phase(args.data_dir)
    print(f"  {len(law_map)} laws found in data/", file=sys.stderr)

    # Fix 3: LAW_NAME_JA を v0.1 frontmatter から動的構築 (全 43 法令対応)
    print("Building law_id -> law_name_ja map (Fix 3) ...", file=sys.stderr)
    global LAW_NAME_JA
    LAW_NAME_JA = build_law_id_to_name_ja(args.data_dir)
    print(f"  {len(LAW_NAME_JA)} law_name entries built", file=sys.stderr)

    if args.law_only:
        if args.law_only not in law_map:
            sys.exit(f"ERROR: law_abbrev not found: {args.law_only}")
        law_map = {args.law_only: law_map[args.law_only]}

    total_chunks = 0
    total_rollup = 0
    laws_processed = 0
    laws_skipped_no_xml: list[tuple[str, str]] = []
    chunks_per_law: dict[str, int] = {}
    topic_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for law_abbrev, (law_id, _phase) in sorted(law_map.items()):
        xml_path = args.xml_dir / f"{law_id}.xml"
        if not xml_path.exists():
            laws_skipped_no_xml.append((law_abbrev, law_id))
            continue
        chunks = extract_supplproviso_chunks(xml_path, law_abbrev, law_id)
        if not chunks:
            continue
        laws_processed += 1
        chunks_per_law[law_abbrev] = len(chunks)
        for c in chunks:
            topic_counts[c.get("topic", "unspecified")] += 1
            status_counts[c.get("effective_status", "unknown")] += 1
            if c.get("segment_type") == "supplproviso_rollup":
                total_rollup += 1
        total_chunks += len(chunks)

        # 出力: flat 配置で build/chunks/{law}/{law}-supplproviso.chunks.jsonl
        out_dir = args.chunks_dir / law_abbrev
        out_file = out_dir / f"{law_abbrev}-supplproviso.chunks.jsonl"
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            # FU-302: safe_write_jsonl で atomic write + 各レコード json.loads 検証.
            # 既存事故 (a) WSL ruff corruption / (b) NUL padding の再発防止.
            safe_write_jsonl(out_file, chunks)

    # ---- Summary ----
    print("\n=== Summary ===", file=sys.stderr)
    print(f"Laws processed:           {laws_processed}", file=sys.stderr)
    print(f"Laws skipped (no XML):    {len(laws_skipped_no_xml)}", file=sys.stderr)
    for abbrev, lid in laws_skipped_no_xml:
        print(f"  - {abbrev}: {lid}", file=sys.stderr)
    print(f"Total chunks (子+rollup): {total_chunks}", file=sys.stderr)
    print(f"  rollup chunks:          {total_rollup}", file=sys.stderr)
    print(f"  子 chunks:              {total_chunks - total_rollup}", file=sys.stderr)
    print("\nTopic distribution:", file=sys.stderr)
    for t, c in topic_counts.most_common():
        print(f"  {t:15s}: {c}", file=sys.stderr)
    print("\nEffective status distribution:", file=sys.stderr)
    for s, c in status_counts.most_common():
        print(f"  {s:15s}: {c}", file=sys.stderr)
    print("\nTop 10 laws by chunk count:", file=sys.stderr)
    for law, n in sorted(chunks_per_law.items(), key=lambda x: -x[1])[:10]:
        print(f"  {law:35s}: {n}", file=sys.stderr)
    if args.dry_run:
        print("\n(dry-run, no files written)", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

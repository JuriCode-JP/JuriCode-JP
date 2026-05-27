#!/usr/bin/env python3
"""convert-lawqa-to-evalset.py -- デジタル庁 lawqa_jp を JuriCode-JP eval-set 形式に変換.

入力:
    selection.json (lawqa_jp の元データ, PDL 1.0 ライセンス)
    https://github.com/digital-go-jp/lawqa_jp

出力:
    data/eval-set/commercial-kinsho.jsonl   (金商法系問題)
    data/eval-set/pharma.jsonl              (薬機法系問題)
    data/eval-set/real-estate.jsonl         (借地借家法問題)
    data/eval-set/lawqa-jp-other.jsonl      (その他 / 法令未マップ)

各エントリ形式 (既存 eval-set 互換 + lawqa_jp 出典明示):
{
  "id": "eval-kinsho-001",
  "category": "commercial-kinsho",
  "question": "(問題文 + 選択肢を統合した自然言語クエリ)",
  "expected_article_ids": ["kinsho-hou-art-5", "kinsho-hou-art-5-6"],
  "relevance": "high",
  "difficulty": "medium",
  "topic_tags": [...],
  "notes": "...",
  "source": "Digital Agency lawqa_jp",
  "source_license": "PDL 1.0 (CC BY 4.0 compatible)",
  "source_url": "https://github.com/digital-go-jp/lawqa_jp",
  "original_file_name": "金商法_第2章_選択式_関連法令_問題番号57",
  "original_choices": "a ~\\nb ~\\nc ~\\nd ~",
  "original_correct_choice": "c"
}

使い方:
    python tools/embed/convert-lawqa-to-evalset.py \
        --input <path-to-selection.json> \
        --output-dir data/eval-set/ \
        --law-id-map tools/fetch-egov/src/fetch_egov/law_id_map.py

ライセンス出典必須:
    PDL 1.0: https://www.digital.go.jp/resources/open_data/public_data_license_v1.0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 法令名 → JuriCode-JP 略称マッピング (lawqa_jp の law_list.json 内の title を逆引き)
LAW_NAME_TO_ABBREV: dict[str, str] = {
    "金融商品取引法": "kinsho-hou",
    "金融商品取引法施行令": "kinsho-hou-shikkourei",
    "企業内容等の開示に関する内閣府令": "kigyou-kaiji-furei",
    "発行者以外の者による株券等の公開買付けの開示に関する内閣府令": "koukai-kaitsuke-furei",
    "金融商品取引法第二条に規定する定義に関する内閣府令": "kinsho-teigi-furei",
    "金融商品取引法第六章の二の規定による課徴金に関する内閣府令": "kinsho-kachoukin-furei",
    "金融商品取引業等に関する内閣府令": "kinsho-gyou-furei",
    "有価証券の取引等の規制に関する内閣府令": "yuukashouken-kisei-furei",
    "証券情報等の提供又は公表に関する内閣府令": "shouken-jouhou-furei",
    "金融商品取引法第二章の六の規定による重要情報の公表に関する内閣府令": "juuyou-jouhou-furei",
    "借地借家法": "shakuchi-shakka-hou",
    "医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律": "yakkihou",
    "医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律施行規則": "yakkihou-shikoukisoku",
}

# 法令ファイル名 → カテゴリ
ABBREV_TO_CATEGORY: dict[str, str] = {
    "kinsho-hou": "commercial-kinsho",
    "kinsho-hou-shikkourei": "commercial-kinsho",
    "kigyou-kaiji-furei": "commercial-kinsho",
    "koukai-kaitsuke-furei": "commercial-kinsho",
    "kinsho-teigi-furei": "commercial-kinsho",
    "kinsho-kachoukin-furei": "commercial-kinsho",
    "kinsho-gyou-furei": "commercial-kinsho",
    "yuukashouken-kisei-furei": "commercial-kinsho",
    "shouken-jouhou-furei": "commercial-kinsho",
    "juuyou-jouhou-furei": "commercial-kinsho",
    "shakuchi-shakka-hou": "real-estate",
    "yakkihou": "pharma",
    "yakkihou-shikoukisoku": "pharma",
}

# 漢数字 → アラビア数字 (簡易版、本格的には日本語数値パーサ要)
KANJI_DIGIT = {
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


def kanji_to_int(s: str) -> int | None:
    """漢数字を整数に変換. 「百二十三」→ 123 など複合形対応."""
    if not s:
        return None
    # 全角数字対応
    s_normalized = s.translate(
        str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789")
    )
    if s_normalized.isdigit():
        return int(s_normalized)

    # 簡易漢数字変換
    total = 0
    current = 0
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    for ch in s:
        if ch in KANJI_DIGIT:
            current = current * 10 + KANJI_DIGIT[ch] if current else KANJI_DIGIT[ch]
        elif ch in unit_map:
            unit = unit_map[ch]
            current = current if current else 1
            total += current * unit
            current = 0
    total += current
    return total if total > 0 else None


def _normalize_digits(s: str) -> str:
    """全角数字を半角に変換."""
    return s.translate(
        str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789")
    )


def parse_article_number(text: str) -> str | None:
    """「第5条」「第三条」「第5条の2」を「5」「3」「5-2」に変換 (全角・半角・漢数字対応)."""
    # 全角数字を含む可能性があるため、まず正規化前の値をキャプチャ
    # 第N条 or 第N条のM (N, M はアラビア数字 / 全角数字)
    m = re.search(r"第\s*([\d0-9]+)\s*条(?:の\s*([\d0-9]+))?", text)
    if m:
        main = _normalize_digits(m.group(1))
        if m.group(2):
            sub = _normalize_digits(m.group(2))
            return f"{main}-{sub}"
        return main
    # 漢数字版: 第三条 or 第三条の二
    m = re.search(
        r"第\s*([〇一二三四五六七八九十百千万]+)\s*条(?:の\s*([〇一二三四五六七八九十百千万]+))?",
        text,
    )
    if m:
        main_num = kanji_to_int(m.group(1))
        sub_num = kanji_to_int(m.group(2)) if m.group(2) else None
        if main_num is not None:
            if sub_num is not None:
                return f"{main_num}-{sub_num}"
            return str(main_num)
    return None


def extract_article_refs_from_context(context: str) -> list[tuple[str, str]]:
    """コンテキストから (法令略称, 条番号) ペアのリストを抽出.

    Markdown の見出し構造:
        ## 法令名
        ### 第N条
        #### 第M項
    から複数の article_id を取り出す.
    """
    results = []
    current_law_abbrev = None

    for line in context.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            # 法令名行
            law_name = line_stripped[3:].strip()
            current_law_abbrev = LAW_NAME_TO_ABBREV.get(law_name)
            if current_law_abbrev is None:
                # 部分一致を試行
                for known_name, abbrev in LAW_NAME_TO_ABBREV.items():
                    if known_name in law_name or law_name in known_name:
                        current_law_abbrev = abbrev
                        break
        elif line_stripped.startswith("### ") and current_law_abbrev:
            # 条番号行
            art_num = parse_article_number(line_stripped)
            if art_num:
                results.append((current_law_abbrev, art_num))

    # 重複除去 (順序保持)
    seen = set()
    unique = []
    for pair in results:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def determine_category(refs: list[tuple[str, str]]) -> str:
    """主要参照法令からカテゴリを決定."""
    if not refs:
        return "lawqa-jp-other"
    # 最初の法令から決定
    first_abbrev = refs[0][0]
    return ABBREV_TO_CATEGORY.get(first_abbrev, "lawqa-jp-other")


def build_eval_entry(orig: dict, idx: int) -> tuple[str, dict]:
    """lawqa_jp の 1 エントリを eval-set 形式に変換.

    Returns:
        (category, eval_entry_dict)
    """
    context = orig.get("コンテキスト", "")
    question = orig.get("問題文", "")
    choices = orig.get("選択肢", "")
    answer = orig.get("output", "")
    references = orig.get("references", [])
    file_name = orig.get("ファイル名", f"unknown-{idx}")

    # 条文 ID 抽出
    refs = extract_article_refs_from_context(context)
    expected_article_ids = [f"{abbrev}-art-{num}" for abbrev, num in refs]

    category = determine_category(refs)

    # 質問形式に再構成 (問題文 + 選択肢で自然言語クエリにする)
    # ただし retrieval 評価では「正解条文を引けるか」が目的なので、選択肢は補助的にプロンプトに添えるのみ
    natural_query = question.strip()

    # 一意 ID 生成
    entry_id = f"eval-{category}-{idx:03d}"

    entry = {
        "id": entry_id,
        "category": category,
        "question": natural_query,
        "expected_article_ids": expected_article_ids,
        "relevance": "high" if expected_article_ids else "unknown",
        "difficulty": "medium",  # lawqa_jp 全体が中難度想定
        "topic_tags": [refs[0][0]] if refs else [],
        "notes": "Converted from Digital Agency lawqa_jp. References extracted from Context Markdown headings.",
        "source": "Digital Agency lawqa_jp",
        "source_license": "PDL 1.0 (CC BY 4.0 compatible)",
        "source_url": "https://github.com/digital-go-jp/lawqa_jp",
        "original_file_name": file_name,
        "original_choices": choices,
        "original_correct_choice": answer,
        "original_references": references,
    }
    return category, entry


def main():
    ap = argparse.ArgumentParser(
        description="Convert lawqa_jp selection.json to JuriCode-JP eval-set format."
    )
    ap.add_argument("--input", type=Path, required=True, help="Path to lawqa_jp selection.json")
    ap.add_argument(
        "--output-dir", type=Path, required=True, help="Output directory for jsonl files"
    )
    ap.add_argument("--dry-run", action="store_true", help="Print stats without writing files")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"ERROR: input not found: {args.input}")

    with args.input.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        sys.exit(f"ERROR: expected JSON array, got {type(data).__name__}")

    print(f"Loaded {len(data)} entries from {args.input}")

    # カテゴリ別バケット
    buckets: dict[str, list[dict]] = {}
    unmapped_count = 0
    no_refs_count = 0

    for idx, orig in enumerate(data, 1):
        category, entry = build_eval_entry(orig, idx)
        if not entry["expected_article_ids"]:
            no_refs_count += 1
        if category == "lawqa-jp-other":
            unmapped_count += 1
        buckets.setdefault(category, []).append(entry)

    print("\n=== Distribution ===")
    for cat, entries in sorted(buckets.items()):
        with_refs = sum(1 for e in entries if e["expected_article_ids"])
        print(f"  {cat:30s} : {len(entries):3d} entries ({with_refs} with article refs)")
    print(f"  TOTAL                          : {len(data)} entries")
    print(f"  Unmapped (other category)      : {unmapped_count}")
    print(f"  No article refs extracted      : {no_refs_count}")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for cat, entries in buckets.items():
        out_path = args.output_dir / f"{cat}.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"  Wrote {out_path} ({len(entries)} entries)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

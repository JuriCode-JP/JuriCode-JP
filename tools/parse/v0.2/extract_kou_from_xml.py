#!/usr/bin/env python3
"""extract_kou_from_xml.py — e-Gov XML から各号 (Item) content を抽出.

v0.1 parser がスキップしていた各号 content を補完。
existing build/chunks/{law}/{law}-article-{N}.chunks.jsonl に append.

設計:
  - 入力: cache/laws/{law_id}.xml と law_abbrev → law_id mapping
  - 抽出: Article > Paragraph > Item を全て segment 化
  - 出力: 既存 .chunks.jsonl に append (重複は item_id でスキップ)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET


# 法令名 ja マッピング (簡易)
LAW_NAME_JA = {
    "129AC0000000089": "民法",
    "140AC0000000045": "刑法",
    "132AC0000000048": "商法",
    "417AC0000000086": "会社法",
    "322AC0000000067": "地方自治法",
    "323AC0000000131": "刑事訴訟法",
    "323AC0000000136": "警察官職務執行法",
    "329AC0000000162": "警察法",
    "405AC0000000088": "行政手続法",
    "426AC0000000068": "行政不服審査法",
    "323AC0000000039": "軽犯罪法",
    "412AC0100000081": "ストーカー行為等の規制等に関する法律",
    "335AC0000000105": "道路交通法",
    "323AC0000000122": "風俗営業等の規制及び業務の適正化等に関する法律",
    "419AC0000000022": "犯罪による収益の移転防止に関する法律",
    "337AC0000000066": "国税通則法",
    "340AC0000000034": "法人税法",
    "340AC0000000033": "所得税法",
    "363AC0000000108": "消費税法",
    "325AC0000000073": "相続税法",
    "325AC0000000226": "地方税法",
    "322AC0000000054": "私的独占の禁止及び公正取引の確保に関する法律",
    "415AC0000000057": "個人情報保護法",
    "421AC0000000066": "公文書等の管理に関する法律",
    "411AC0000000042": "行政機関の保有する情報の公開に関する法律",
    "322AC0000000120": "国家公務員法",
    "325AC0000000261": "地方公務員法",
    "503AC0000000035": "デジタル社会形成基本法",
    "322AC0000000049": "労働基準法",
    "321CONSTITUTION": "日本国憲法",
    "323AC0000000025": "金融商品取引法",
}


# law_abbrev → law_id mapping (data ディレクトリの phase/law/ から構築)
def build_law_abbrev_to_id_phase(data_dir: Path) -> dict[str, tuple[str, str]]:
    """各 phase/law から先頭 .md を読んで law_id と phase を取る."""
    out: dict[str, tuple[str, str]] = {}
    for phase_dir in data_dir.iterdir():
        if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
            continue
        for law_dir in phase_dir.iterdir():
            if not law_dir.is_dir():
                continue
            # 先頭 .md ファイルから law_id を読む
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


def get_text_recursive(elem) -> str:
    """Element の全 text content を recursive に結合."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        # Ruby 等は内部 Rt をスキップして本文のみ
        if child.tag == "Rt":
            continue
        parts.append(get_text_recursive(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def extract_kou_chunks(
    xml_path: Path,
    law_abbrev: str,
    law_id: str,
    phase: str,
) -> list[dict]:
    """1 つの XML から各号 chunk を全て抽出."""
    try:
        tree = ET.parse(xml_path)
    except Exception as e:
        print(f"WARN: XML parse error for {xml_path}: {e}", file=sys.stderr)
        return []
    root = tree.getroot()

    law_name_ja = LAW_NAME_JA.get(law_id, "")
    chunks: list[dict] = []

    # 編・章・節・款の階層追跡用 (XML 階層を辿る)
    def find_section_path(article_elem) -> dict:
        """Article の祖先から Part/Chapter/Section/Subsection を集める."""
        path = {}
        node = article_elem
        # ElementTree は親情報を持たないので、別途 parent map を作る必要があるが、
        # ここでは簡易的に空でも OK (parent_section は augmentation 用)
        return path

    for article in root.iter("Article"):
        article_num = article.get("Num", "")
        if not article_num:
            continue
        # article_number を v0.1 形式に合わせる (例: "1-2" 等は維持)
        article_id = f"{law_abbrev}-art-{article_num}"

        article_caption_elem = article.find("ArticleCaption")
        article_caption = ""
        if article_caption_elem is not None:
            cap_text = get_text_recursive(article_caption_elem).strip()
            # 「（〜）」を剥く
            cap_text = re.sub(r"^[\(（](.*)[\)）]$", r"\1", cap_text).strip()
            article_caption = cap_text

        for paragraph in article.findall("Paragraph"):
            para_num_str = paragraph.get("Num", "1")
            try:
                para_num = int(para_num_str)
            except ValueError:
                para_num = 1

            # この段落内の Item を全て収集
            items = paragraph.findall("Item")
            if not items:
                continue

            for item in items:
                item_num_str = item.get("Num", "")
                try:
                    item_num = int(item_num_str)
                except ValueError:
                    continue
                # ItemSentence からテキストを取る
                item_sentence = item.find("ItemSentence")
                text = ""
                if item_sentence is not None:
                    sentences = item_sentence.findall("Sentence")
                    if sentences:
                        text = "".join(get_text_recursive(s) for s in sentences).strip()
                    else:
                        text = get_text_recursive(item_sentence).strip()

                # Subitem1 も結合 (ある場合)
                subitems = item.findall("Subitem1")
                if subitems:
                    sub_texts = []
                    for sub in subitems:
                        sub_title = sub.find("Subitem1Title")
                        sub_sentence = sub.find("Subitem1Sentence")
                        sub_t = ""
                        if sub_title is not None:
                            sub_t += get_text_recursive(sub_title).strip() + " "
                        if sub_sentence is not None:
                            sub_t += get_text_recursive(sub_sentence).strip()
                        if sub_t:
                            sub_texts.append(sub_t)
                    if sub_texts:
                        text += "\n" + "\n".join(sub_texts)

                if not text:
                    continue

                chunk_id = f"{article_id}-p{para_num}-kou-{item_num}"
                chunk = {
                    "id": chunk_id,
                    "article_id": article_id,
                    "law_id": law_id,
                    "law_name_ja": law_name_ja,
                    "article_number": article_num,
                    "paragraph_number": para_num,
                    "segment_type": "kou",
                    "modality": "unspecified",  # 号本文は通常文末で判定
                    "item_number": item_num,
                    "text": text,
                }
                chunks.append(chunk)

    return chunks


def detect_modality_from_text(text: str) -> str:
    """簡易 modality 判定 (segment_parser.py と一貫させる)."""
    text = text.strip()
    if text.endswith("この限りでない。") or text.endswith("妨げない。"):
        return "jogai"
    if text.endswith("することができる。") or text.endswith("ができる。"):
        return "kanou_kenri"
    if text.endswith("することができない。") or text.endswith("できない。"):
        return "kanou_negative"
    if text.endswith("しなければならない。") or text.endswith("するものとする。") or text.endswith("とする。"):
        return "gimu"
    if text.endswith("無効とする。"):
        return "koka_mukou"
    if text.endswith("取り消すことができる。"):
        return "koka_torikeshi"
    if text.endswith("処する。"):
        return "gimu_kei"
    if text.endswith("をいう。") or text.endswith("という。"):
        return "teigi"
    return "unspecified"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--law-only", default=None,
                    help="特定の law_abbrev だけ処理 (テスト用)")
    args = ap.parse_args()

    print(f"Building law_abbrev -> (law_id, phase) map ...", file=sys.stderr)
    law_map = build_law_abbrev_to_id_phase(args.data_dir)
    print(f"  {len(law_map)} laws found in data/", file=sys.stderr)

    if args.law_only:
        law_map = {args.law_only: law_map.get(args.law_only)}
        if law_map[args.law_only] is None:
            sys.exit(f"ERROR: law_abbrev not found: {args.law_only}")

    total_chunks = 0
    laws_processed = 0
    laws_skipped_no_xml = []
    new_chunks_per_law: dict[str, int] = {}

    for law_abbrev, (law_id, phase) in sorted(law_map.items()):
        xml_path = args.xml_dir / f"{law_id}.xml"
        if not xml_path.exists():
            laws_skipped_no_xml.append((law_abbrev, law_id))
            continue

        chunks = extract_kou_chunks(xml_path, law_abbrev, law_id, phase)
        # modality を文末から検出
        for c in chunks:
            c["modality"] = detect_modality_from_text(c["text"])

        if not chunks:
            continue

        laws_processed += 1
        new_chunks_per_law[law_abbrev] = len(chunks)

        # article_id 別に grouping して既存 .chunks.jsonl に append
        from collections import defaultdict
        by_article: dict[str, list[dict]] = defaultdict(list)
        for c in chunks:
            by_article[c["article_id"]].append(c)

        for article_id, art_chunks in by_article.items():
            # article_id は "{law}-art-{N}" 形式、ファイル名は "{law}-article-{N}.chunks.jsonl"
            article_num_part = article_id.replace(f"{law_abbrev}-art-", "")
            chunk_file = args.chunks_dir / law_abbrev / f"{law_abbrev}-article-{article_num_part}.chunks.jsonl"
            if not chunk_file.exists():
                # 親が存在しない条 (Article XML にあるが v0.1 .md なし) はスキップ
                continue
            # 既存の chunk_id を読み込んで重複防止
            existing_ids = set()
            with chunk_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        existing_ids.add(d.get("id"))
                    except Exception:
                        continue

            # parent_section を既存 chunk からコピー
            parent_section = None
            with chunk_file.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                        parent_section = d.get("parent_section")
                        if parent_section:
                            break
                    except Exception:
                        continue

            if not args.dry_run:
                with chunk_file.open("a", encoding="utf-8") as fh:
                    for c in art_chunks:
                        if c["id"] in existing_ids:
                            continue
                        if parent_section:
                            c["parent_section"] = parent_section
                        fh.write(json.dumps(c, ensure_ascii=False) + "\n")
                        total_chunks += 1

    print(f"\n=== Summary ===", file=sys.stderr)
    print(f"Laws processed: {laws_processed}", file=sys.stderr)
    print(f"Laws skipped (no XML): {len(laws_skipped_no_xml)}", file=sys.stderr)
    for abbrev, lid in laws_skipped_no_xml:
        print(f"  - {abbrev}: {lid}", file=sys.stderr)
    print(f"Total kou chunks added: {total_chunks}", file=sys.stderr)
    print(f"\nTop 10 laws by kou chunks added:", file=sys.stderr)
    for law, n in sorted(new_chunks_per_law.items(), key=lambda x: -x[1])[:10]:
        print(f"  {law:35s}: {n}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
 added:", file=sys.stderr)
    for law, n in sorted(new_chunks_per_law.items(), key=lambda x: -x[1])[:10]:
        print(f"  {law:35s}: {n}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

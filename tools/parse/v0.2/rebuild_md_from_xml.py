#!/usr/bin/env python3
"""rebuild_md_from_xml.py -- 正本 md の `## 原文 (日本語)` を e-Gov XML から作り直す.

責務 (1 ファイル 1 責務):
    「e-Gov XML の 1 条」→「その条の md の 原文セクション本文 ＋ frontmatter.paragraphs[]」
    を生成し、**それ以外の md 内容は 1 文字も触らない**。

Why 「parse-egov.py を再実行する」ではなく in-place rebuild なのか (★重要):
    parse-egov.py は md を新規生成するツールで、`cases: []` / `amendments: []` を
    毎回書き出す (parse-egov.py:344-345)。素直に再実行すると **人手で積み上げた
    判例リンク 276 条分・改正履歴 380 条分が消える**。よって本ツールは既存 md を
    読み、frontmatter の curated フィールドと 原文セクション以降 (英訳・判例リンク・
    改正履歴・注記) を保存したまま、原文セクションと paragraphs[] だけを差し替える。

何が変わるか (format-spec §5.2 = 案A):
    1. **号 (Item) と細別 (Subitem1..N) の本文が入る** -- 従来は
       parse-egov.py:233 が ParagraphSentence/Sentence しか拾わず、正本から
       号 41,621 / 細別 16,609 unit が丸ごと欠落していた。
    2. **内部マーカー `<!-- segment: ... -->` を本文に入れない** -- segment の
       メタデータは frontmatter の paragraphs[].segments[] が正本。
    3. **表を XML の文書順の位置に置く** -- 従来の emit_table_md は「項の末尾」に
       付けていたため、号の中の表が項末尾に飛んで順序が崩れていた。
    4. **List / SupplNote (罰則付記) を落とさない**。

不変条件 (これが崩れたら実装が間違い):
    - 空白畳み込み後、生成した本文 == XML の条文本文 (G0-a exact)。
      構造の表現に空白と項見出しと GFM 区切り行しか使わないので自明に成立する。
    - 各 segment の text は本文の部分列 (G0-c)。
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

    print(
        "RuntimeWarning: defusedxml 不在、stdlib ElementTree に fallback",
        file=sys.stderr,
    )

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pip install pyyaml")

_HERE = Path(__file__).resolve().parent  # tools/parse/v0.2
_PARSE_DIR = _HERE.parent  # tools/parse
_SHARED_SRC = _PARSE_DIR.parent / "shared" / "src"
for _p in (str(_HERE), str(_PARSE_DIR), str(_SHARED_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from juricode_shared import safe_write_text  # noqa: E402
from juricode_shared.headings import JA_SECTION_RE  # noqa: E402
from segment_parser import (  # noqa: E402
    Segment,
    detect_modality,
    split_paragraph_segments,
)
from table_core import table_to_grid_safe  # noqa: E402

# 全角スペース = 案A で階層を表す唯一の構造文字 (半角だとコードブロック誤認)。
IDEO_SPACE = "　"

# XML の整形用改行 + インデント (要素間の tail text)。本文の一部ではないので落とす。
# Why: e-Gov XML は pretty-print されており、<Column><Sentence>…</Sentence></Column> の
# 間に改行と空白が入る。extract_all_text は tail を拾うため、そのまま書くと
# 「一　国内\n      \n      この法律の施行地をいう。」のような本文になる。
_XML_PRETTY_WS = re.compile(r"\s*\n\s*")


def _load_parse_egov():
    """parse-egov.py (ハイフン名) を確立パターンで import する."""
    spec = importlib.util.spec_from_file_location(
        "_rebuild_parse_egov", _PARSE_DIR / "parse-egov.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_rebuild_parse_egov"] = mod
    spec.loader.exec_module(mod)
    return mod


_parse_egov = _load_parse_egov()
extract_all_text = _parse_egov.extract_all_text
int_to_kansuji = _parse_egov._int_to_kansuji


# ============================================================
# XML -> 原文セクション本文 (案A)
# ============================================================


def _text(elem: Any) -> str:
    """要素の全テキスト (XML の整形用改行・インデントを除去)."""
    if elem is None:
        return ""
    return _XML_PRETTY_WS.sub("", extract_all_text(elem)).strip()


def sentences_text(elem: Any) -> str:
    """*Sentence 要素 (ParagraphSentence / ItemSentence / SubitemNSentence) の本文.

    Why Column を分けるか: 定義規定の号は `<ItemSentence><Column><Sentence>国内</Sentence>
    </Column><Column><Sentence>この法律の施行地をいう。</Sentence></Column></ItemSentence>`
    という 2 カラム構造を取る。カラムは版面上「一　国内　この法律の施行地をいう。」と
    全角スペースで区切られるので、ここでも全角スペースで繋ぐ (区切りは空白のみ＝
    空白畳み込み後の XML 一致を壊さない)。カラム内の複数 Sentence (本文＋ただし書) は
    原文どおり連結する (parse-egov.py:236 と同じ)。
    """
    if elem is None:
        return ""
    columns = elem.findall("Column")
    if columns:
        return IDEO_SPACE.join(
            filter(None, ("".join(_text(s) for s in c.findall("Sentence")) for c in columns))
        )
    sents = elem.findall("Sentence")
    if sents:
        return "".join(_text(s) for s in sents)
    return _text(elem)


def _gfm_block(grid: list[list[str]]) -> list[str]:
    """グリッドを GFM 表の行リストにする (emit_table_md.build_gfm_block と同形)."""
    if not grid:
        return []
    ncols = max(len(r) for r in grid)
    rows = [r + [""] * (ncols - len(r)) for r in grid]
    lines = ["| " + " | ".join(r) + " |" for r in rows]
    return [lines[0], "| " + " | ".join(["---"] * ncols) + " |", *lines[1:]]


def _render_table(ts: Any, indent: str = "") -> list[str]:
    """TableStruct を (題名 ＋ GFM 表) の行群にする.

    Why 題名を出すか: `TableStructTitle` (「別表第一」等) は原文の一部。旧 emit_table_md は
    grid しか出さず題名を落としていた (合成テストで検出)。落とすと G0-a が exact にならない。
    """
    grid = table_to_grid_safe(ts)
    if not grid:
        return []
    lines: list[str] = []
    title = _text(ts.find("TableStructTitle"))
    if title:
        lines.extend(["", f"{indent}{title}"])
    lines.extend(["", *_gfm_block(grid)])
    return lines


def _render_item(elem: Any, depth: int) -> list[str]:
    """Item / SubitemN を案A の行群にする (文書順・再帰).

    depth 0 = 号 (段付けなし)、depth 1.. = 細別 (全角スペース × depth の段付け)。
    """
    tag = elem.tag
    title_tag, sent_tag = f"{tag}Title", f"{tag}Sentence"
    indent = IDEO_SPACE * depth
    title = ""
    lines: list[str] = []
    for child in elem:
        ct = child.tag
        if ct == title_tag:
            title = _text(child)
        elif ct == sent_tag:
            text = sentences_text(child)
            head = f"{indent}{title}{IDEO_SPACE}{text}" if title else f"{indent}{text}"
            lines.extend(["", head])
        elif ct == "TableStruct":
            lines.extend(_render_table(child, indent))
        elif ct == "List":
            lines.extend(["", f"{indent}{_text(child)}"])
        elif ct.startswith("Subitem"):
            lines.extend(_render_item(child, depth + 1))
    return lines


def render_paragraph_body(para: Any) -> str:
    """1 つの Paragraph を案A の本文テキストにする (文書順)."""
    lines: list[str] = []
    for child in para:
        tag = child.tag
        if tag in ("ParagraphNum", "ParagraphCaption"):
            continue  # 項番号は見出しへ写像、キャプションは本文でない
        if tag == "ParagraphSentence":
            text = sentences_text(child)
            if text:
                lines.append(text)
        elif tag == "Item":
            lines.extend(_render_item(child, 0))
        elif tag == "TableStruct":
            lines.extend(_render_table(child))
        elif tag == "List":
            lines.extend(["", _text(child)])
        else:
            text = _text(child)
            if text:
                lines.extend(["", text])
    return "\n".join(lines).strip("\n")


def paragraph_sentence_text(para: Any) -> str:
    """Paragraph の 柱書/本文 (ParagraphSentence) のみのテキスト.

    Why 分けるか: segment 分割 (hashira / tadashi / junyou / tokusoku) は従来どおり
    「項の本文」に対して行い、号は独立した kou segment にする。号本文を柱書 segment に
    混ぜると、既存 chunk の意味 (柱書 = 号を導く文) が変わってしまう。
    """
    return sentences_text(para.find("ParagraphSentence"))


def _item_segment_text(elem: Any) -> str:
    """号 chunk の text: 号番号 ＋ 本文 ＋ 配下の細別 (番号 ＋ 本文).

    Why 号番号 (ItemTitle「一」) を含めるか: 本文 md の当該行が
    「一　国内　この法律の施行地をいう。」である以上、chunk の text も同じ内容に
    しないと「chunk の総和 == 正本本文」(G0-b) が号番号の分だけ食い違う。番号込みに
    すると chunk は本文行そのものになり、G0-b exact と G0-c (chunk ⊂ 親本文) が
    どちらも自明に成立する。検索・引用の観点でも号番号は有用。
    """
    tag = elem.tag
    title_tag, sent_tag = f"{tag}Title", f"{tag}Sentence"
    title = _text(elem.find(title_tag))
    parts: list[str] = []
    for child in elem:
        ct = child.tag
        if ct == sent_tag:
            body = sentences_text(child)
            parts.append(f"{title}{IDEO_SPACE}{body}" if title else body)
        elif ct.startswith("Subitem"):
            parts.append(_item_segment_text(child))
        elif ct == "List":
            # 号・細別の中の List は当該号の本文の一部 (md でも同じ行群に出る)。
            # chunk に含めないと「md にあるのに chunk に無い」= G0-b 不一致になる。
            parts.append(_text(child))
    return "\n".join(p for p in parts if p)


def _item_num_parts(raw: str) -> tuple[str, int | None]:
    """号の Num 属性を (id サフィックス, item_number) にする.

    e-Gov の Item@Num の実例:
      "1"    通常の号            -> ("1", 1)
      "1_2"  号の枝番 (第一号の二) -> ("1-2", 1)
      "3:4"  範囲号 (三及び四 削除) -> ("3-4", 3)

    Why 全角に分解するか (旧実装の 2 つのバグ):
      旧実装は ``int(raw.split("_")[0])`` だったため、
      (a) 範囲号 "3:4" は ValueError で **無言スキップ** され、md には本文
          (「三及び四　削除」) が出るのに chunk が作られなかった (G0-b 不一致)。
      (b) 号の枝番 "1_2" は id が ``-kou-1`` に潰れ、**第一号と id が衝突**していた。
    """
    suffix = raw.replace("_", "-").replace(":", "-")
    head = re.split(r"[-]", suffix)[0] if suffix else ""
    try:
        return suffix, int(head)
    except ValueError:
        return suffix, None


def build_kou_segments(para: Any, article_id: str, para_num: int) -> list[Segment]:
    """項配下の号を kou segment にする (範囲号・枝番号も落とさない)."""
    segments: list[Segment] = []
    for i, item in enumerate(para.findall("Item"), start=1):
        raw = (item.get("Num") or "").strip()
        suffix, item_num = _item_num_parts(raw)
        text = _item_segment_text(item)
        if not text:
            continue
        segments.append(
            Segment(
                id=f"{article_id}-p{para_num}-kou-{suffix or i}",
                type="kou",
                text=text,
                modality=detect_modality(text),
                item_number=item_num,
            )
        )
    return segments


def build_list_segments(para: Any, article_id: str, para_num: int) -> list[Segment]:
    """項直下の List を list segment にする.

    Why: List は正本 md の本文に出る (原文の一部) が、従来どの segment にも
    入っていなかった。chunk 化しないと「md にあるのに chunk に無い」= G0-b 不一致。
    号の中の List は号 segment に含める (build_kou_segments 側)。
    """
    segments: list[Segment] = []
    for i, lst in enumerate(para.findall("List"), start=1):
        text = _text(lst)
        if not text:
            continue
        segments.append(
            Segment(
                id=f"{article_id}-p{para_num}-list-{i}",
                type="list",
                text=text,
                modality=detect_modality(text),
            )
        )
    return segments


# ============================================================
# 条 -> (原文セクション本文, paragraphs[])
# ============================================================


def build_article_md(article: Any, article_id: str) -> tuple[str, list[dict], list[str]]:
    """1 条の (原文セクション本文, frontmatter paragraphs[], warnings) を作る."""
    warnings: list[str] = []
    art_title = _text(article.find("ArticleTitle"))
    paragraphs = article.findall("Paragraph")
    multi = len(paragraphs) > 1

    blocks: list[str] = []
    fm_paragraphs: list[dict] = []

    for i, para in enumerate(paragraphs, start=1):
        try:
            pnum = int((para.get("Num") or str(i)).strip())
        except ValueError:
            pnum = i
        heading = f"### {art_title}第{int_to_kansuji(pnum)}項" if multi else f"### {art_title}"
        body = render_paragraph_body(para)
        blocks.append(f"{heading}\n\n{body}" if body else heading)

        base_text = paragraph_sentence_text(para)
        segments = split_paragraph_segments(article_id, pnum, base_text) if base_text else []
        segments.extend(build_kou_segments(para, article_id, pnum))
        segments.extend(build_list_segments(para, article_id, pnum))
        if not segments:
            warnings.append(f"{article_id}: paragraph {pnum} produced no segments")

        fm_paragraphs.append(
            {
                "number": pnum,
                "has_proviso": any(
                    s.get("Function") == "proviso"
                    for ps in para.findall("ParagraphSentence")
                    for s in ps.findall("Sentence")
                ),
                "has_items": bool(para.findall("Item")),
                "is_added_by_amendment": False,
                "segments": [s.to_dict() for s in segments],
            }
        )

    # 条直下の SupplNote (罰則付記) 等は最後の項ブロックの末尾に原文のまま置く。
    # segment 化もする (md にあるのに chunk に無い = G0-b 不一致 になるため)。
    extras = [
        (c.tag, _text(c))
        for c in article
        if c.tag not in ("ArticleTitle", "ArticleCaption", "Paragraph") and _text(c)
    ]
    if extras:
        if not blocks or not fm_paragraphs:
            warnings.append(f"{article_id}: has extras but no paragraphs; extras dropped")
        else:
            blocks[-1] = blocks[-1] + "\n\n" + "\n\n".join(t for _tag, t in extras)
            last = fm_paragraphs[-1]
            for i, (tag, text) in enumerate(extras, start=1):
                seg = Segment(
                    id=f"{article_id}-{tag.lower()}-{i}",
                    type=tag.lower(),  # 例: supplnote (罰則付記)
                    text=text,
                    modality=detect_modality(text),
                )
                last["segments"].append(seg.to_dict())

    return "\n\n".join(blocks) + "\n", fm_paragraphs, warnings


# ============================================================
# md への in-place 反映 (curated 内容を保存)
# ============================================================


_H1_RE = re.compile(r"^# .*$", re.MULTILINE)


def build_h1(article: Any, law_name_ja: str, article_number: str) -> str:
    """H1 見出しを XML から作る (parse-egov.article_to_markdown と同じ式).

    Why H1 も作り直すか: H1 の見出し語は ArticleCaption 由来 = XML 由来であって
    人手 curated ではない。ルビ (<Rt>) 混入は本文だけでなく caption にも及んでいた
    (例「代理行為の瑕疵かし」)。本文だけ直して H1 を残すと、同じ条の中で
    表記が食い違う。
    """
    caption = _text(article.find("ArticleCaption"))
    title = f"# {law_name_ja} 第{article_number}条"
    if caption:
        title += f"({caption.strip('()')})"
    return title


def rewrite_md(
    md_text: str,
    new_ja_body: str,
    fm_paragraphs: list[dict],
    new_h1: str | None = None,
    parent_section: dict | None = None,
) -> str:
    """既存 md の XML 由来部分 (原文本文 / paragraphs / H1 / parent_section) を差し替える.

    curated なフィールド (cases / amendments / tags / notes / translation_status …) と、
    原文セクション以降 (英訳・判例リンク・改正履歴・注記) は一切触らない。

    Raises:
        ValueError: frontmatter または 原文セクションが無い場合 (fail loud).
    """
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", md_text, re.DOTALL)
    if not m:
        raise ValueError("missing frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)

    sec = JA_SECTION_RE.search(body)
    if not sec:
        raise ValueError("missing `## 原文 (日本語)` section")

    fm["paragraphs"] = fm_paragraphs  # curated な他フィールドは触らない
    if parent_section:
        fm["parent_section"] = parent_section
    fm_yaml = yaml.dump(fm, allow_unicode=True, sort_keys=False, width=200)

    # frontmatter と `## 原文` の間は **H1 見出しだけ** (format-spec §5.1)。
    # 全部 derived なので、元の内容を温存せず丸ごと作り直す。
    #
    # Why 温存してはいけないか (実際に起きた事故):
    #   旧 render_v02_md は marker を「segment 本文の先頭 20 字」を検索して直前に挿入して
    #   いた。その 20 字が **H1 のキャプションにも含まれる** 条では、marker が H1 行の
    #   内部に挿入され、H1 が 2 行に割れていた:
    #       # 地方税法 第622条(（<!-- segment: simple id: ... -->
    #       遊休土地に対して課する特別土地保有税の課税標準）)
    #   H1 行だけを regex で差し替えると、**割れた残り半分と marker がそのまま残る**
    #   (2026-07-14 に 18 条で残存。本文セクションの外なので G0-a〜d はどれも見ていなかった)。
    #   ここを「作り直す」ことで、セクション外の残骸を構造的に一掃する。
    heading_line = body[sec.start() : sec.start(1)].rstrip("\n")  # 例: "## 原文 (日本語)"
    h1 = new_h1 or (_H1_RE.search(body).group(0) if _H1_RE.search(body) else "")
    prefix = f"\n{h1}\n\n{heading_line}\n\n" if h1 else f"\n{heading_line}\n\n"
    new_body = prefix + new_ja_body + body[sec.end(1) :]
    return f"---\n{fm_yaml}---\n{new_body}"


def process_law(
    law_abbrev: str,
    law_id: str,
    md_dir: Path,
    xml_path: Path,
    dry_run: bool,
) -> tuple[int, int, list[str]]:
    """1 法令を rebuild. (更新数, 変化なし数, warnings) を返す."""
    warnings: list[str] = []
    root = ET.fromstring(xml_path.read_bytes().decode("utf-8"))
    law = root if root.tag == "Law" else root.find(".//Law")
    main = law.find("LawBody").find("MainProvision")

    # parent_section (編・章・節・款・目の番号と名称) も XML 由来なので作り直す。
    # Why: 節名にもルビが混入していた (例「乗車、積載及び牽けん引」)。parent_section は
    # chunk にも複製されるので、直さないと索引側に汚染が残る。
    # 抽出は parse-egov._walk_articles を再利用する (構造スタックの実装を二重に書かない)。
    parent_sections = {
        a["number"]: a.get("parent_section") for a in _parse_egov._walk_articles(main, []) if a
    }

    updated = unchanged = 0
    for article in main.iter("Article"):
        num = (article.get("Num") or "").strip().replace("_", "-")
        if not num or ":" in num:
            continue  # 範囲条 (削除) は parse-egov.py:224 と同様にスキップ
        md_path = md_dir / f"{law_abbrev}-article-{num}.md"
        if not md_path.exists():
            warnings.append(f"{law_abbrev} art {num}: md 不在 (新規作成はスコープ外)")
            continue
        article_id = f"{law_abbrev}-art-{num}"
        ja_body, fm_paragraphs, warns = build_article_md(article, article_id)
        warnings.extend(warns)

        original = md_path.read_text(encoding="utf-8")
        fm_head = yaml.safe_load(re.match(r"^---\n(.*?)\n---\n", original, re.DOTALL).group(1))
        new_h1 = build_h1(article, fm_head.get("law_name_ja", ""), num)
        try:
            new_text = rewrite_md(
                original,
                ja_body,
                fm_paragraphs,
                new_h1=new_h1,
                parent_section=parent_sections.get(num),
            )
        except ValueError as e:
            warnings.append(f"{law_abbrev} art {num}: {e}")
            continue
        if new_text == original:
            unchanged += 1
            continue
        updated += 1
        if not dry_run:
            # newline="\n" 必須: 既定 (None) は OS ネイティブ = Windows で CRLF になり、
            # git 追跡ファイルに CRLF が入る (既知の事故源)。
            safe_write_text(md_path, new_text, encoding="utf-8", newline="\n")
    return updated, unchanged, warnings


def find_md_dir(data_dir: Path, law_abbrev: str) -> Path | None:
    """data_dir/phase*/law_abbrev/ を探す (case-law/ 等の同名 dir を掴まない)."""
    for phase_dir in sorted(data_dir.iterdir()):
        if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
            continue
        cand = phase_dir / law_abbrev
        if cand.is_dir():
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data/v0.2"))
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--law-only", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(_HERE))
    from extract_kou_from_xml import build_law_abbrev_to_id_phase

    law_map = build_law_abbrev_to_id_phase(args.data_dir)
    if args.law_only:
        if args.law_only not in law_map:
            print(f"ERROR: law_abbrev not found: {args.law_only}", file=sys.stderr)
            return 1
        law_map = {args.law_only: law_map[args.law_only]}

    total_updated = total_unchanged = 0
    all_warnings: list[str] = []
    for law_abbrev, (law_id, _phase) in sorted(law_map.items()):
        xml_path = args.xml_dir / f"{law_id}.xml"
        md_dir = find_md_dir(args.data_dir, law_abbrev)
        if not xml_path.exists() or md_dir is None:
            all_warnings.append(f"{law_abbrev}: XML or md dir 不在")
            continue
        updated, unchanged, warns = process_law(law_abbrev, law_id, md_dir, xml_path, args.dry_run)
        all_warnings.extend(warns)
        total_updated += updated
        total_unchanged += unchanged
        print(f"  {law_abbrev}: updated={updated} unchanged={unchanged}", file=sys.stderr)

    print(f"\n=== updated {total_updated} / unchanged {total_unchanged} ===", file=sys.stderr)
    if all_warnings:
        print(f"--- warnings ({len(all_warnings)}) ---", file=sys.stderr)
        for w in all_warnings[:40]:
            print(f"  - {w}", file=sys.stderr)
    if args.dry_run:
        print("(dry-run, 書き込みなし)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

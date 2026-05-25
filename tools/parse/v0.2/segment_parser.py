#!/usr/bin/env python3
"""segment_parser.py — JuriCode-JP v0.1 → v0.2 segment-aware migrator.

入力: v0.1 .md ファイル (既存 corpus)
出力:
  1. v0.2 .md (segments[] を frontmatter に追加、segment marker を body に追加)
  2. .chunks.jsonl (segment 単位の retrieval 用 JSON Lines)

設計図: business/japanese-law-rag-design-blueprint-2026-05-22.md
仕様書: docs/format-spec-v0.2.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# tools/shared/src を sys.path に追加して juricode_shared を import 可能にする
_SHARED_SRC = Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import safe_write_text  # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pip install pyyaml")

PARSER_VERSION = "tools/parse/v0.2/segment_parser.py@0.1.0"

# ============================================================
# 検出ルール (rule-based detectors)
# ============================================================

# segment type detectors
TADASHI_PATTERN = re.compile(r"ただし、")
KOU_DAN_LEADER = re.compile(r"この場合において(?:は|、)|^前段の場合において")
HASHIRA_PATTERN = re.compile(r"次に掲げる|次の各号|次のとおり|次に定める")

# override / 準用
NIKAKAWARAZU_PATTERN = re.compile(
    r"(?:(第[一二三四五六七八九十百千]+項|前項|同項|第[一二三四五六七八九十百千]+条|前条|前[二三四五六]条)(?:第[一二三四五六七八九十百千]+項)?)の規定にかかわらず"
)
JUNYOU_PATTERN = re.compile(r"(?:について|に)準用する")
APPLIES_PROVISIONS_PATTERN = re.compile(
    r"(第[一二三四五六七八九十百千]+条(?:から第[一二三四五六七八九十百千]+条まで)?|前条|前[二三四五六]条|次条)の規定(?:は|を)"
)

# modality detectors (文末から判定)
MODALITY_PATTERNS = [
    # 優先順位順 (より specific なものを先に判定)
    ("jogai", re.compile(r"この限りでない[。」]?$|妨げない[。」]?$|適用しない[。」]?$")),
    ("koka_mukou", re.compile(r"無効とする[。」]?$")),
    ("koka_torikeshi", re.compile(r"取り消すことができる[。」]?$")),
    ("gimu_kei", re.compile(r"処する[。」]?$|の刑に処する[。」]?$|罰する[。」]?$")),
    (
        "gimu_negative",
        re.compile(
            r"罰しない[。」]?$|処罰しない[。」]?$|してはならない[。」]?$|してはいけない[。」]?$"
        ),
    ),
    ("kanou_negative", re.compile(r"することができない[。」]?$|できない[。」]?$")),
    (
        "doryoku_gimu",
        re.compile(r"努めなければならない[。」]?$|努めるものとする[。」]?$|努める[。」]?$"),
    ),
    (
        "gimu",
        re.compile(
            r"しなければならない[。」]?$|なければならない[。」]?$|するものとする[。」]?$|とする[。」]?$"
        ),
    ),
    ("kanou_kenri", re.compile(r"することができる[。」]?$|ができる[。」]?$")),
    ("teigi", re.compile(r"をいう[。」]?$|という[。」]?$")),  # 定義条文
    (
        "tetsuduki",
        re.compile(
            r"通知する[。」]?$|公示する[。」]?$|公表する[。」]?$|送付する[。」]?$|提出する[。」]?$|交付する[。」]?$"
        ),
    ),  # 手続的義務
]

# 相対参照 (絶対参照化のため)
RELATIVE_REF_PATTERN = re.compile(
    r"(前項|同項|次項|前条|次条|本条|前[二三四五六七八九十]項|前[二三四五六七八九十]条)"
)

# 項見出し (v0.1 形式) — 単一の真実源として module level に集約 (FU-301).
#
# 設計上の Why:
# - re.split / re.match の両方で使うため re.MULTILINE フラグ付き
#   (re.match は MULTILINE の影響を受けないので、両方安全に共有可能)
# - capture group なし (re.split で使うとき、capture group があると分割結果に
#   group 値が混入して下流の zip ロジックが壊れる)
# - 「第N条」「第N条のM」(枝番条)、「第N条第K項」「第N条のM第K項」を全て match
# - 既知事故 (g) 4,810 件 empty chunks bug の再発条件 (regex 2 重定義) を解消
#
# テスト: tools/parse/v0.2/tests/test_paragraph_heading_pattern.py
PARAGRAPH_HEADING_PATTERN = re.compile(
    r"^### 第[零〇一二三四五六七八九十百千万]+条(?:の[零〇一二三四五六七八九十百千万]+)?(?:第[零〇一二三四五六七八九十百千万]+項)?\s*$",
    re.MULTILINE,
)

# 漢数字 → アラビア数字
KANSUJI_TO_INT = {
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
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}


def kansuji_to_int(s: str) -> int:
    """漢数字をアラビア数字に変換 (簡易、~万まで対応)."""
    if not s:
        return 0
    result = 0
    current = 0
    for ch in s:
        v = KANSUJI_TO_INT.get(ch, 0)
        if v >= 10:
            if current == 0:
                current = 1
            result += current * v
            current = 0
        else:
            current = current * 10 + v
    result += current
    return result


# ============================================================
# データ型
# ============================================================


@dataclass
class Segment:
    """1 つの segment (本文/ただし書/柱書/号/前段/後段/特則/準用)."""

    id: str
    type: str  # simple | honbun | tadashi | zen_dan | kou_dan | hashira | kou | tokusoku | junyou
    text: str
    modality: str = "unspecified"
    item_number: int | None = None
    override_flag: bool = False
    override_target: list[str] = field(default_factory=list)
    applies_provisions: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    depends_on: str | None = None

    def to_dict(self) -> dict:
        """YAML/JSON 出力用に空フィールドを省略."""
        d = {"id": self.id, "type": self.type, "text": self.text, "modality": self.modality}
        if self.item_number is not None:
            d["item_number"] = self.item_number
        if self.override_flag:
            d["override_flag"] = True
            if self.override_target:
                d["override_target"] = self.override_target
        if self.applies_provisions:
            d["applies_provisions"] = self.applies_provisions
        if self.references:
            d["references"] = self.references
        if self.depends_on:
            d["depends_on"] = self.depends_on
        return d


@dataclass
class ParagraphV02:
    """v0.2 paragraph (segments を持つ)."""

    number: int
    has_proviso: bool
    has_items: bool
    is_added_by_amendment: bool
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "has_proviso": self.has_proviso,
            "has_items": self.has_items,
            "is_added_by_amendment": self.is_added_by_amendment,
            "segments": [s.to_dict() for s in self.segments],
        }


# ============================================================
# 段落解析: paragraph body → segments
# ============================================================


def detect_modality(text: str) -> str:
    """text の文末から modality を判定."""
    # 「。」等で終わる箇所を順に試す
    text_stripped = text.strip()
    # 「。」で文を分割し、最後の意味のある文を見る
    sentences = [s for s in re.split(r"[。]", text_stripped) if s.strip()]
    if not sentences:
        return "unspecified"
    last = sentences[-1] + "。"  # 「。」を補完
    for modality, pattern in MODALITY_PATTERNS:
        if pattern.search(last):
            return modality
    return "unspecified"


def extract_relative_references(text: str) -> list[str]:
    """text から相対参照を抽出 (絶対参照化は後段)."""
    refs = RELATIVE_REF_PATTERN.findall(text)
    return list(set(refs))  # 重複排除


def detect_nikakawarazu_target(text: str) -> list[str]:
    """『にかかわらず』の対象を抽出 (相対参照のまま、絶対化は後段)."""
    matches = NIKAKAWARAZU_PATTERN.findall(text)
    targets = []
    for m in matches:
        targets.append(m)  # 例: "第一項", "前項", "第二十三条"
    return targets


def detect_applies_provisions(text: str) -> list[str]:
    """『〜について準用する』の対象を抽出."""
    matches = APPLIES_PROVISIONS_PATTERN.findall(text)
    return [m for m in matches if "規定" in text]  # フィルタ簡略化


def split_paragraph_segments(
    article_id: str,
    paragraph_number: int,
    body: str,
) -> list[Segment]:
    """paragraph body を segment 群に分割.

    優先順位:
      1. 「準用する」 → type: junyou (項全体)
      2. 「にかかわらず」 → type: tokusoku (項全体 or 該当 segment)
      3. 「次に掲げる」 → type: hashira + (各号は v0.1 では body に欠落しているため hashira のみ)
      4. 「この場合において」 → 前段 + 後段
      5. 「ただし、」 → 本文 + ただし書
      6. その他 → simple
    """
    body = body.strip()
    if not body:
        return []

    seg_prefix = f"{article_id}-p{paragraph_number}"

    # 1. 準用判定 (項全体が準用)
    if JUNYOU_PATTERN.search(body):
        applies = detect_applies_provisions(body)
        seg = Segment(
            id=seg_prefix,
            type="junyou",
            text=body,
            modality=detect_modality(body),
            applies_provisions=applies,
            references=extract_relative_references(body),
        )
        return [seg]

    # 2. にかかわらず判定 (項全体が tokusoku)
    nikakawarazu_targets = detect_nikakawarazu_target(body)
    if nikakawarazu_targets:
        seg = Segment(
            id=seg_prefix,
            type="tokusoku",
            text=body,
            modality=detect_modality(body),
            override_flag=True,
            override_target=nikakawarazu_targets,
            references=extract_relative_references(body),
        )
        return [seg]

    # 3. 柱書+号 判定
    if HASHIRA_PATTERN.search(body):
        # v0.1 corpus では各号 content が欠落しているため、hashira のみ抽出
        seg = Segment(
            id=f"{seg_prefix}-hashira",
            type="hashira",
            text=body,  # 本文全体 (柱書 + 各号 欠落) を hashira に
            modality=detect_modality(body),
            references=extract_relative_references(body),
        )
        return [seg]

    # 4. 前段+後段 判定 (「この場合において」が文中にある)
    if KOU_DAN_LEADER.search(body):
        # 「この場合において」を境に分割
        match = KOU_DAN_LEADER.search(body)
        zen_text = body[: match.start()].strip()
        kou_text = body[match.start() :].strip()
        if zen_text.endswith("。"):
            zen_seg = Segment(
                id=f"{seg_prefix}-zen",
                type="zen_dan",
                text=zen_text,
                modality=detect_modality(zen_text),
                references=extract_relative_references(zen_text),
            )
            kou_seg = Segment(
                id=f"{seg_prefix}-kou",
                type="kou_dan",
                text=kou_text,
                modality=detect_modality(kou_text),
                depends_on=zen_seg.id,
                references=extract_relative_references(kou_text),
            )
            return [zen_seg, kou_seg]

    # 5. 本文+ただし書 判定
    if TADASHI_PATTERN.search(body):
        match = TADASHI_PATTERN.search(body)
        honbun_text = body[: match.start()].strip()
        tadashi_text = body[match.start() :].strip()
        if honbun_text:
            honbun_seg = Segment(
                id=f"{seg_prefix}-honbun",
                type="honbun",
                text=honbun_text,
                modality=detect_modality(honbun_text),
                references=extract_relative_references(honbun_text),
            )
            tadashi_seg = Segment(
                id=f"{seg_prefix}-tadashi",
                type="tadashi",
                text=tadashi_text,
                modality=detect_modality(tadashi_text),
                references=extract_relative_references(tadashi_text),
            )
            return [honbun_seg, tadashi_seg]

    # 6. デフォルト: simple
    seg = Segment(
        id=seg_prefix,
        type="simple",
        text=body,
        modality=detect_modality(body),
        references=extract_relative_references(body),
    )
    return [seg]


# ============================================================
# v0.1 .md → v0.2 IR (in-memory)
# ============================================================


def parse_v01_md(md_path: Path) -> tuple[dict, list[ParagraphV02], str]:
    """v0.1 .md を読み、 (frontmatter, paragraphs_v02, body_after_frontmatter) を返す."""
    raw = md_path.read_text(encoding="utf-8")
    # frontmatter 抽出
    m = re.match(r"^---\n(.*?)\n---\n(.*)", raw, re.DOTALL)
    if not m:
        raise ValueError(f"frontmatter not found: {md_path}")
    fm_text = m.group(1)
    body = m.group(2)
    frontmatter = yaml.safe_load(fm_text)

    article_id = frontmatter.get("article_id", md_path.stem)

    # paragraph 見出しを検出して body を分割
    paragraphs_v02: list[ParagraphV02] = []
    paragraph_meta = frontmatter.get("paragraphs", []) or []

    # 「### 第N条第N項」「### 第N条の二第N項」「### 第N条」見出しを境に body を分割
    # 枝番付き条 (第一条の二、第百九十七条の三) も対応
    # FU-301: module level の PARAGRAPH_HEADING_PATTERN を再利用 (regex 2 重定義を解消)
    sections = PARAGRAPH_HEADING_PATTERN.split(body)
    # 最初の要素は見出し前 (通常 ## 原文 などの導入部)
    # sections[0] は捨てて、sections[1:] が各段落本文
    paragraph_bodies = sections[1:]

    # 「## English Translation」以降は paragraph 本文ではない
    if paragraph_bodies:
        # 最後の paragraph_body から「## English Translation」以降を削る
        last_body = paragraph_bodies[-1]
        end_match = re.search(r"^##\s+", last_body, flags=re.MULTILINE)
        if end_match:
            paragraph_bodies[-1] = last_body[: end_match.start()]

    # paragraph_meta と paragraph_bodies を zip
    for i, pmeta in enumerate(paragraph_meta):
        pnum = pmeta.get("number", i + 1)
        body_text = paragraph_bodies[i] if i < len(paragraph_bodies) else ""
        body_text = body_text.strip()

        segments = split_paragraph_segments(article_id, pnum, body_text)

        # has_proviso / has_items を segment から再計算
        has_proviso = any(s.type == "tadashi" for s in segments)
        has_items = any(s.type == "hashira" for s in segments) or bool(
            HASHIRA_PATTERN.search(body_text)
        )

        para_v02 = ParagraphV02(
            number=pnum,
            has_proviso=has_proviso,
            has_items=has_items,
            is_added_by_amendment=pmeta.get("is_added_by_amendment", False),
            segments=segments,
        )
        paragraphs_v02.append(para_v02)

    return frontmatter, paragraphs_v02, body


# ============================================================
# v0.2 .md 生成
# ============================================================

SEGMENT_HEADING = {
    "simple": None,  # 見出し省略
    "honbun": "本文",
    "tadashi": "ただし書",
    "zen_dan": "前段",
    "kou_dan": "後段",
    "hashira": "柱書",
    "kou": None,  # 「第N号」
    "tokusoku": "特則",
    "junyou": "準用",
}


def render_v02_md(
    frontmatter: dict,
    paragraphs_v02: list[ParagraphV02],
    original_body: str,
    parsing_warnings: list[str] | None = None,
) -> str:
    """v0.2 .md を生成 (FU-303: scope 限定 + warnings 記録).

    Args:
        frontmatter: v0.1 frontmatter dict.
        paragraphs_v02: v0.2 paragraph (segments を含む) のリスト.
        original_body: v0.1 .md の本文.
        parsing_warnings: マーカー挿入失敗時に追記される警告リスト. None 可.

    FU-303 設計:
        旧実装は body 全体に対し replace していたため、(a) 「## English
        Translation」セクションに同じ search_str があれば英訳に marker が
        誤挿入、(b) search_str に改行が混じると strip() でマッチが消えて
        サイレント失敗、の 2 種類の事故が起きた。

        修正: body を intro / paragraph slices / trailing (英訳以降) に分解し、
        marker 挿入は対応する paragraph slice 内のみに限定。失敗時は
        parsing_warnings に詳細を追記してサイレント失敗を阻止する。

    関連: business/code-reviews/2026-05-24-v02-parser-pipeline-review.md §D-03
    """
    warnings = parsing_warnings if parsing_warnings is not None else []

    new_fm = dict(frontmatter)
    new_fm["paragraphs"] = [p.to_dict() for p in paragraphs_v02]
    fm_yaml = yaml.dump(new_fm, allow_unicode=True, sort_keys=False, width=200)

    # ---- scope 分解: intro / paragraph slices / English (or other H2) 以降 ----
    # 「## 原文 (日本語)」セクションは本文を含むので boundary ではない.
    # その後に現れる H2 (## English Translation / ## 注記 / ## 判例 等) を
    # 「日本語本文終端」と見なす. これにより英訳側への marker 誤挿入を防ぐ.
    gen_match = re.search(r"^##\s+原文", original_body, re.MULTILINE)
    if gen_match:
        next_h2 = re.search(r"^##\s+", original_body[gen_match.end() :], re.MULTILINE)
        ja_end = gen_match.end() + next_h2.start() if next_h2 else len(original_body)
    else:
        # 「## 原文」セクションがない場合は body 全体を JA とみなす
        ja_end = len(original_body)
    ja_body = original_body[:ja_end]
    trailing = original_body[ja_end:]

    headings = list(PARAGRAPH_HEADING_PATTERN.finditer(ja_body))
    has_any_segments = any(p.segments for p in paragraphs_v02)
    if not headings and has_any_segments:
        warnings.append(
            "render_v02_md: no paragraph headings found in body; "
            "segment markers will be skipped (no safe scope to insert into)"
        )
        return f"---\n{fm_yaml}---\n{original_body}"

    intro = ja_body[: headings[0].start()] if headings else ja_body
    heading_texts: list[str] = []
    para_bodies: list[str] = []
    for i, h in enumerate(headings):
        heading_texts.append(ja_body[h.start() : h.end()])
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(ja_body)
        para_bodies.append(ja_body[start:end])

    # ---- segment marker 挿入 (paragraph slice 内のみ) ----
    for p in paragraphs_v02:
        pnum = p.number
        pidx = pnum - 1  # 1-indexed
        if pidx < 0 or pidx >= len(para_bodies):
            for seg in p.segments:
                warnings.append(
                    f"render_v02_md: paragraph_number={pnum} out of range "
                    f"(have {len(para_bodies)} slices); segment {seg.id!r} marker skipped"
                )
            continue

        for seg in p.segments:
            marker_attrs = [f"segment: {seg.type}", f"id: {seg.id}"]
            if seg.override_flag:
                marker_attrs.append("override_flag: true")
                if seg.override_target:
                    marker_attrs.append(f"override_target: {','.join(seg.override_target)}")
            if seg.depends_on:
                marker_attrs.append(f"depends_on: {seg.depends_on}")
            if seg.applies_provisions:
                marker_attrs.append(f"applies_provisions: {','.join(seg.applies_provisions)}")
            marker = f"<!-- {' '.join(marker_attrs)} -->"

            # text 先頭 20 文字 (ただし改行までで切る — 改行入り substring は body に存在しない)
            raw_text = seg.text
            nl_idx = raw_text.find("\n")
            head = raw_text if nl_idx < 0 else raw_text[:nl_idx]
            search_str = head[:20].strip()

            if not search_str:
                warnings.append(
                    f"render_v02_md: segment {seg.id!r}: empty search_str "
                    f"(seg.text 先頭が空白のみ); marker skipped"
                )
                continue
            if search_str not in para_bodies[pidx]:
                warnings.append(
                    f"render_v02_md: segment {seg.id!r}: search_str {search_str!r} "
                    f"not found in paragraph {pnum} scope; marker skipped"
                )
                continue
            para_bodies[pidx] = para_bodies[pidx].replace(search_str, f"{marker}\n{search_str}", 1)

    rebuilt_ja = intro + "".join(h + b for h, b in zip(heading_texts, para_bodies, strict=True))
    new_body = rebuilt_ja + trailing
    return f"---\n{fm_yaml}---\n{new_body}"


# ============================================================
# .chunks.jsonl 生成
# ============================================================


def render_chunks_jsonl(
    frontmatter: dict,
    paragraphs_v02: list[ParagraphV02],
) -> str:
    """segment chunk を 1 行 1 JSON で出力."""
    lines = []
    article_id = frontmatter.get("article_id")
    law_id = frontmatter.get("law_id")
    law_name_ja = frontmatter.get("law_name_ja")
    article_number = frontmatter.get("article_number")
    parent_section = frontmatter.get("parent_section")

    for p in paragraphs_v02:
        for seg in p.segments:
            chunk = {
                "id": seg.id,
                "article_id": article_id,
                "law_id": law_id,
                "law_name_ja": law_name_ja,
                "article_number": article_number,
                "paragraph_number": p.number,
                "segment_type": seg.type,
                "modality": seg.modality,
                "text": seg.text,
            }
            if parent_section:
                chunk["parent_section"] = parent_section
            if seg.item_number is not None:
                chunk["item_number"] = seg.item_number
            if seg.override_flag:
                chunk["override_flag"] = True
                if seg.override_target:
                    chunk["override_target"] = seg.override_target
            if seg.applies_provisions:
                chunk["applies_provisions"] = seg.applies_provisions
            if seg.references:
                chunk["references"] = seg.references
            if seg.depends_on:
                chunk["depends_on"] = seg.depends_on
            lines.append(json.dumps(chunk, ensure_ascii=False))
    return "\n".join(lines) + "\n"


# ============================================================
# main
# ============================================================


def process_file(
    md_path: Path,
    output_md_dir: Path,
    output_chunks_dir: Path,
    dry_run: bool = False,
) -> dict:
    """1 ファイルを v0.1 → v0.2 に変換."""
    try:
        frontmatter, paragraphs_v02, body = parse_v01_md(md_path)
    except Exception as e:
        return {"path": str(md_path), "status": "error", "error": str(e)}

    # 出力ファイル名
    out_md = output_md_dir / md_path.name
    out_chunks = output_chunks_dir / f"{md_path.stem}.chunks.jsonl"

    # FU-303: render_v02_md がマーカー挿入失敗を warnings に記録する
    parsing_warnings: list[str] = []
    rendered_md = render_v02_md(
        frontmatter, paragraphs_v02, body, parsing_warnings=parsing_warnings
    )

    if not dry_run:
        safe_write_text(out_md, rendered_md, encoding="utf-8")
        safe_write_text(
            out_chunks,
            render_chunks_jsonl(frontmatter, paragraphs_v02),
            encoding="utf-8",
        )

    # 統計
    total_segments = sum(len(p.segments) for p in paragraphs_v02)
    type_counts: dict[str, int] = {}
    modality_counts: dict[str, int] = {}
    override_count = 0
    junyou_count = 0
    for p in paragraphs_v02:
        for seg in p.segments:
            type_counts[seg.type] = type_counts.get(seg.type, 0) + 1
            modality_counts[seg.modality] = modality_counts.get(seg.modality, 0) + 1
            if seg.override_flag:
                override_count += 1
            if seg.type == "junyou":
                junyou_count += 1

    return {
        "path": str(md_path),
        "status": "ok",
        "paragraphs": len(paragraphs_v02),
        "segments": total_segments,
        "type_counts": type_counts,
        "modality_counts": modality_counts,
        "override_count": override_count,
        "junyou_count": junyou_count,
        "parsing_warnings": parsing_warnings,  # FU-303: marker 挿入失敗等
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--input", type=Path, required=True, help="v0.1 .md ファイル or ディレクトリ"
    )
    parser.add_argument("--output-md-dir", type=Path, required=True, help="v0.2 .md 出力先")
    parser.add_argument(
        "--output-chunks-dir", type=Path, required=True, help=".chunks.jsonl 出力先"
    )
    parser.add_argument("--dry-run", action="store_true", help="書き込みなし、統計のみ")
    parser.add_argument("--limit", type=int, default=None, help="処理ファイル数の上限 (デバッグ)")
    args = parser.parse_args()

    # 入力ファイル列挙
    if args.input.is_file():
        files = [args.input]
    elif args.input.is_dir():
        files = sorted(args.input.rglob("*.md"))
    else:
        sys.exit(f"ERROR: input not found: {args.input}")

    if args.limit:
        files = files[: args.limit]

    print(f"Processing {len(files)} file(s)...", file=sys.stderr)

    # 集計
    total_segments = 0
    total_type_counts: dict[str, int] = {}
    total_modality_counts: dict[str, int] = {}
    total_override = 0
    total_junyou = 0
    errors = []
    ok_count = 0

    for f in files:
        # README や _meta は skip
        if f.name in ("README.md", "_meta.yaml") or f.name.startswith("_"):
            continue
        result = process_file(f, args.output_md_dir, args.output_chunks_dir, dry_run=args.dry_run)
        if result["status"] == "ok":
            ok_count += 1
            total_segments += result["segments"]
            for t, c in result["type_counts"].items():
                total_type_counts[t] = total_type_counts.get(t, 0) + c
            for mod, c in result["modality_counts"].items():
                total_modality_counts[mod] = total_modality_counts.get(mod, 0) + c
            total_override += result["override_count"]
            total_junyou += result["junyou_count"]
        else:
            errors.append(result)

    # サマリ
    print("\n=== Summary ===", file=sys.stderr)
    print(f"OK: {ok_count}, Error: {len(errors)}", file=sys.stderr)
    print(f"Total segments: {total_segments}", file=sys.stderr)
    print("\nSegment types:", file=sys.stderr)
    for t, c in sorted(total_type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:12s}: {c}", file=sys.stderr)
    print("\nModality:", file=sys.stderr)
    for mod, c in sorted(total_modality_counts.items(), key=lambda x: -x[1]):
        print(f"  {mod:18s}: {c}", file=sys.stderr)
    print(f"\nOverride (nikakawarazu): {total_override}", file=sys.stderr)
    print(f"Junyou (junyou): {total_junyou}", file=sys.stderr)

    if errors:
        print(f"\n=== Errors ({len(errors)}) ===", file=sys.stderr)
        for e in errors[:10]:
            print(f"  {e['path']}: {e['error']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

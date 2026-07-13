"""headings.py -- 条文 Markdown の見出し正規表現の単一の真実源 (FU-554).

Why 一元化するか:
    同一の「項見出し」正規表現が 5 箇所に独立実装され、**枝番条の扱いが食い違っていた**:

    | 実装 | 枝番 | 影響 |
    |---|---|---|
    | segment_parser.py:117 (旧) | `(?:の[…]+)?` = 1 段のみ | 二重枝番 (第十条の五の二) の項分割が全滅 -> segments/chunks が空 |
    | verify.py:45 (旧) | `(?:の[…]+)*` | (正しい) |
    | emit_table_md.py:55 (旧) | `(?:の[…]+)*` | (正しい) |
    | manifest/canonical_hash.py:64 (旧) | `(?:の[…]+)*` | (正しい) |
    | export/lawsy-bq/export-jsonl.py:119 (旧) | 枝番指定なし | 枝番条の項分割が全滅 (BQ export) |

    生成側 (segment_parser) と検証側 (verify/canonical_hash) で regex が違うと、
    「生成が落としたものを検証が見逃す」構造になる。本モジュールに集約し、
    枝番は **0 回以上** (`*`) に統一する。

正規表現の設計:
    - 漢数字・アラビア数字の両方を許す (corpus は漢数字だが、外部入力の揺れに耐える)。
    - 枝番 (「の二」「の五の二」) は 0 回以上。
    - 項番号 (「第三項」) は任意。
    - **capture group 有無で 2 種を提供する**: `re.split` に capture group 付き regex を
      渡すと分割結果に group 値が混入して下流の zip が壊れるため、split 用は非捕捉。
"""

from __future__ import annotations

import re

# 「## 原文 (日本語)」セクション本文 (次の H2 直前まで) を group(1) で取る。
JA_SECTION_RE = re.compile(
    r"##\s*原文\s*\(?日本語\)?\s*\n(.*?)(?=\n##\s|\Z)",
    re.DOTALL,
)

# 数字 1 文字として許す集合 (漢数字 + アラビア数字)。
_NUM = r"[零〇一二三四五六七八九十百千万0-9]"

# 「### 第N条」「### 第N条のM」「### 第N条のMのK第P項」等にマッチする本体。
# {para} に捕捉/非捕捉のいずれかを差し込む。
_HEADING_TMPL = r"^###\s+第{n}+条(?:の{n}+)*(?:第{para}項)?\s*$"

#: finditer / match 用 (項番号を group(1) で取れる)。
PARAGRAPH_HEADING_RE = re.compile(
    _HEADING_TMPL.format(n=_NUM, para=f"({_NUM}+)"),
    re.MULTILINE,
)

#: re.split 用 (capture group なし)。split 結果に group 値を混入させないため必須。
PARAGRAPH_HEADING_SPLIT_RE = re.compile(
    _HEADING_TMPL.format(n=_NUM, para=f"(?:{_NUM}+)"),
    re.MULTILINE,
)


def extract_ja_section(md_text: str) -> str | None:
    """`## 原文 (日本語)` セクションの本文を返す (無ければ None)."""
    m = JA_SECTION_RE.search(md_text)
    return m.group(1) if m else None


def split_paragraph_blocks(ja_body: str) -> tuple[str, list[str], list[str]]:
    """日本語本文を (intro, 見出し行リスト, 項本文リスト) に分解する.

    Why: verify / canonical_hash / emit_table_md / segment_parser が同一の
    「見出しで項スライスに切る」ロジックを各々書いていた。切り方が 1 箇所でも
    ずれると hash と生成が食い違うため、ここに集約する。

    Returns:
        (intro, heading_texts, paragraph_bodies)
        heading_texts[i] と paragraph_bodies[i] は対になる (len が一致)。
    """
    headings = list(PARAGRAPH_HEADING_RE.finditer(ja_body))
    if not headings:
        return ja_body, [], []
    intro = ja_body[: headings[0].start()]
    heading_texts: list[str] = []
    bodies: list[str] = []
    for i, h in enumerate(headings):
        heading_texts.append(ja_body[h.start() : h.end()])
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(ja_body)
        bodies.append(ja_body[start:end])
    return intro, heading_texts, bodies

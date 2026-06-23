#!/usr/bin/env python3
"""table_core.py -- e-Gov XML 表構造 (TableStruct) 直列化の共通コア (FU-515 Phase E).

責務 (バイブコーディング 3 原則 #1):
  「TableStruct (の XML element) -> 仮想グリッド -> pipe 行」までの純粋な
  直列化ロジックだけを提供する。chunk のウィンドウ分割・jsonl 書き出し・
  CLI 引数 parse・md ファイル I/O は範囲外 (それぞれ extract_table_from_xml.py /
  emit_table_md.py の責務)。

Why このモジュールが存在するのか (DRY・計画 §2 / briefing E-1):
  FU-515 Phase E では同じ表直列化ロジックを 3 箇所が必要とする:
    (1) build/chunks の table chunk 生成 (extract_table_from_xml.py, D-a 既存)
    (2) canonical md への表反映 (emit_table_md.py, E-3 新規)
    (3) canonical_hash のセマンティック正準化 (canonical_hash.py, E-4 新規)
  二重実装すると片方のバグ修正漏れで round-trip が永久に赤くなる。中核を
  本モジュールに一本化し 3 箇所が import することで構造的に齟齬を防ぐ。

  本モジュールは extract_table_from_xml.py から **挙動を一切変えずに** 切り出した
  (E-1 は pure refactor)。リファクタ前後で build/chunks の table.chunks.jsonl が
  バイト一致することを回帰テストで保証する (tests/test_table_core.py)。

設計上の制約 (元 extract_table_from_xml.py から継承):
  - [仮想グリッド展開] rowspan/colspan を結合先セルに値複製 (逐語複製)
  - [クラッシュ完全禁止] 異常行は plain dump フォールバック + stderr 警告
  - [セルテキスト正規化] 空白折り畳み + "|" エスケープ
"""

from __future__ import annotations

import re
import sys
from typing import Any

# ============================================================
# 定数 (元 extract_table_from_xml.py と同一)
# ============================================================

MAX_LEADIN_LEN: int = 250  # 導入文の最大文字数 (A-9②)
WHITESPACE_RE = re.compile(r"\s+")

# ============================================================
# XML ユーティリティ
# ============================================================


def get_text_recursive(elem: Any) -> str:
    """Element の全 text content を再帰結合 (Rt は skip).

    Why Rt を skip するか: Rt はルビ (振り仮名) であり本文ではない。本文非改変
    の原則上、ルビは直列化対象に含めない。
    """
    if elem is None:
        return ""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag == "Rt":
            continue
        parts.append(get_text_recursive(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def normalize_cell_text(text: str) -> str:
    """セルテキストを正規化: 空白折り畳み + | エスケープ.

    Why: ① 連続空白 (改行含む) を半角スペース 1 つに畳む = GFM の 1 セル 1 行
    要件を満たす (生改行が入ると表が崩れる)。② セル内の "|" を "\\|" にエスケープ
    して列区切りとの衝突を防ぐ。テキストの語そのものは変えない (本文外整形)。
    """
    text = WHITESPACE_RE.sub(" ", text).strip()
    text = text.replace("|", r"\|")
    return text


def trim_leadin(text: str) -> str:
    """導入文を MAX_LEADIN_LEN 文字以内にトリム (A-9②).

    読替構造「〜とあるのは〜とする」の末尾が失われないよう、
    超過時は先頭 MAX_LEADIN_LEN 文字で切ってから警告を出す。
    """
    if len(text) <= MAX_LEADIN_LEN:
        return text
    trimmed = text[:MAX_LEADIN_LEN]
    print(
        f"WARN: leadin trimmed {len(text)} -> {MAX_LEADIN_LEN} chars: {text[:60]!r}...",
        file=sys.stderr,
    )
    return trimmed


# ============================================================
# 仮想グリッド展開 (A-7③ / A-8 1-2)
# ============================================================


def expand_virtual_grid(
    rows: list[Any],
) -> list[list[str]]:
    """TableRow のリストを仮想グリッドに展開し、テキスト行リストを返す.

    rowspan/colspan を結合先セルに値を複製 (逐語複製) する。
    不整合な colspan は寛容実装: warn + 素通し (クラッシュ禁止)。
    """
    # まず全行・全列のセルを収集し、最大列数を確定
    raw_rows: list[list[tuple[str, int, int]]] = []  # (text, rowspan, colspan)
    for row in rows:
        cells_in_row: list[tuple[str, int, int]] = []
        for cell in row:
            raw_text = "".join(cell.itertext())
            text = normalize_cell_text(raw_text)
            try:
                rs = max(1, int(cell.get("rowspan") or 1))
            except (ValueError, TypeError):
                rs = 1
            try:
                cs = max(1, int(cell.get("colspan") or 1))
            except (ValueError, TypeError):
                cs = 1
            cells_in_row.append((text, rs, cs))
        raw_rows.append(cells_in_row)

    # 最大論理列数 (colspan 展開後)
    max_cols = max(
        (sum(cs for _, _, cs in row) for row in raw_rows if row),
        default=1,
    )

    # 仮想グリッド構築
    grid: list[list[str]] = []
    # carry[col] = (text, remaining_rows)
    carry: dict[int, tuple[str, int]] = {}

    for row_data in raw_rows:
        row_out: list[str] = [""] * max_cols
        col_logical = 0
        # carry をまず埋める
        for c in range(max_cols):
            if c in carry:
                text, rem = carry[c]
                row_out[c] = text
                if rem - 1 > 0:
                    carry[c] = (text, rem - 1)
                else:
                    del carry[c]

        # 今行のセルを配置
        for text, rs, cs in row_data:
            # carry が使っていない空き列を探す
            while col_logical < max_cols and row_out[col_logical] != "":
                col_logical += 1
            if col_logical >= max_cols:
                print(
                    f"WARN: table column overflow (max_cols={max_cols}), "
                    f"cell dropped: {text[:30]!r}",
                    file=sys.stderr,
                )
                break
            # colspan 分を配置
            for offset in range(cs):
                target_col = col_logical + offset
                if target_col >= max_cols:
                    print(
                        f"WARN: colspan overflow col={target_col}, max={max_cols}, "
                        f"cell={text[:30]!r}",
                        file=sys.stderr,
                    )
                    break
                row_out[target_col] = text
                if rs > 1:
                    # rowspan 残り行への複製 (A-9③: 逐語複製)
                    carry[target_col] = (text, rs - 1)
            col_logical += cs

        grid.append(row_out)

    return grid


def grid_to_pipe_rows(grid: list[list[str]]) -> list[str]:
    """グリッドを「| A | B | C |」形式の行リストに変換."""
    return ["| " + " | ".join(row) + " |" for row in grid]


def is_gfm_separator_line(line: str) -> bool:
    """GFM 表の区切り行 (例 `| --- | --- |`) かどうかを判定する.

    Why (案C・§3.5.2/§3.5.7): 法令表に意味的ヘッダは無く、区切り行は GFM が表を
    描画するための機械的装飾にすぎない。canonical_hash / 構造等価では区切り行を
    正準化除外し、表セマンティクスを markdown 外見から切り離す (md→hash と
    XML→hash を同一シーケンスに接地)。本判定を hash 側と verify 側の両方が import
    して文字列レベル一致を保証する (二重実装で drift すると round-trip 永久赤)。

    判定 (保守的): strip 後に `|` で開始・終了し、各セルが `-`/`:` のみ + 最低 1 つの
    `-` から成る行のみ True。データセル (全角ダッシュ `―`・ASCII `-` を含む通常テキスト)
    は False を返し、隔離 (Bug10) を保つ。e-Gov は空欄に全角 `―` を使い ASCII の
    `-` だけのセルは生成しないため、誤検知は構造的に起きない。
    """
    s = line.strip()
    if len(s) < 2 or not s.startswith("|") or not s.endswith("|"):
        return False
    cells = s[1:-1].split("|")
    if not cells:
        return False
    for cell in cells:
        c = cell.strip()
        if not c or (set(c) - {"-", ":"}) or "-" not in c:
            return False
    return True


# ============================================================
# 導入文の取得
# ============================================================


def get_leadin_for_table(ts: Any, parent_map: dict[Any, Any]) -> str:
    """TableStruct の親 Paragraph から ParagraphSentence を取得してトリム."""
    p = parent_map.get(ts)
    if p is None:
        return ""
    # Paragraph 直下なら ParagraphSentence を探す
    if p.tag == "Paragraph":
        ps = p.find("ParagraphSentence")
        if ps is not None:
            leadin = get_text_recursive(ps).strip()
            return trim_leadin(leadin)
    # Item/QuoteStruct 等の場合は親を辿って Paragraph を探す
    gp = parent_map.get(p)
    if gp is not None and gp.tag == "Paragraph":
        ps = gp.find("ParagraphSentence")
        if ps is not None:
            leadin = get_text_recursive(ps).strip()
            return trim_leadin(leadin)
    return ""


# ============================================================
# TableStruct -> pipe 行
# ============================================================


def table_to_pipe_rows_safe(ts: Any) -> list[str]:
    """TableStruct を pipe 行リストに変換 (A-9④: 例外時は plain dump フォールバック)."""
    try:
        table_elem = ts.find("Table") or ts
        rows = list(table_elem.iter("TableRow"))
        if not rows:
            return []
        grid = expand_virtual_grid(rows)
        return grid_to_pipe_rows(grid)
    except Exception as e:
        print(f"WARN: table render failed ({e}), falling back to plain dump", file=sys.stderr)
        raw = normalize_cell_text(get_text_recursive(ts))
        return [raw] if raw else []


def table_to_grid_safe(ts: Any) -> list[list[str]]:
    """TableStruct を仮想グリッド (行 x 列の文字列) に変換 (例外時は空グリッド).

    Why grid を直接返す版が要るか:
      E-3 (md 反映) と E-4 (canonical_hash の構造等価) は pipe 文字列でなく
      行 x 列の 2 次元配列を必要とする (GFM 区切り行の挿入・セル単位の比較)。
      table_to_pipe_rows_safe と同じ堅牢性 (例外時フォールバック) を保ちつつ
      grid を返す。plain-dump フォールバックは 1 行 1 列のグリッドにする。
    """
    try:
        table_elem = ts.find("Table") or ts
        rows = list(table_elem.iter("TableRow"))
        if not rows:
            return []
        return expand_virtual_grid(rows)
    except Exception as e:
        print(f"WARN: table render failed ({e}), falling back to plain dump", file=sys.stderr)
        raw = normalize_cell_text(get_text_recursive(ts))
        return [[raw]] if raw else []

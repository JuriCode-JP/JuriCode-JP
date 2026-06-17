#!/usr/bin/env python3
"""extract_table_from_xml.py -- e-Gov XML から TableStruct (インライン表) を抽出.

施行令・施行規則の条文内インライン表 (<TableStruct>) をテキスト直列化して
table chunk として出力する (Phase 5b Stage 1 積み残し対応)。

設計上の制約 (07_計画 A-7/A-8/A-9 の必須要件を全て満たす):
  - [全探索] //TableStruct を全走査 (Paragraph/Item/QuoteStruct/附則すべて対象)
  - [附則ルーティング] SupplProvision 内の表は supplproviso chunk と別ファイルに分離
  - [別ファイル分離] {law}-article-{N}.table.chunks.jsonl  (冪等・RMW・競合回避)
                     {law}-supplproviso.table.chunks.jsonl
  - [仮想グリッド展開] rowspan/colspan を全行・全列に複製してから直列化
  - [行ウィンドウ分割] MAX_ROWS_PER_CHUNK 行ごとに分割、先頭に導入文をプレフィックス
  - [導入文ヘッダー] 親 Paragraph の ParagraphSentence を MAX_LEADIN_LEN でトリム
  - [クラッシュ完全禁止] try-except で異常行は plain dump フォールバック + stderr 警告
  - [セルテキスト正規化] strip/collapse + "|" エスケープ

出力:
  build/chunks/{law_abbrev}/{law_abbrev}-article-{N}.table.chunks.jsonl
  build/chunks/{law_abbrev}/{law_abbrev}-supplproviso.table.chunks.jsonl
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

# tools/parse/v0.2/extract_table_from_xml.py -> parent×3 = tools/ -> tools/shared/src
# (旧コードは parent×4 = <root>/shared/src を指す誤りで、pip install -e 不在時に
#  juricode_shared を import できなかった。FU-307 切り離しにより本ファイルのみ修正)
_SHARED_SRC = Path(__file__).resolve().parent.parent.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import safe_write_jsonl  # noqa: E402

# ============================================================
# 定数
# ============================================================

MAX_LEADIN_LEN: int = 250  # 導入文の最大文字数 (A-9②)
MAX_ROWS_PER_CHUNK: int = 20  # 行ウィンドウ幅 (A-7④)
WHITESPACE_RE = re.compile(r"\s+")

# ============================================================
# XML ユーティリティ
# ============================================================


def get_text_recursive(elem: Any) -> str:
    """Element の全 text content を再帰結合 (Rt は skip)."""
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
    """セルテキストを正規化: 空白折り畳み + | エスケープ."""
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
# TableStruct → chunks
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


def build_table_chunks_for_ts(
    ts: Any,
    leadin: str,
    chunk_id_prefix: str,
    meta: dict,
    table_seq: int,
) -> list[dict]:
    """1 つの TableStruct から table chunk リスト (ウィンドウ分割) を生成.

    Returns:
        chunk のリスト (0 件の場合は空リスト)
    """
    pipe_rows = table_to_pipe_rows_safe(ts)
    if not pipe_rows:
        return []

    chunks: list[dict] = []
    total_rows = len(pipe_rows)
    window_idx = 0

    for start in range(0, total_rows, MAX_ROWS_PER_CHUNK):
        window_rows = pipe_rows[start : start + MAX_ROWS_PER_CHUNK]
        # rowspan グループが境界で分断されないよう拡張 (A-7④ 補足)
        # 簡易実装: window_rows がヘッダーのみにならないよう最低 2 行保証
        # (rowspan グループの同一ウィンドウ保証は expand_virtual_grid 側で対応済)

        text_parts: list[str] = []
        if leadin:
            text_parts.append(leadin)
        text_parts.extend(window_rows)
        text = "\n".join(text_parts).strip()
        if not text:
            window_idx += 1
            continue

        chunk_id = (
            f"{chunk_id_prefix}-tbl{table_seq}-w{window_idx}"
            if total_rows > MAX_ROWS_PER_CHUNK
            else f"{chunk_id_prefix}-tbl{table_seq}"
        )
        chunk: dict = {
            "id": chunk_id,
            "segment_type": "table",
            "modality": "unspecified",
            "text": text,
        }
        chunk.update(meta)
        chunks.append(chunk)
        window_idx += 1

    return chunks


# ============================================================
# 本則の表抽出
# ============================================================


def extract_main_table_chunks(
    root: Any,
    parent_map: dict[Any, Any],
    law_abbrev: str,
    law_id: str,
    law_name_ja: str,
) -> dict[str, list[dict]]:
    """本則 Article 配下の TableStruct を抽出.

    Returns:
        article_num -> chunk リスト の dict
    """
    result: dict[str, list[dict]] = {}
    table_seq_per_article: dict[str, int] = {}

    for ts in root.iter("TableStruct"):
        # SupplProvision 配下はスキップ
        current = ts
        in_sp = False
        while True:
            current = parent_map.get(current)
            if current is None:
                break
            if current.tag == "SupplProvision":
                in_sp = True
                break
        if in_sp:
            continue

        # 所属 Article を ancestor から再解決 (ループ変数使い回し禁止 A-8 2-1)
        art_elem = None
        current = ts
        while True:
            current = parent_map.get(current)
            if current is None:
                break
            if current.tag == "Article":
                art_elem = current
                break
        if art_elem is None:
            print(
                "WARN: TableStruct in main provision has no Article ancestor, skipped",
                file=sys.stderr,
            )
            continue

        art_num = art_elem.get("Num", "")
        if not art_num:
            continue

        leadin = get_leadin_for_table(ts, parent_map)

        article_id = f"{law_abbrev}-art-{art_num}"
        seq = table_seq_per_article.get(article_id, 0) + 1
        table_seq_per_article[article_id] = seq

        meta: dict = {
            "article_id": article_id,
            "law_id": law_id,
            "law_name_ja": law_name_ja,
            "article_number": art_num,
        }
        chunks = build_table_chunks_for_ts(ts, leadin, article_id, meta, seq)
        if chunks:
            result.setdefault(art_num, []).extend(chunks)

    return result


# ============================================================
# 附則の表抽出
# ============================================================


def extract_supplproviso_table_chunks(
    root: Any,
    parent_map: dict[Any, Any],
    law_abbrev: str,
    law_id: str,
    law_name_ja: str,
) -> list[dict]:
    """SupplProvision 内の TableStruct を抽出.

    chunk_id は extract_supplproviso_from_xml.py の命名規則と整合させる:
      '{law_abbrev}-supplproviso-{sp_idx}-art{art_num}-p{p_idx}-tbl{seq}'
    """
    chunks: list[dict] = []

    for sp_idx, sp in enumerate(root.iter("SupplProvision"), 1):
        amend_law_num = sp.get("AmendLawNum", "")
        table_seq_per_para: dict[str, int] = {}

        for ts in sp.iter("TableStruct"):
            # 所属 Article / Paragraph を ancestor から再解決
            art_elem = None
            para_elem = None
            current = ts
            while True:
                current = parent_map.get(current)
                if current is None:
                    break
                if current.tag == "Paragraph" and para_elem is None:
                    para_elem = current
                if current.tag == "Article" and art_elem is None:
                    art_elem = current
                if current.tag == "SupplProvision":
                    break

            art_num = art_elem.get("Num", "") if art_elem is not None else ""
            para_num = para_elem.get("Num", "1") if para_elem is not None else "1"

            id_base = (
                f"{law_abbrev}-supplproviso-{sp_idx}-art{art_num}-p{para_num}"
                if art_num
                else f"{law_abbrev}-supplproviso-{sp_idx}-p{para_num}"
            )

            leadin = get_leadin_for_table(ts, parent_map)

            seq = table_seq_per_para.get(id_base, 0) + 1
            table_seq_per_para[id_base] = seq

            meta: dict = {
                "law_id": law_id,
                "law_name_ja": law_name_ja,
                "law_abbrev": law_abbrev,
                "supplproviso_id": sp_idx,
                "amend_law_num": amend_law_num or None,
            }
            if art_num:
                meta["supplproviso_article_number"] = art_num
            if para_num:
                try:
                    meta["paragraph_number"] = int(para_num)
                except ValueError:
                    pass

            new_chunks = build_table_chunks_for_ts(ts, leadin, id_base, meta, seq)
            chunks.extend(new_chunks)

    return chunks


# ============================================================
# law_abbrev → law_id mapping
# ============================================================


_LAW_ID_RE = re.compile(r"^law_id:\s*([A-Z0-9_]+)")


def _extract_law_id(md_path: Path) -> str | None:
    """先頭 md の frontmatter から law_id を行正規表現で抽出 (無ければ None).

    Why: extract_table が md から消費するのは law_id / law_name_ja のみ
    (briefing §2 call graph)。YAML パーサーでなく行正規表現で十分かつ高速。
    """
    try:
        with md_path.open(encoding="utf-8") as fh:
            for line in fh:
                m = _LAW_ID_RE.match(line.strip())
                if m:
                    return m.group(1)
    except OSError:
        return None
    return None


def _git_last_commit_iso(path: Path) -> str:
    """path の最終更新 commit 日時 (ISO) を返す。git 不在/履歴なしでも例外を出さない.

    Why: duplicate law_abbrev 検出時、どちらの dir を残す/削除すべきかを人間が
    判断できるよう各 dir の recency を併記する (briefing §4 / 第1巡 #1b)。診断専用。
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ci", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or "(no git history)"
    except Exception:
        # 診断用ゆえ git 不在/タイムアウトでも握りつぶし placeholder を返す
        return "(git unavailable)"


def build_law_abbrev_to_id_phase(data_dir: Path) -> dict[str, tuple[str, str]]:
    """data_dir 直下の phase* を走査し law_abbrev -> (law_id, phase) を構築.

    Why: GO② により再帰両走査は採用せず phase* 直下のみ走査。
    fail-loud 3 点: (1) 同一 law_abbrev の重複は片選び/skip 禁止
    (skip は欠落 chunk を生む = 本 FU が直すバグそのもの)、
    (2) md を持つ law_dir が law_id を生まない silent drop も禁止 (coverage 欠落防止)、
    (3) 1 法令も発見できない (誤った --data-dir 等) も silent な 0 件出力を防ぐため fail-loud。
    """
    out: dict[str, tuple[str, str]] = {}
    seen_src: dict[str, Path] = {}
    for phase_dir in sorted(data_dir.iterdir()):
        if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
            continue
        for law_dir in sorted(phase_dir.iterdir()):
            if not law_dir.is_dir():
                continue
            mds = sorted(law_dir.glob("*-article-*.md"))
            if not mds:
                continue
            law_id = _extract_law_id(mds[0])
            if law_id is None:
                raise ValueError(
                    "law_id を frontmatter から抽出できません (silent-drop 防止):\n"
                    f"  law_dir: {law_dir}\n"
                    f"  先頭 md: {mds[0]}"
                )
            abbrev = law_dir.name
            if abbrev in seen_src:
                prev = seen_src[abbrev]
                raise ValueError(
                    "重複する law_abbrev を検出 (fail-loud / 片選び・skip 禁止):\n"
                    f"  abbrev: {abbrev}\n"
                    f"  (1) {prev}  [最終更新 {_git_last_commit_iso(prev)}]\n"
                    f"  (2) {law_dir}  [最終更新 {_git_last_commit_iso(law_dir)}]\n"
                    "  どちらを残すか判断のうえ一方を整理してください。"
                )
            seen_src[abbrev] = law_dir
            out[abbrev] = (law_id, phase_dir.name)
    if not out:
        raise ValueError(
            "phase* 直下に法令を 1 件も発見できません (silent な 0 件出力を防ぐ fail-loud):\n"
            f"  data_dir: {data_dir}\n"
            "  --data-dir が canonical corpus (phase* を直下に持つ) を指しているか確認してください。"
        )
    return out


def build_law_id_to_name_ja(data_dir: Path) -> dict[str, str]:
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


# ============================================================
# main
# ============================================================


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/v0.2"),
        help="phase* を直下に持つ corpus root (既定: data/v0.2 = canonical Master, GO②)",
    )
    ap.add_argument("--law-only", default=None, help="特定 law_abbrev のみ処理 (テスト用)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("Building law_abbrev -> (law_id, phase) map ...", file=sys.stderr)
    law_map = build_law_abbrev_to_id_phase(args.data_dir)
    print(f"  {len(law_map)} laws found in {args.data_dir}", file=sys.stderr)

    print("Building law_id -> law_name_ja map ...", file=sys.stderr)
    law_name_ja_map = build_law_id_to_name_ja(args.data_dir)
    print(f"  {len(law_name_ja_map)} entries", file=sys.stderr)

    if args.law_only:
        if args.law_only not in law_map:
            print(f"ERROR: law_abbrev not found: {args.law_only}", file=sys.stderr)
            return 1
        law_map = {args.law_only: law_map[args.law_only]}

    total_main = 0
    total_sp = 0
    laws_no_table: list[str] = []
    laws_no_xml: list[str] = []

    for law_abbrev, (law_id, _phase) in sorted(law_map.items()):
        xml_path = args.xml_dir / f"{law_id}.xml"
        if not xml_path.exists():
            laws_no_xml.append(law_abbrev)
            continue

        try:
            tree = ET.parse(xml_path)
        except Exception as e:
            print(f"WARN: XML parse error {xml_path}: {e}", file=sys.stderr)
            continue

        root = tree.getroot()
        # parent_map は表ごとに再解決に使う (ループ変数使い回し禁止 A-8 2-1)
        parent_map: dict[Any, Any] = {child: parent for parent in root.iter() for child in parent}

        law_name_ja = law_name_ja_map.get(law_id, "")
        out_dir = args.chunks_dir / law_abbrev

        # --- 本則の表 ---
        main_by_article = extract_main_table_chunks(
            root, parent_map, law_abbrev, law_id, law_name_ja
        )
        main_chunk_count = sum(len(v) for v in main_by_article.values())

        # --- 附則の表 ---
        sp_chunks = extract_supplproviso_table_chunks(
            root, parent_map, law_abbrev, law_id, law_name_ja
        )

        if main_chunk_count == 0 and not sp_chunks:
            laws_no_table.append(law_abbrev)
            continue

        print(
            f"  {law_abbrev}: main_chunks={main_chunk_count}, sp_chunks={len(sp_chunks)}",
            file=sys.stderr,
        )
        total_main += main_chunk_count
        total_sp += len(sp_chunks)

        if args.dry_run:
            continue

        out_dir.mkdir(parents=True, exist_ok=True)

        # 本則: 条ごとに別ファイル (A-8 4-1: 別ファイル分離)
        # ファイル名: {law_abbrev}-article-{N}.table.chunks.jsonl
        for art_num, art_chunks in main_by_article.items():
            out_file = out_dir / f"{law_abbrev}-article-{art_num}.table.chunks.jsonl"
            safe_write_jsonl(out_file, art_chunks)

        # 附則: まとめて 1 ファイル
        if sp_chunks:
            out_file = out_dir / f"{law_abbrev}-supplproviso.table.chunks.jsonl"
            safe_write_jsonl(out_file, sp_chunks)

    print("\n=== Summary ===", file=sys.stderr)
    print(f"Main table chunks generated: {total_main}", file=sys.stderr)
    print(f"SupplProviso table chunks:   {total_sp}", file=sys.stderr)
    print(f"Laws with no tables:         {len(laws_no_table)}", file=sys.stderr)
    for a in laws_no_table:
        print(f"  - {a}", file=sys.stderr)
    print(f"Laws with no XML:            {len(laws_no_xml)}", file=sys.stderr)
    for a in laws_no_xml:
        print(f"  - {a}", file=sys.stderr)
    if args.dry_run:
        print("\n(dry-run, no files written)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

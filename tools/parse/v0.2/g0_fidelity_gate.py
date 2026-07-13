#!/usr/bin/env python3
"""g0_fidelity_gate.py -- G0 忠実性ゲート (Phase 0: 調査・計測のみ、修正はしない).

2 段階の比較を **分離** して実行する (合算禁止):
  G0-a: e-Gov XML の条文本文 <-> 正本 md 単体 (chunk と合算しない)
  G0-b: 正本 md <-> その条の chunk 群 (build/chunks/)

比較方法 (Phase 0 probe 仕様):
  - 正規化は「空白・改行の畳み込み (= 全空白文字の除去)」のみ。文字は変えない。
  - 合否判定は正規化後の完全一致 (exact equal)。部分一致 (contains) を合否に使わない。
    (unit 単位の位置探索は「何が欠けたか」の分類診断にのみ使う)
  - Phase 0 の出力は pass/fail ではなく分類付き diff レポート (build/fidelity-report/)。

既存抽出器の再利用 (新規のテキスト抽出セマンティクスを書かない):
  - XML テキスト抽出: parse-egov.py の extract_all_text (md 生成と同一関数)
  - 表グリッド直列化: table_core.table_to_grid_safe / is_gfm_separator_line
  - md 本文抽出: verify.py の extract_ja_paragraphs_from_md (manifest hash と同一抽出)
  - law_abbrev -> (law_id, phase) マップ: extract_kou_from_xml.build_law_abbrev_to_id_phase
  本モジュールが新規に持つのは「XML 要素の文書順走査 (タグ dispatch)」と「分類集計」のみ。

Why:
  verify.py は md <-> manifest の自己整合しか見ない (verify.py:186-190) ため、
  XML -> md の変換で落ちた本文 (号・細別・表・枝番) を検出できない。本ゲートが
  初めて e-Gov XML を ground truth として突合し、「欠落の全体像」を数値化する。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
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

_HERE = Path(__file__).resolve().parent  # tools/parse/v0.2
_PARSE_DIR = _HERE.parent  # tools/parse
_SHARED_SRC = _PARSE_DIR.parent / "shared" / "src"
for _p in (str(_HERE), str(_PARSE_DIR), str(_SHARED_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from juricode_shared import safe_write_text  # noqa: E402
from table_core import is_gfm_separator_line, table_to_grid_safe  # noqa: E402


def _load_module(name: str, path: Path):
    """ハイフン入りファイル名のモジュールを import する (確立パターン).

    Why: parse-egov.py はハイフンのため通常 import 不可。bulk-kfs-*.py 等と
    同じ spec_from_file_location パターンで読み込む (sys.modules 登録は
    dataclass の module 解決に必須)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_parse_egov = _load_module("_g0_parse_egov", _PARSE_DIR / "parse-egov.py")
_verify = _load_module("_g0_verify", _PARSE_DIR / "verify.py")
_extract_kou = _load_module("_g0_extract_kou", _HERE / "extract_kou_from_xml.py")

extract_all_text = _parse_egov.extract_all_text
extract_ja_paragraphs_from_md = _verify.extract_ja_paragraphs_from_md
build_law_abbrev_to_id_phase = _extract_kou.build_law_abbrev_to_id_phase

# 全空白 (半角/タブ/改行/全角 U+3000) の除去 = 「空白・改行の畳み込み」の最小実装。
# 文字自体は一切変えない (全角半角変換・漢数字変換をしない)。
_WS_RE = re.compile(r"[\s　]+")

# segment_parser.py 由来の chunk type (G0-b で md と突合する側)。
# kou / table / supplproviso* は XML 直接経路、rollup* は派生重複なので除外する。
PARSER_CHUNK_TYPES = frozenset(
    {"simple", "honbun", "tadashi", "zen_dan", "kou_dan", "hashira", "junyou", "tokusoku"}
)

# マーカーは行頭挿入とは限らない: render_v02_md (segment_parser.py:563) は
# search_str の直前に "<marker>\n" を replace 挿入するため、tadashi/kou_dan の
# マーカーは前段テキストと同一行の末尾に付く。行単位でなく inline で剥ぐ。
MARKER_RE = re.compile(r"<!--[^>]*-->")

# Paragraph 直下でテキスト比較の対象にしないタグ (番号ラベル・キャプション)。
# ParagraphNum は「２」等の項番号ラベルで、md では見出し (### 第N条第M項) に
# 構造として写像されるため本文比較から除外する。
_PARA_SKIP_TAGS = frozenset({"ParagraphNum", "ParagraphCaption"})


def norm(s: str) -> str:
    """空白・改行を畳み込む (全空白除去)。文字は変えない。"""
    return _WS_RE.sub("", s or "")


@dataclass
class Unit:
    """XML 条文本文の最小比較単位 (文書順)."""

    kind: str  # para | proviso | item | subitem | table | list | other
    text: str
    meta: dict = field(default_factory=dict)


def _table_unit(ts: Any) -> Unit:
    """TableStruct を 1 unit に直列化 (セルは table_core 再利用).

    Why cells を meta に持つか: md 側は GFM パイプ表 (書式差) なので、表全体の
    完全一致が落ちても「全セルが md にあるか」で 表の書式差 / 表の欠落 を分類する。
    """
    grid = table_to_grid_safe(ts)
    cells = [c for row in grid for c in row if norm(c)]
    title_el = ts.find("TableStructTitle")
    title = extract_all_text(title_el).strip() if title_el is not None else ""
    text = (title + "".join(cells)) if (title or cells) else extract_all_text(ts)
    return Unit("table", text, {"cells": cells, "title": title})


def _walk_item(elem: Any) -> list[Unit]:
    """Item / SubitemN を文書順に unit 化 (テキスト抽出は extract_all_text に委譲).

    Why 号番号 (ItemTitle「一」「イ」) を比較対象テキストに含めるか (format-spec §5.2):
    項番号 (ParagraphNum) は md の見出し `### 第N条第K項` に構造として写像されるので
    本文比較から外すが、**号番号は本文行の一部として原文どおり書く**のが案A の規約。
    よって XML 側の号 unit も「番号 ＋ 本文」で比較しないと、md 側の番号が「過剰」に
    見えてしまう。
    """
    tag = elem.tag
    kind = "item" if tag == "Item" else "subitem"
    title_tag, sent_tag = f"{tag}Title", f"{tag}Sentence"
    units: list[Unit] = []
    title = ""
    for child in elem:
        ct = child.tag
        if ct == title_tag:
            title = extract_all_text(child).strip()
        elif ct == sent_tag:
            body = extract_all_text(child)
            units.append(Unit(kind, f"{title}{body}" if title else body, {"title": title}))
        elif ct == "TableStruct":
            units.append(_table_unit(child))
        elif ct == "List":
            units.append(Unit("list", extract_all_text(child)))
        elif ct.startswith("Subitem"):
            units.extend(_walk_item(child))
        else:
            txt = extract_all_text(child).strip()
            if txt:
                units.append(Unit("other", txt, {"tag": ct}))
    return units


def _walk_paragraph(para: Any) -> list[Unit]:
    """Paragraph を文書順に unit 化。ただし書は Sentence@Function で区別."""
    units: list[Unit] = []
    for child in para:
        tag = child.tag
        if tag in _PARA_SKIP_TAGS:
            continue
        if tag == "ParagraphSentence":
            sentences = child.findall("Sentence")
            if sentences:
                for s in sentences:
                    kind = "proviso" if s.get("Function") == "proviso" else "para"
                    units.append(Unit(kind, extract_all_text(s)))
            else:
                units.append(Unit("para", extract_all_text(child)))
        elif tag == "Item":
            units.extend(_walk_item(child))
        elif tag == "TableStruct":
            units.append(_table_unit(child))
        elif tag == "List":
            units.append(Unit("list", extract_all_text(child)))
        else:
            txt = extract_all_text(child).strip()
            if txt:
                units.append(Unit("other", txt, {"tag": tag}))
    return units


def walk_main_articles(root: Any) -> tuple[dict[str, dict], list[str]]:
    """MainProvision 配下の Article -> 項ごとの unit 群。範囲条 (Num にコロン) は別掲.

    Returns:
        (article_num -> {"groups": 項ごとの unit list, "extra": 条直下のその他 unit},
         range_article_nums)
        article_num は md 規約 (hyphen) に正規化済み。

    Why 項ごとにグループ化するか: md 側は「### 第N条第K項」で項ブロックを持つ。
    条全体を 1 本の文字列にすると、繰り返しの多い条文 (通算法人系など) で
    unit が別の項の同一文言に吸着し、順序違反の false positive を生む
    (houjin-zei-hou art 64-7 で実測)。項ブロック内でのみ探索して偶然一致を断つ。
    """
    law = root if root.tag == "Law" else root.find(".//Law")
    if law is None:
        raise ValueError("No <Law> element")
    body = law.find("LawBody")
    if body is None:
        raise ValueError("No <LawBody> element")
    main = body.find("MainProvision")
    if main is None:
        raise ValueError("No <MainProvision> element")

    articles: dict[str, dict] = {}
    ranges: list[str] = []
    for art in main.iter("Article"):
        num = (art.get("Num") or "").strip().replace("_", "-")
        if not num:
            continue
        if ":" in num:
            ranges.append(num)  # parse-egov.py:224 が意図的に skip する範囲削除条
            continue
        groups: list[list[Unit]] = []
        extra: list[Unit] = []
        for child in art:
            if child.tag == "Paragraph":
                groups.append(_walk_paragraph(child))
            elif child.tag in ("ArticleTitle", "ArticleCaption"):
                continue  # 構造ラベル (md では見出し行に写像)
            else:
                txt = extract_all_text(child).strip()
                if txt:
                    extra.append(Unit("other", txt, {"tag": child.tag}))
        articles[num] = {"groups": groups, "extra": extra}
    return articles, ranges


def count_appdx_units(root: Any) -> int:
    """LawBody 直下の別表等 (Appdx*) の個数 (law-level、md 対象ファイルなし)."""
    law = root if root.tag == "Law" else root.find(".//Law")
    body = law.find("LawBody") if law is not None else None
    if body is None:
        return 0
    return sum(1 for child in body if child.tag.startswith("Appdx"))


def md_paragraph_texts(md_text: str) -> tuple[list[str], int]:
    """md 本文 (原文セクション) をマーカー除去済み段落テキストにする.

    抽出は verify.py の extract_ja_paragraphs_from_md を再利用 (manifest hash と
    同一の抽出)。その上で <!-- ... --> マーカー行だけ剥ぐ。
    """
    paras = extract_ja_paragraphs_from_md(md_text)
    markers = 0
    cleaned: list[str] = []
    for p in paras:
        markers += len(MARKER_RE.findall(p))
        cleaned.append(MARKER_RE.sub("", p).strip())
    return cleaned, markers


# 2-pass マッチングの骨格 unit 最小長 (norm 後)。
# Why: 短い unit (号「第八十条」4 字、「その該当することとなつた日」13 字) は
# 他の項本文の中に偶然出現し得るため、単純 cursor 探索では ORDER/OK の誤判定を
# 生む (houjin-zei-hou art 10 / art 150 で実測)。長い unit だけで先に順序骨格を
# 確定し、短い unit は骨格間の「窓」の内側でのみ探索する。順序違反の主張は
# 骨格 unit に限る (偶然一致で順序を主張しない)。
_SKELETON_MIN_LEN = 30

_MISSING_CATEGORY = {
    "item": "kou_missing",
    "subitem": "saibetsu_missing",
    "proviso": "tadashi_missing",
    "para": "honbun_missing",
    "list": "list_missing",
    "table": "table_missing",
    "other": "unclassified_missing",
}


def compare_article(groups: list[list[Unit]], extra: list[Unit], md_blocks: list[str]) -> dict:
    """G0-a 診断: 項ブロック単位で XML unit と md を突合し diff を分類する.

    合否は exact フィールド (完全一致) のみ。位置探索は分類診断にのみ使う。
    項数が一致する場合は「XML 第 i 項の unit は md 第 i ブロック内でのみ探索」する
    (別の項の同一文言への吸着 = 偶然一致を構造的に断つ)。項数不一致の場合は
    全 unit を 1 グループとして全文に対する探索にフォールバックし、その旨を
    paragraph_count_mismatch に立てる。
    """
    md_norms = [norm(b) for b in md_blocks]
    whole = "".join(md_norms)
    all_units = [u for g in groups for u in g] + extra
    xml_norm = norm("".join(u.text for u in all_units))
    result: dict[str, Any] = {
        "exact": xml_norm == whole,
        "xml_chars": len(xml_norm),
        "md_chars": len(whole),
        "paragraph_count_xml": len(groups),
        "paragraph_count_md": len(md_blocks),
        "paragraph_count_mismatch": len(groups) != len(md_blocks),
        "missing": {},  # category -> count
        "missing_samples": [],
        "order_violations": 0,
        "excess_chars": 0,
        "excess_sample": "",
        "table_format_diff": 0,
        "short_match_ambiguous": 0,
    }
    if result["exact"]:
        return result

    if result["paragraph_count_mismatch"]:
        blocks = [(all_units, whole)]
    else:
        blocks = list(zip(groups, md_norms, strict=True))
        for u in extra:
            t = norm(u.text)
            if t and t not in whole:
                _classify_unmatched(result, u, t, whole)

    excess_runs: list[str] = []
    for units, block_norm in blocks:
        excess_runs.extend(_match_block(units, block_norm, whole, result))
    result["excess_chars"] = sum(len(r) for r in excess_runs)
    if excess_runs:
        result["excess_sample"] = excess_runs[0][:80]
    return result


def _match_block(units: list[Unit], block_norm: str, whole: str, result: dict) -> list[str]:
    """1 項ブロック内の 2-pass マッチング。ブロック内で未カバーの run を返す.

    pass 1: 骨格 unit (>= _SKELETON_MIN_LEN) を文書順 cursor で確定。ブロック内の
            手前 or ブロック外に存在すれば順序違反 (それ以外は欠落分類)。
    pass 2: 短 unit は骨格間の窓内でのみ探索 (偶然一致は順序と主張しない)。
    """
    texts = [norm(u.text) for u in units]
    spans: list[tuple[int, int] | None] = [None] * len(units)

    cursor = 0
    for i, (u, t) in enumerate(zip(units, texts, strict=True)):
        if not t or len(t) < _SKELETON_MIN_LEN:
            continue
        idx = block_norm.find(t, cursor)
        if idx >= 0:
            spans[i] = (idx, idx + len(t))
            cursor = idx + len(t)
            continue
        idx_any = block_norm.find(t)
        if idx_any >= 0:
            result["order_violations"] += 1  # ブロック内の手前に存在 = 順序の入れ替わり
            spans[i] = (idx_any, idx_any + len(t))
        elif t in whole:
            result["order_violations"] += 1  # 別の項ブロックに存在 = 項配置のズレ
        else:
            _classify_unmatched(result, u, t, whole)

    for i, (u, t) in enumerate(zip(units, texts, strict=True)):
        if not t or spans[i] is not None or len(t) >= _SKELETON_MIN_LEN:
            continue
        lo = max((s[1] for s in spans[:i] if s), default=0)
        hi = min((s[0] for s in spans[i + 1 :] if s), default=len(block_norm))
        if hi < lo:  # 骨格自体が順序破壊 -> 窓が定義できないのでブロック全域
            lo, hi = 0, len(block_norm)
        idx = block_norm.find(t, lo, hi)
        if idx >= 0:
            spans[i] = (idx, idx + len(t))
        else:
            if whole.find(t) >= 0:
                # 窓外・ブロック外の一致は偶然一致と区別不能 -> 欠落に分類し別掲
                result["short_match_ambiguous"] += 1
            _classify_unmatched(result, u, t, whole)

    covered = bytearray(len(block_norm))
    for s in spans:
        if s:
            covered[s[0] : s[1]] = b"\x01" * (s[1] - s[0])
    return _uncovered_runs(block_norm, covered)


def _classify_unmatched(result: dict, u: Unit, t: str, md_norm: str) -> None:
    """md に見つからなかった unit を分類 (表はセル単位で書式差/欠落を判別)."""
    if u.kind == "table" and u.meta.get("cells"):
        cells = [norm(c) for c in u.meta["cells"] if norm(c)]
        if cells and all(c in md_norm for c in cells):
            result["table_format_diff"] += 1
            return
    _add_missing(result, u, t)


def _add_missing(result: dict, u: Unit, t: str) -> None:
    """欠落 unit を分類バケットに積む (推測で分類を埋めない: other は未分類)."""
    cat = _MISSING_CATEGORY.get(u.kind, "unclassified_missing")
    result["missing"][cat] = result["missing"].get(cat, 0) + 1
    if len(result["missing_samples"]) < 5:
        label = u.meta.get("title") or u.meta.get("tag") or u.kind
        result["missing_samples"].append(f"[{cat}:{label}] {t[:60]}")


def _uncovered_runs(text: str, covered: bytearray) -> list[str]:
    """カバーされなかった文字列 run (= 過剰候補) を列挙."""
    runs: list[str] = []
    start = None
    for i, c in enumerate(covered):
        if not c and start is None:
            start = i
        elif c and start is not None:
            runs.append(text[start:i])
            start = None
    if start is not None:
        runs.append(text[start:])
    return runs


# ============================================================
# G0-b: 正本 md <-> chunks
# ============================================================


def load_chunks(chunk_dir: Path, law_abbrev: str, art_num: str) -> tuple[list[dict], list[dict]]:
    """条の chunk 群 (本体 + table 別ファイル) を読む."""

    def _read(p: Path) -> list[dict]:
        if not p.exists():
            return []
        out = []
        with p.open(encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    out.append(json.loads(ln))
        return out

    base = chunk_dir / law_abbrev / f"{law_abbrev}-article-{art_num}"
    # table chunk のファイル名は枝番を underscore で持つ (extract_table_from_xml.py が
    # XML @Num をそのまま使うため。例 chihou-zei-hou-article-15_5.table.chunks.jsonl)。
    # 本体 chunk は hyphen 形式なので、table 側は両方を試す。
    base_us = chunk_dir / law_abbrev / f"{law_abbrev}-article-{art_num.replace('-', '_')}"
    table = _read(Path(f"{base}.table.chunks.jsonl"))
    if not table and "-" in art_num:
        table = _read(Path(f"{base_us}.table.chunks.jsonl"))
    return _read(Path(f"{base}.chunks.jsonl")), table


def compare_md_to_chunks(md_paras: list[str], chunks: list[dict], table_chunks: list[dict]) -> dict:
    """G0-b 診断: 正本 md -> chunk 変換の欠落・過剰を分類する.

    - parser 系 chunk (segment_parser 由来) の連結 <-> md 非表本文 の完全一致が本判定。
      (emit_table_md は md のみに表を足すため、表行は分離して table chunk と突合)
    - kou / table chunk は XML 直接経路 (F3) なので「chunk のみに存在」を別掲する。
    """
    md_nontable_lines: list[str] = []
    md_table_rows: list[str] = []
    for p in md_paras:
        for ln in p.splitlines():
            if ln.lstrip().startswith("|"):
                if not is_gfm_separator_line(ln):
                    md_table_rows.append(ln)
            else:
                md_nontable_lines.append(ln)
    md_main_norm = norm("".join(md_nontable_lines))

    parser_texts = [
        c.get("text", "") for c in chunks if c.get("segment_type") in PARSER_CHUNK_TYPES
    ]
    kou_texts = [c.get("text", "") for c in chunks if c.get("segment_type") == "kou"]
    parser_norm = norm("".join(parser_texts))

    result: dict[str, Any] = {
        "exact": parser_norm == md_main_norm,
        "md_chars": len(md_main_norm),
        "chunk_chars": len(parser_norm),
        "all_chunks_missing": bool(md_main_norm) and not parser_texts and not kou_texts,
        "parser_chunks_missing": bool(md_main_norm) and not parser_texts,
        "md_not_in_chunks_chars": 0,
        "chunk_not_in_md_count": 0,
        "kou_chunks": len(kou_texts),
        "kou_chunks_not_in_md": 0,
        "table_rows_md": len(md_table_rows),
        "table_rows_not_in_table_chunks": 0,
    }

    if not result["exact"]:
        covered = bytearray(len(md_main_norm))
        cursor = 0
        for t in parser_texts:
            tn = norm(t)
            if not tn:
                continue
            idx = md_main_norm.find(tn, cursor)
            if idx < 0:
                idx = md_main_norm.find(tn)
            if idx < 0:
                result["chunk_not_in_md_count"] += 1
                continue
            covered[idx : idx + len(tn)] = b"\x01" * len(tn)
            cursor = max(cursor, idx + len(tn))
        result["md_not_in_chunks_chars"] = sum(
            len(r) for r in _uncovered_runs(md_main_norm, covered)
        )

    md_all_norm = norm("".join(md_paras))
    for t in kou_texts:
        if norm(t) and norm(t) not in md_all_norm:
            result["kou_chunks_not_in_md"] += 1

    # table chunk のテキストもパイプ付き GFM 行 (leadin + "| a | b |" 群) なので、
    # md 行と同様に書式パイプを剥いでから比較する (剥がないと全行が不一致になる)
    table_all = norm(
        "".join(
            _strip_format_pipes(ln)
            for c in table_chunks
            for ln in c.get("text", "").splitlines()
            if not is_gfm_separator_line(ln)
        )
    )
    for row in md_table_rows:
        row_cells = norm(_strip_format_pipes(row))
        if row_cells and row_cells not in table_all:
            result["table_rows_not_in_table_chunks"] += 1
    return result


def _strip_format_pipes(line: str) -> str:
    r"""GFM 行の書式 "|" を剥ぎ、セル内エスケープ "\|" は文字 "|" に戻す.

    Why: XML 側のセル原文は raw "|" を持ち得る (normalize_cell_text が md 側で
    "\|" にエスケープする)。書式のパイプだけ落とし文字は変えない。
    """
    return line.replace("\\|", "\x00").replace("|", "").replace("\x00", "|")


# ============================================================
# law 単位の実行
# ============================================================


def process_law(
    law_abbrev: str,
    law_id: str,
    phase: str,
    md_dir: Path,
    xml_path: Path,
    chunks_dir: Path,
) -> dict:
    """1 法令の G0-a / G0-b を実行し law-level レポート dict を返す."""
    report: dict[str, Any] = {
        "law_abbrev": law_abbrev,
        "law_id": law_id,
        "phase": phase,
        "xml": str(xml_path),
    }

    manifest_path = md_dir / "_source-manifest.json"
    xml_bytes = xml_path.read_bytes()
    report["xml_sha256"] = hashlib.sha256(xml_bytes).hexdigest()
    report["manifest_xml_sha_match"] = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report["manifest_xml_sha_match"] = manifest.get("source_xml_sha256") == report["xml_sha256"]

    root = ET.fromstring(xml_bytes.decode("utf-8"))
    xml_articles, range_articles = walk_main_articles(root)
    report["appdx_count"] = count_appdx_units(root)
    report["range_articles_skipped"] = range_articles

    md_files = {
        p.name[len(law_abbrev) + len("-article-") : -3]: p
        for p in md_dir.glob(f"{law_abbrev}-article-*.md")
    }

    report["xml_article_count"] = len(xml_articles)
    report["md_article_count"] = len(md_files)
    report["articles_missing_md"] = sorted(set(xml_articles) - set(md_files))
    report["articles_md_only"] = sorted(set(md_files) - set(xml_articles))

    g0a: dict[str, dict] = {}
    g0b: dict[str, dict] = {}
    marker_lines_total = 0
    files_with_markers = 0

    for num, art_units in sorted(xml_articles.items()):
        md_path = md_files.get(num)
        if md_path is None:
            continue  # articles_missing_md で計上済み
        md_text = md_path.read_text(encoding="utf-8")
        md_paras, marker_lines = md_paragraph_texts(md_text)
        marker_lines_total += marker_lines
        if marker_lines:
            files_with_markers += 1
        # md 側の GFM 表行はセル文字のみに畳む (emit_table_md の "|" は書式)
        md_blocks = [
            "".join(
                _strip_format_pipes(ln) for ln in p.splitlines() if not is_gfm_separator_line(ln)
            )
            for p in md_paras
        ]
        g0a[num] = compare_article(art_units["groups"], art_units["extra"], md_blocks)
        chunks, table_chunks = load_chunks(chunks_dir, law_abbrev, num)
        g0b[num] = compare_md_to_chunks(md_paras, chunks, table_chunks)

    report["marker_lines_total"] = marker_lines_total
    report["files_with_markers"] = files_with_markers
    report["g0a"] = g0a
    report["g0b"] = g0b
    return report


def aggregate(reports: list[dict]) -> dict:
    """全法令の分類別合計 (summary.md の元データ)."""
    agg: dict[str, Any] = {
        "laws": len(reports),
        "xml_articles": 0,
        "md_articles": 0,
        "articles_missing_md": 0,
        "articles_md_only": 0,
        "g0a_exact": 0,
        "g0a_diff": 0,
        "g0a_missing_by_category": {},
        "g0a_order_violations": 0,
        "g0a_short_match_ambiguous": 0,
        "g0a_paragraph_count_mismatch": 0,
        "g0a_articles_with_excess": 0,
        "g0a_table_format_diff": 0,
        "g0b_exact": 0,
        "g0b_diff": 0,
        "g0b_all_chunks_missing": 0,
        "g0b_parser_chunks_missing": 0,
        "g0b_articles_md_not_in_chunks": 0,
        "g0b_kou_chunks_not_in_md": 0,
        "g0b_table_rows_not_in_table_chunks": 0,
        "marker_lines_total": 0,
        "files_with_markers": 0,
        "appdx_total": 0,
        "manifest_xml_sha_mismatch_laws": [],
    }
    for r in reports:
        agg["xml_articles"] += r["xml_article_count"]
        agg["md_articles"] += r["md_article_count"]
        agg["articles_missing_md"] += len(r["articles_missing_md"])
        agg["articles_md_only"] += len(r["articles_md_only"])
        agg["marker_lines_total"] += r["marker_lines_total"]
        agg["files_with_markers"] += r["files_with_markers"]
        agg["appdx_total"] += r["appdx_count"]
        if r["manifest_xml_sha_match"] is False:
            agg["manifest_xml_sha_mismatch_laws"].append(r["law_abbrev"])
        for a in r["g0a"].values():
            if a["exact"]:
                agg["g0a_exact"] += 1
            else:
                agg["g0a_diff"] += 1
            for cat, n in a["missing"].items():
                agg["g0a_missing_by_category"][cat] = agg["g0a_missing_by_category"].get(cat, 0) + n
            agg["g0a_order_violations"] += a["order_violations"]
            agg["g0a_short_match_ambiguous"] += a.get("short_match_ambiguous", 0)
            if a.get("paragraph_count_mismatch"):
                agg["g0a_paragraph_count_mismatch"] += 1
            if a["excess_chars"]:
                agg["g0a_articles_with_excess"] += 1
            agg["g0a_table_format_diff"] += a["table_format_diff"]
        for b in r["g0b"].values():
            if b["exact"]:
                agg["g0b_exact"] += 1
            else:
                agg["g0b_diff"] += 1
            if b["all_chunks_missing"]:
                agg["g0b_all_chunks_missing"] += 1
            if b.get("parser_chunks_missing"):
                agg["g0b_parser_chunks_missing"] += 1
            if b["md_not_in_chunks_chars"]:
                agg["g0b_articles_md_not_in_chunks"] += 1
            agg["g0b_kou_chunks_not_in_md"] += b["kou_chunks_not_in_md"]
            agg["g0b_table_rows_not_in_table_chunks"] += b["table_rows_not_in_table_chunks"]
    return agg


def render_summary_md(agg: dict, skipped_no_xml: list[str]) -> str:
    """人が読めるサマリ (build/fidelity-report/summary.md)."""
    lines = [
        "# G0 忠実性ゲート diff レポート (Phase 0)",
        "",
        "判定 = 空白畳み込み後の完全一致。分類の探索は診断用 (合否に contains 不使用)。",
        "",
        f"- 対象法令: {agg['laws']} (XML 不在で skip: {len(skipped_no_xml)})",
        f"- XML 本則条文: {agg['xml_articles']} / md 条文: {agg['md_articles']}",
        "",
        "## G0-a: e-Gov XML <-> 正本 md (chunk と合算しない)",
        "",
        f"- 完全一致: {agg['g0a_exact']}",
        f"- 不一致: {agg['g0a_diff']}",
        f"- 条文丸ごと md 欠落: {agg['articles_missing_md']}",
        f"- md のみ存在 (XML に無い条): {agg['articles_md_only']}",
        "- 欠落 unit の分類:",
    ]
    for cat, n in sorted(agg["g0a_missing_by_category"].items(), key=lambda x: -x[1]):
        lines.append(f"  - {cat}: {n}")
    lines += [
        f"- 表の書式差 (全セルは md に存在): {agg['g0a_table_format_diff']}",
        f"- 順序の入れ替わり (骨格 unit >= {_SKELETON_MIN_LEN} 字のみ主張): "
        f"{agg['g0a_order_violations']}",
        f"- 短 unit の窓外一致 (偶然一致と区別不能 -> 欠落に分類): "
        f"{agg['g0a_short_match_ambiguous']}",
        f"- 項数不一致 (XML 項数 != md ブロック数) の条: {agg['g0a_paragraph_count_mismatch']}",
        f"- 過剰 (md 側にだけある文字列) を持つ条: {agg['g0a_articles_with_excess']}",
        f"- 別表等 (Appdx*、law-level・md 対象外): {agg['appdx_total']}",
        f"- manifest と cache XML の sha 不一致: {agg['manifest_xml_sha_mismatch_laws']}",
        "",
        "## G0-b: 正本 md <-> chunks",
        "",
        f"- 完全一致: {agg['g0b_exact']}",
        f"- 不一致: {agg['g0b_diff']}",
        f"- chunk 全欠落 (md に本文があるのに chunk 0 件): {agg['g0b_all_chunks_missing']}",
        f"- 本文系 chunk 欠落 (kou のみ等を含む): {agg['g0b_parser_chunks_missing']}",
        f"- md 本文の一部が chunk に無い条: {agg['g0b_articles_md_not_in_chunks']}",
        f"- 号 chunk が md に無い (F3: XML 別経路): {agg['g0b_kou_chunks_not_in_md']}",
        f"- md 表行が table chunk に無い: {agg['g0b_table_rows_not_in_table_chunks']}",
        "",
        "## マーカー混入 (F4)",
        "",
        f"- マーカー行合計: {agg['marker_lines_total']}",
        f"- マーカーを含む md ファイル: {agg['files_with_markers']}",
        "",
    ]
    if skipped_no_xml:
        lines += ["## XML 不在で skip した法令", ""]
        lines += [f"- {law}" for law in skipped_no_xml]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data/v0.2"))
    ap.add_argument("--xml-dir", type=Path, default=Path("cache/laws"))
    ap.add_argument("--chunks-dir", type=Path, default=Path("build/chunks"))
    ap.add_argument("--out-dir", type=Path, default=Path("build/fidelity-report"))
    ap.add_argument("--law-only", default=None)
    args = ap.parse_args()

    law_map = build_law_abbrev_to_id_phase(args.data_dir)
    if args.law_only:
        if args.law_only not in law_map:
            print(f"ERROR: law_abbrev not found: {args.law_only}", file=sys.stderr)
            return 1
        law_map = {args.law_only: law_map[args.law_only]}

    reports: list[dict] = []
    skipped_no_xml: list[str] = []
    for law_abbrev, (law_id, phase) in sorted(law_map.items()):
        xml_path = args.xml_dir / f"{law_id}.xml"
        if not xml_path.exists():
            skipped_no_xml.append(f"{law_abbrev} ({law_id})")
            continue
        md_dir = None
        for phase_dir in sorted(args.data_dir.iterdir()):
            # phase* 配下のみが正本 md。case-law/ 等の同名 law ディレクトリ
            # (例 data/v0.2/case-law/keihou) を誤って掴まない (実測バグの再発防止)。
            if not phase_dir.is_dir() or not phase_dir.name.startswith("phase"):
                continue
            cand = phase_dir / law_abbrev
            if cand.is_dir():
                md_dir = cand
                break
        if md_dir is None:
            skipped_no_xml.append(f"{law_abbrev} (md dir 不在)")
            continue
        print(f"  {law_abbrev} ...", file=sys.stderr)
        reports.append(process_law(law_abbrev, law_id, phase, md_dir, xml_path, args.chunks_dir))

    agg = aggregate(reports)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        args.out_dir / "g0-report.json",
        json.dumps(
            {"aggregate": agg, "skipped_no_xml": skipped_no_xml, "laws": reports},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = render_summary_md(agg, skipped_no_xml)
    safe_write_text(args.out_dir / "summary.md", summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

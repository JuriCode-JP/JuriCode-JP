#!/usr/bin/env python3
"""build-keihou-precedents.py -- 刑法36条 判例 store の直接投入 + article 付与.

Why: 刑法には裁決 store が無いため、hojin の「rulings.jsonl から機械導出」型は流用しない
(WU2 handoff 2026-07-10)。courts.go.jp detail2 実ページから probe し佐藤が relevance を
ロックした検証済み JSON (business/keihou36-attach-locked-2026-07-10.json) を読み、
(1) PrecedentStoreEntry 化して data/v0.2/case-law/keihou/precedents.jsonl に永続化、
(2) keihou-article-36.md の frontmatter cases: に PrecedentReference を追記する。
本文セクションは非改変 (frontmatter 追記のみ・ja_text_sha256 不変)。

入力 JSON は gitignored (business/) のため、CI での再現は committed 成果物への
構造ゲート (tests/test_keihou_precedents_store.py) で行い、--check-only は入力を
持つローカルでのみ byte べき等を検証する。

Usage:
    python tools/parse/build-keihou-precedents.py
    python tools/parse/build-keihou-precedents.py --check-only   # 差分があれば非0で終了
    python tools/parse/build-keihou-precedents.py --input <path>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent.parent
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import PrecedentStoreEntry, safe_write_jsonl, safe_write_text  # noqa: E402
from juricode_shared.ir import PrecedentReference  # noqa: E402

_DEFAULT_INPUT = _REPO_ROOT / "business" / "keihou36-attach-locked-2026-07-10.json"
_STORE_PATH = _REPO_ROOT / "data" / "v0.2" / "case-law" / "keihou" / "precedents.jsonl"
_ARTICLE_MD = _REPO_ROOT / "data" / "v0.2" / "phase1-police" / "keihou" / "keihou-article-36.md"

# 佐藤ロック済み fidelity gate (2026-07-10)。件数・分布が入力とずれたら fail-loud。
_EXPECTED_TOTAL = 28
_EXPECTED_RELEVANCE = {"high": 4, "medium": 24}
_TARGET_ARTICLE_ID = "keihou-art-36"

# article cases: に出力するフィールド順 (hojin bulk の _ARTICLE_FIELD_ORDER と同思想。
# precedent 固有の court/court_en/citation を decision_date の後に置く)。
_ARTICLE_FIELD_ORDER = [
    "case_id",
    "case_type",
    "source_license",
    "summary_source",
    "decision_date",
    "court",
    "court_en",
    "citation",
    "case_name_ja",
    "url",
    "relevance",
    "relevant_paragraph",
    "summary_ja",
    "tags",
]


def load_locked_candidates(input_path: Path) -> list[dict]:
    """佐藤ロック済み JSON を読み、投入前ゲートを通した candidates を返す.

    Why: 一次資料ゲート (probe 済・記憶由来0) と L3 ロック (relevance/overruled) の下流で
    ある本 builder は、入力の前提が崩れていたら黙って進まず fail-loud で止める。
    """
    data = json.loads(input_path.read_text(encoding="utf-8"))
    cands: list[dict] = data["candidates"]

    if len(cands) != _EXPECTED_TOTAL:
        raise ValueError(f"locked candidates: {len(cands)} 件 (expected {_EXPECTED_TOTAL})")
    dist: dict[str, int] = {}
    for c in cands:
        dist[c["relevance"]] = dist.get(c["relevance"], 0) + 1
    if dist != _EXPECTED_RELEVANCE:
        raise ValueError(f"relevance 分布 {dist} != locked {_EXPECTED_RELEVANCE}")

    ids = [c["case_id"] for c in cands]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id が重複しています")
    for c in cands:
        if c["case_type"] != "precedent":
            raise ValueError(f"{c['case_id']}: case_type={c['case_type']} (precedent 以外)")
        if c.get("overruled"):
            raise ValueError(f"{c['case_id']}: overruled=true は付与しない (D5 安全弁)")
        if c.get("attached_article_id") != _TARGET_ARTICLE_ID:
            raise ValueError(f"{c['case_id']}: 付与先 {c.get('attached_article_id')} は対象外")
    return cands


def build_store_rows(cands: list[dict]) -> list[dict]:
    """candidates -> PrecedentStoreEntry payload の list (case_id 昇順・決定論).

    Why: store は article 非依存の判例レコード。relevant_paragraph は条文固有ゆえ
    article 側 cases: のみに持たせ、store では null に落とす (hojin store と同思想)。
    summary_ja は D2 で defer (null)。overruled_by/modified_by は D5 予約のまま空。
    jiken_number は case_id slug に serial として織込済のため独立フィールドにしない
    (IR は extra=forbid)。
    """
    rows: list[dict] = []
    for c in sorted(cands, key=lambda x: x["case_id"]):
        entry = PrecedentStoreEntry(
            case_id=c["case_id"],
            case_type="precedent",
            court=c["court"],
            court_en=c["court_en"],
            citation=c["citation"],
            decision_date=c["decision_date"],
            url=c["url"],
            relevance=c["relevance"],
            source_license=c["source_license"],
            summary_source=c["summary_source"],
        )
        rows.append(entry.model_dump(mode="json"))
    return rows


def _article_paragraph_numbers(fm: dict) -> set[int]:
    """frontmatter の paragraphs から項番号集合を返す (relevant_paragraph ゲート用)。"""
    nums: set[int] = set()
    for p in fm.get("paragraphs") or []:
        n = p.get("number")
        if isinstance(n, int):
            nums.add(n)
    return nums


def _article_case_payload(c: dict, para_nums: set[int]) -> dict:
    """条 md cases: に入れる PrecedentReference payload (順序固定・store 専用 field なし).

    Why: relevant_paragraph は locked JSON に basis 付きで明示された場合のみ設定し、
    対象条の実項数以内であることを IR ゲート (cases_relevant_paragraph_exists) の
    手前で fail-loud に検証する (黙って null に落とさない: ロック済の値が条と矛盾
    したらデータ側の異常なので止める)。
    """
    rel_para = c.get("relevant_paragraph")
    if rel_para is not None and rel_para not in para_nums:
        raise ValueError(
            f"{c['case_id']}: relevant_paragraph={rel_para} が条の項 {sorted(para_nums)} に無い"
        )
    full = {
        "case_id": c["case_id"],
        "case_type": "precedent",
        "source_license": c["source_license"],
        "summary_source": c["summary_source"],
        "decision_date": c["decision_date"],
        "court": c["court"],
        "court_en": c["court_en"],
        "citation": c["citation"],
        "case_name_ja": None,
        "url": c["url"],
        "relevance": c["relevance"],
        "relevant_paragraph": rel_para,
        "summary_ja": None,
        "tags": [],
    }
    out: dict = {}
    for k in _ARTICLE_FIELD_ORDER:
        v = full.get(k)
        if k == "relevant_paragraph" and v is None:
            continue
        if k == "tags" and not v:
            continue
        out[k] = v
    PrecedentReference.model_validate(out)  # 全件 IR 検証 (fail-loud)
    return out


def _splice_new_cases(md_text: str, new_payloads: list[dict]) -> str:
    """frontmatter の cases: に new_payloads を追記する (既存バイトを保存・末尾挿入).

    Why (べき等・bulk-kfs-hojin.py の確立パターンを逐語流用): commit 済 cases: は
    上書き再生成せず、新規のみを cases ブロックの末尾へ splice する。
    """
    dumped = yaml.safe_dump(
        new_payloads, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False
    )
    indented = "\n".join(("  " + ln) if ln else ln for ln in dumped.rstrip("\n").split("\n"))

    lines = md_text.split("\n")
    idx = next(i for i, ln in enumerate(lines) if re.match(r"^cases:", ln))
    if lines[idx].strip() == "cases: []":
        lines[idx] = "cases:"
        insert_at = idx + 1
    else:
        insert_at = idx + 1
        while insert_at < len(lines) and (
            lines[insert_at].startswith((" ", "\t")) or lines[insert_at] == ""
        ):
            insert_at += 1
    lines[insert_at:insert_at] = indented.split("\n")
    return "\n".join(lines)


def append_cases_to_md(md: Path, cands: list[dict]) -> int:
    """条 md の cases: に candidates を idempotent append する。追加件数を返す (0=変更なし)。"""
    text = md.read_text(encoding="utf-8")
    fm_text = text.split("---\n", 2)[1]
    fm = yaml.safe_load(fm_text) or {}
    existing = {c["case_id"] for c in (fm.get("cases") or [])}
    para_nums = _article_paragraph_numbers(fm)

    new_payloads = [
        _article_case_payload(c, para_nums)
        for c in sorted(cands, key=lambda x: x["case_id"])
        if c["case_id"] not in existing
    ]
    if not new_payloads:
        return 0
    new_text = _splice_new_cases(text, new_payloads)
    if not new_text.endswith("\n"):
        new_text += "\n"
    # newline="\n" 明示: repo は .gitattributes eol=lf。Windows 既定の CRLF 書込を防ぐ。
    safe_write_text(md, new_text, newline="\n")
    return len(new_payloads)


def _store_content(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _check(rows: list[dict], cands: list[dict]) -> int:
    """--check-only: store byte 一致 + article md に全 case_id が付与済みかを検証する。"""
    if not _STORE_PATH.exists():
        print(f"NG: {_STORE_PATH} が存在しません")
        return 1
    if _STORE_PATH.read_text(encoding="utf-8") != _store_content(rows):
        print("NG: 生成結果が既存 precedents.jsonl と一致しません (再生成が必要)")
        return 1
    fm = yaml.safe_load(_ARTICLE_MD.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
    attached = {c["case_id"] for c in (fm.get("cases") or [])}
    missing = sorted({c["case_id"] for c in cands} - attached)
    if missing:
        print(f"NG: article md に未付与の case_id が {len(missing)} 件: {missing[:3]} ...")
        return 1
    print(f"OK: store {len(rows)} 判例 (byte 一致)・article 付与 {len(attached)} 件")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="生成結果が既存 store / article 付与と一致するか確認のみ (差分あれば非0)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=_DEFAULT_INPUT,
        help="佐藤ロック済み candidates JSON のパス (default: business/ 配下)",
    )
    args = parser.parse_args()

    cands = load_locked_candidates(args.input)
    rows = build_store_rows(cands)

    if args.check_only:
        return _check(rows, cands)

    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_write_jsonl(_STORE_PATH, rows)
    print(f"Wrote: {_STORE_PATH.relative_to(_REPO_ROOT)} ({len(rows)} 判例)")

    added = append_cases_to_md(_ARTICLE_MD, cands)
    print(f"Attached: {_ARTICLE_MD.relative_to(_REPO_ROOT)} (+{added} 件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

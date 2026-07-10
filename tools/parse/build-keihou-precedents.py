#!/usr/bin/env python3
"""build-keihou-precedents.py -- 刑法 判例 store の直接投入 + article 付与 (多条対応).

Why: 刑法には裁決 store が無いため、hojin の「rulings.jsonl から機械導出」型は流用しない
(WU2 handoff 2026-07-10)。courts.go.jp detail2 実ページから probe し佐藤が relevance を
ロックした committed source (data/v0.2/case-law/keihou/_sources/keihou{N}.json) を読み、
(1) 全 source を合流した PrecedentStoreEntry を data/v0.2/case-law/keihou/precedents.jsonl
    に全件再書込する (store = f(全 committed sources) の決定論。--article の部分実行でも
    store は常に全 source から再生成するため、他条のレコードを消さない)、
(2) 各条 md の frontmatter cases: に PrecedentReference を非破壊 splice で追記する。
本文セクションは非改変 (frontmatter 追記のみ・ja_text_sha256 不変)。

store は判例 1 件 = 1 レコード (case_id 一意・article 非依存・hojin store と同思想。
PrecedentStoreEntry は attached_article_id を持たない)。同一判例が複数条に付く場合は
各条 md の cases: に条ごとに並存させ、store 側は 1 レコードに合流する。source 間で
store 投影フィールド (relevance 等) が食い違えば fail-loud で止める (L3 裁定へ差し戻し)。

Usage:
    python tools/parse/build-keihou-precedents.py                 # 全条 (store + 全条 md 付与)
    python tools/parse/build-keihou-precedents.py --article 36    # store 全再生成 + md は36条のみ
    python tools/parse/build-keihou-precedents.py --check-only    # 差分があれば非0で終了
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent.parent
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import PrecedentStoreEntry, safe_write_jsonl, safe_write_text  # noqa: E402
from juricode_shared.ir import PrecedentReference  # noqa: E402

_SOURCES_DIR = _REPO_ROOT / "data" / "v0.2" / "case-law" / "keihou" / "_sources"
_STORE_PATH = _REPO_ROOT / "data" / "v0.2" / "case-law" / "keihou" / "precedents.jsonl"
_ARTICLE_DIR = _REPO_ROOT / "data" / "v0.2" / "phase1-police" / "keihou"

_ARTICLE_ID_RE = re.compile(r"^keihou-art-([0-9]+(?:-[0-9]+)*)$")

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


@dataclass(frozen=True)
class LockedSource:
    """committed source 1 ファイル分 (佐藤ロック済み・load_locked_source のゲート通過後)。"""

    path: Path
    article_id: str  # 例: keihou-art-36
    article_number: str  # 例: "36" (枝番は "36-2")
    candidates: tuple[dict, ...]


def _relevance_dist(cands: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for c in cands:
        dist[c["relevance"]] = dist.get(c["relevance"], 0) + 1
    return dist


def load_locked_source(path: Path) -> LockedSource:
    """committed source JSON を読み、投入前ゲートを通した LockedSource を返す.

    Why: 一次資料ゲート (probe 済・記憶由来0) と L3 ロック (relevance/overruled) の下流で
    ある本 builder は、入力の前提が崩れていたら黙って進まず fail-loud で止める。
    lock ヘッダ (total / relevance 分布) は佐藤ロック時の宣言値で、実 candidates との
    自己整合を強制する (件数のすり替え・分布の取り違え検出)。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    article_id = data["article_id"]
    m = _ARTICLE_ID_RE.match(article_id)
    if not m:
        raise ValueError(f"{path.name}: article_id={article_id!r} が keihou-art-N 形式でない")
    num = m.group(1)
    if path.name != f"keihou{num}.json":
        raise ValueError(f"{path.name}: ファイル名が keihou{num}.json でない (article_id と不一致)")

    cands: list[dict] = data["candidates"]
    lock = data["lock"]
    if lock["total"] != len(cands):
        raise ValueError(f"{path.name}: lock.total={lock['total']} != candidates {len(cands)} 件")
    dist = _relevance_dist(cands)
    if dist != lock["relevance"]:
        raise ValueError(f"{path.name}: relevance 分布 {dist} != locked {lock['relevance']}")
    ids = [c["case_id"] for c in cands]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: case_id が重複しています")
    for c in cands:
        if c["case_type"] != "precedent":
            raise ValueError(f"{c['case_id']}: case_type={c['case_type']} (precedent 以外)")
        if c.get("overruled"):
            raise ValueError(f"{c['case_id']}: overruled=true は付与しない (D5 安全弁)")
        if c.get("attached_article_id") != article_id:
            raise ValueError(
                f"{c['case_id']}: 付与先 {c.get('attached_article_id')} は {article_id} と不一致"
            )
    return LockedSource(
        path=path, article_id=article_id, article_number=num, candidates=tuple(cands)
    )


def discover_sources(sources_dir: Path) -> list[LockedSource]:
    """_sources/ 配下の全 committed source を決定論順 (ファイル名昇順) でロードする。"""
    paths = sorted(sources_dir.glob("keihou*.json"))
    if not paths:
        raise ValueError(f"committed source がありません: {sources_dir}")
    return [load_locked_source(p) for p in paths]


def _store_row(c: dict) -> dict:
    """candidate 1 件を PrecedentStoreEntry payload に投影する.

    Why: store は article 非依存の判例レコード。relevant_paragraph は条文固有ゆえ
    article 側 cases: のみに持たせ、store では null に落とす (hojin store と同思想)。
    summary_ja は D2 で defer (null)。overruled_by/modified_by は D5 予約のまま空。
    jiken_number は case_id slug に serial として織込済のため独立フィールドにしない
    (IR は extra=forbid)。
    """
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
    return entry.model_dump(mode="json")


def merge_store_rows(sources: list[LockedSource]) -> list[dict]:
    """全 source を合流した store rows を返す (case_id 昇順・判例 1 件 = 1 レコード).

    Why: 多条跨ぎの判例 (例: 43条 x 199条) は article 側 cases: に条ごとに並存させ、
    store は case_id で 1 レコードに合流する。source 間で store 投影フィールドが
    食い違う場合 (例: 条ごとに異なる relevance ロック) は黙って上書き・選択せず
    fail-loud で止める (relevance は L3 = 佐藤裁定)。
    """
    by_id: dict[str, tuple[str, dict]] = {}
    for src in sources:
        for c in src.candidates:
            row = _store_row(c)
            cid = c["case_id"]
            if cid in by_id:
                prev_article, prev_row = by_id[cid]
                if prev_row != row:
                    diff = sorted(k for k in row if row[k] != prev_row[k])
                    raise ValueError(
                        f"{cid}: store 投影フィールドが source 間で不一致 "
                        f"({prev_article} vs {src.article_id}, 差分: {diff})"
                    )
            else:
                by_id[cid] = (src.article_id, row)
    return [by_id[cid][1] for cid in sorted(by_id)]


def article_md_path(article_dir: Path, source: LockedSource) -> Path:
    """source の付与先 md パス (keihou-article-{N}.md) を返す。"""
    return article_dir / f"keihou-article-{source.article_number}.md"


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
    上書き再生成せず、新規のみを cases ブロックの末尾へ splice する。YAML 全体の
    parse -> 再 emit は quote/インデントが変わり byte 不変性を破るため行わない (R3)。
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


def _check(
    targets: list[LockedSource], rows: list[dict], store_path: Path, article_dir: Path
) -> int:
    """--check-only: store byte 一致 + 各対象条 md に source 全 case_id が付与済みかを検証.

    Why: no-arg では「全 committed source から生成した総レコード == committed store」を
    要求する (CI 不変条件・R5)。byte 比較は read_bytes で行い CRLF 混入も検出する。
    """
    if not store_path.exists():
        print(f"NG: {store_path} が存在しません")
        return 1
    if store_path.read_bytes() != _store_content(rows).encode("utf-8"):
        print("NG: 生成結果が既存 precedents.jsonl と一致しません (再生成が必要)")
        return 1
    fail = 0
    for src in targets:
        md = article_md_path(article_dir, src)
        fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
        attached = {c["case_id"] for c in (fm.get("cases") or [])}
        missing = sorted({c["case_id"] for c in src.candidates} - attached)
        if missing:
            print(f"NG: {md.name} に未付与の case_id が {len(missing)} 件: {missing[:3]} ...")
            fail = 1
    if not fail:
        print(f"OK: store {len(rows)} 判例 (byte 一致)・{len(targets)} 条の付与を確認")
    return fail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--article",
        default=None,
        help="md 付与をこの条番号に限定 (例: 36, 36-2)。store は常に全 source から再生成",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="生成結果が既存 store / article 付与と一致するか確認のみ (差分あれば非0)",
    )
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=_SOURCES_DIR,
        help="committed source ディレクトリ (default: data/v0.2/case-law/keihou/_sources)",
    )
    args = parser.parse_args()

    sources = discover_sources(args.sources_dir)
    if args.article is not None:
        targets = [s for s in sources if s.article_number == args.article]
        if not targets:
            known = [s.article_number for s in sources]
            print(f"NG: --article {args.article} の committed source が無い (登録済: {known})")
            return 1
    else:
        targets = sources

    rows = merge_store_rows(sources)

    if args.check_only:
        return _check(targets, rows, _STORE_PATH, _ARTICLE_DIR)

    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_write_jsonl(_STORE_PATH, rows)
    print(f"Wrote: {_STORE_PATH.relative_to(_REPO_ROOT)} ({len(rows)} 判例)")

    for src in targets:
        md = article_md_path(_ARTICLE_DIR, src)
        added = append_cases_to_md(md, list(src.candidates))
        print(f"Attached: {md.relative_to(_REPO_ROOT)} (+{added} 件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

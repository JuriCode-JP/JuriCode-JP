#!/usr/bin/env python3
"""bulk-kfs-shohi.py -- KFS 消費税 (MP/05) 全リーフの bulk fetch + dry-run 集計.

相続税 bulk (bulk-kfs-sozoku.py・PR#111) の逐語横展開。fetcher
(tools/fetch-kfs/kfs-fetcher.py) と parser (tools/parse/parse-kfs-saiketsu.py) を
driver 化し、消費税法関係 (MP/05) の全リーフを enumerate -> fetch (skip-if-exists) ->
parse して集計レポートを出す。差分は税目固有の定数のみ (LAW_CATEGORY / TAX_ITEM /
STORE_PATH / APPENDIX_DIR)。

Usage:
    # dry-run (既定): fetch + parse + 集計のみ。corpus は一切書かない。
    python tools/parse/bulk-kfs-shohi.py

    # network を使わず既存 cache だけで再集計 (offline)
    python tools/parse/bulk-kfs-shohi.py --offline

Why (briefing case-law-shohi-bulk-execution-briefing-2026-07-04・dry-run 先行):
    storage=B (全裁決を committed store に永続化) の前に、fetch+parse のシミュレーションで
    総数・attach 率・dup・法令分布・要旨 byte 一致率を機械算出し、佐藤承認を挟む。本 script は
    集計のみ (書込なし)。store 永続化と article 付与は承認後に別途行う。消費は既存 store 無し
    (新規) ゆえ hojin の pilot べき等ゲートは不要 (二重 append 懸念なし・dedup by case_id は維持)。

    parser/fetcher はハイフン名モジュールゆえ importlib で読み込む (test_kfs_saiketsu と同型)。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.error
from collections import Counter
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
_SHARED_SRC = REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

LAW_CATEGORY = "05"  # MP/05 = 消費税法関係
INDEX_LEAF = f"MP/{LAW_CATEGORY}/index.html"
CACHE_ROOT = REPO_ROOT / "cache" / "kfs"
APPENDIX_DIR = REPO_ROOT / "build" / "chunks" / "kfs-shohi"  # gitignored
TAX_ITEM = "消費税"

# index の leaf href (10 桁コード + .html)。相対リンクゆえコードだけ拾う。
_LEAF_CODE_RE = re.compile(r"(\d{10})\.html")
# 空白除去 (byte substring 照合用・YAML block scalar の空白畳みに耐える)。
_WS_RE = re.compile(r"\s")


def _load_hyphen_module(path: Path, mod_name: str) -> ModuleType:
    """ハイフン名の .py を importlib で読み込みモジュールとして返す (test と同型)。"""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def enumerate_leaf_codes(index_html: bytes) -> list[str]:
    """MP/05 index HTML から消費税リーフの 10 桁コードを昇順一意で返す。"""
    text = index_html.decode("cp932", errors="replace")
    hrefs = re.findall(r'href="([^"]+)"', text)
    codes: set[str] = set()
    for href in hrefs:
        m = _LEAF_CODE_RE.search(href)
        if m:
            codes.add(m.group(1))
    return sorted(codes)


def _norm_ws(s: str) -> str:
    return _WS_RE.sub("", s)


def _byte_substring_ok(summary_ja: str, leaf_text_norm: str) -> bool:
    """summary_ja が リーフ本文の byte substring か (空白正規化・要旨改変検知)。"""
    if not summary_ja:
        return True  # 空要旨は照合対象外 (metadata-only の一部)
    return _norm_ws(summary_ja) in leaf_text_norm


def run(*, offline: bool, sleep: float) -> int:
    fetcher = _load_hyphen_module(
        REPO_ROOT / "tools" / "fetch-kfs" / "kfs-fetcher.py", "kfs_fetcher"
    )
    parser_mod = _load_hyphen_module(
        REPO_ROOT / "tools" / "parse" / "parse-kfs-saiketsu.py", "parse_kfs_saiketsu"
    )

    # --- index 取得 (skip-if-exists) ---
    index_dest = CACHE_ROOT / LAW_CATEGORY / "index.html"
    if index_dest.exists():
        index_html = index_dest.read_bytes()
    elif offline:
        sys.exit(f"ERROR: --offline だが index cache が無い: {index_dest}")
    else:
        index_html = fetcher.http_get(f"{fetcher.HOST}{fetcher.SERVICE_BASE}/{INDEX_LEAF}")
        fetcher._save_bytes(index_dest, index_html, force=False)
        time.sleep(sleep)

    codes = enumerate_leaf_codes(index_html)
    print(f"index {INDEX_LEAF}: 消費税リーフ {len(codes)} 件を enumerate")

    # --- 各リーフを fetch (skip-if-exists) + parse ---
    all_entries: list[dict] = []
    per_leaf: list[tuple[str, int]] = []
    byte_pass = byte_total = 0
    fetched = skipped = 0

    for i, code in enumerate(codes, 1):
        leaf_path = f"MP/{LAW_CATEGORY}/{code}"
        leaf_dest = CACHE_ROOT / LAW_CATEGORY / f"{code}.html"
        if leaf_dest.exists():
            html = leaf_dest.read_bytes()
            skipped += 1
        elif offline:
            print(f"  [{i}/{len(codes)}] {code}: MISSING (offline・skip)")
            per_leaf.append((code, -1))
            continue
        else:
            html = fetcher.http_get(f"{fetcher.HOST}{fetcher.SERVICE_BASE}/{leaf_path}.html")
            fetcher._save_bytes(leaf_dest, html, force=False)
            fetched += 1
            time.sleep(sleep)

        entries = parser_mod.parse_leaf(html, code, TAX_ITEM, leaf_path)
        per_leaf.append((code, len(entries)))

        # byte substring 照合 (要旨改変検知・空白正規化)。タグを除いたレンダリング済テキストと
        # 突合する (raw HTML だと <br> 等のタグが要旨行間に挟まり false-fail するため・pilot 法)。
        enc = parser_mod._detect_charset(html)
        soup = parser_mod.BeautifulSoup(html.decode(enc, errors="replace"), "html.parser")
        leaf_text_norm = _norm_ws(soup.get_text("\n"))
        for e in entries:
            e["_leaf_code"] = code
            # 完全性: parser の独立監査 (補強②) が返す取りこぼし grounds。空 = 完全。
            if e.get("_summary_missing"):
                e["_summary_incomplete"] = True
            if e.get("summary_ja"):
                byte_total += 1
                if _byte_substring_ok(e["summary_ja"], leaf_text_norm):
                    byte_pass += 1
                else:
                    e["_byte_fail"] = True
        all_entries.extend(entries)
        if i % 20 == 0 or i == len(codes):
            print(f"  ...parsed {i}/{len(codes)} leaves")

    print(f"fetch: {fetched} 取得 / {skipped} skip(existing)")

    _report(all_entries, per_leaf, byte_pass, byte_total)
    _write_appendix(all_entries, per_leaf)

    incomplete = any(e.get("_summary_incomplete") for e in all_entries)
    null_cid = any(not e["case_id"] for e in all_entries)
    green = byte_pass == byte_total and not incomplete and not null_cid
    return all_entries, green


def _report(
    entries: list[dict],
    per_leaf: list[tuple[str, int]],
    byte_pass: int,
    byte_total: int,
) -> None:
    """dry-run 集計をコンソールに展開する (承認ゲート)。"""
    n = len(entries)
    leaves_with = sum(1 for _, c in per_leaf if c > 0)
    leaves_empty = sum(1 for _, c in per_leaf if c == 0)
    leaves_missing = sum(1 for _, c in per_leaf if c < 0)

    attach = sum(1 for e in entries if e["_has_sanshou"])
    metadata_only = n - attach

    case_ids = [e["case_id"] for e in entries if e["case_id"]]
    null_cid = [e for e in entries if not e["case_id"]]
    cid_counts = Counter(case_ids)
    dups = {cid: c for cid, c in cid_counts.items() if c > 1}

    link_edges = [lk for e in entries for lk in e["_links"]]
    by_law = Counter(lk["law_abbrev"] for lk in link_edges)
    distinct_articles = {lk["article_id"] for lk in link_edges}

    unlinked_reasons = Counter(u["reason"] for e in entries for u in e["_unlinked"])
    # unresolved_law の生表記を surface (cross-law 追加候補の材料・briefing §7)。
    unresolved_raw = Counter(
        u["raw"] for e in entries for u in e["_unlinked"] if u["reason"] == "unresolved_law"
    )
    tsutatsu_tags = sum(len(e["tags"]) for e in entries)
    byte_fail = [e for e in entries if e.get("_byte_fail")]

    print("\n" + "=" * 64)
    print("  KFS 消費税 (MP/05) bulk-ingest DRY-RUN 集計")
    print("=" * 64)
    print(
        f"リーフ: {len(per_leaf)} 件 (>=1 裁決 {leaves_with} / 0 裁決 {leaves_empty}"
        + (f" / 未取得 {leaves_missing}" if leaves_missing else "")
        + ")"
    )
    print(f"\n総裁決数: {n}")
    print(
        f"  《参照条文等》あり (article 付与候補): {attach}"
        + (f"  ({attach * 100 // n}%)" if n else "")
    )
    print(f"  metadata-only (参照条文なし):         {metadata_only}")

    print("\ncase_id:")
    print(f"  生成成功: {len(case_ids)} / null (生成不能): {len(null_cid)}")
    print(f"  ユニーク case_id: {len(cid_counts)}")
    print(
        f"  複数リーフ重複 (dup): {len(dups)} 種"
        + (f"  合計余剰 {sum(dups.values()) - len(dups)} 行" if dups else "")
    )
    if null_cid:
        print("  [null case_id のリーフ (先頭10)]:")
        for e in null_cid[:10]:
            print(
                f"    leaf {e['_leaf_code']}: date={e['decision_date']} name={e['case_name_ja'][:24]}"
            )
    if dups:
        print("  [dup case_id (先頭10)]:")
        for cid, c in list(dups.items())[:10]:
            print(f"    {cid} x{c}")

    print(f"\narticle link edges (denormalize 前・付与先 blast radius): {len(link_edges)}")
    print(f"  distinct article_id: {len(distinct_articles)}")
    for law, c in by_law.most_common():
        print(f"    {law}: {c} edges")

    print(f"\n通達参照 (tags 記録・link せず): {tsutatsu_tags}")
    print("unlinked 内訳:")
    for reason, c in unlinked_reasons.most_common():
        print(f"    {reason}: {c}")
    if unresolved_raw:
        print("  [unresolved_law の生表記 (cross-law 追加候補・先頭20)]:")
        for raw, c in unresolved_raw.most_common(20):
            print(f"    {raw}  x{c}")

    print(
        f"\n要旨 byte substring pass: {byte_pass}/{byte_total}"
        + ("  (100% OK)" if byte_pass == byte_total else f"  ★中間drop {len(byte_fail)}")
    )
    if byte_fail:
        for e in byte_fail[:10]:
            print(f"    中間drop leaf {e['_leaf_code']} {e['case_id']}")

    incomplete = [e for e in entries if e.get("_summary_incomplete")]
    print(
        f"\n要旨 完全性 (構造監査・補強②): <li>/<td>/<th> grounds を取りこぼす裁決 = {len(incomplete)}"
    )
    print("  ※ 抽出ロジックと独立に <li>/<td>/<th> 各片が summary_ja に内包されるか直接照合。")
    for e in incomplete[:15]:
        miss = " / ".join(e.get("_summary_missing", []))[:40]
        print(f"    要旨欠落 leaf {e['_leaf_code']} {e['case_id']}  欠落: {miss}")

    null_after = [e for e in entries if not e["case_id"]]
    print(f"\ncase_id 生成不可 (日付欠落等): {len(null_after)}")

    print("\n" + "=" * 64)
    clean = byte_pass == byte_total and not incomplete and not null_after
    print("  DRY-RUN 完了: corpus には一切書いていません。")
    print(
        "  完全性ゲート: "
        + (
            "全て green (要旨欠落0・case_id欠落0・byte100%)。"
            if clean
            else "未 green の項目あり (上記 ★ を参照)。"
        )
    )
    print("  この集計を承認してから store 書込 + article 付与に進みます。")
    print("=" * 64)


def _write_appendix(entries: list[dict], per_leaf: list[tuple[str, int]]) -> None:
    """全裁決の全 field + per-leaf 件数を gitignored 付録 JSON に保存 (レビュー用)。"""
    APPENDIX_DIR.mkdir(parents=True, exist_ok=True)
    out = APPENDIX_DIR / "dry-run-appendix.json"
    payload = {
        "per_leaf_counts": [{"code": c, "rulings": n} for c, n in per_leaf],
        "entries": entries,
    }
    with out.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n付録 JSON (全裁決・gitignored): {out.relative_to(REPO_ROOT)}")


STORE_PATH = REPO_ROOT / "data" / "v0.2" / "case-law" / "shohi" / "rulings.jsonl"
DATA_V02 = REPO_ROOT / "data" / "v0.2"

# article cases: に出力するフィールド順 (hojin commit 済 md と揃える)。
_ARTICLE_FIELD_ORDER = [
    "case_id",
    "case_type",
    "source_license",
    "summary_source",
    "decision_date",
    "case_name_ja",
    "url",
    "relevance",
    "relevant_paragraph",
    "summary_ja",
    "saiketsu_ref",
    "issue_code",
    "tax_item",
    "tags",
]


def build_store_rows(all_entries: list[dict]) -> list[dict]:
    """case_id で dedup し RulingStoreEntry payload の list (case_id 昇順) を返す.

    Why: 同一裁決が複数争点リーフに重複 (dup)。case_id を primary key に 1 行へ統合し、
    issue_codes に全争点を忠実保持 (継承 issue_code は初出=primary)。cited_refs=《参考判決・
    裁決》raw・attached_article_ids=corpus 実在リンク先。全行を RulingStoreEntry で検証する。
    """
    from juricode_shared import RulingStoreEntry

    groups: dict[str, list[dict]] = {}
    for e in all_entries:
        if e["case_id"]:
            groups.setdefault(e["case_id"], []).append(e)

    rows: list[dict] = []
    for cid in sorted(groups):
        group = groups[cid]
        base = group[0]
        issue_codes = sorted({g["issue_code"] for g in group if g.get("issue_code")})
        cited = _dedup_keep_order(r for g in group for r in g.get("_cited_refs", []))
        tags = _dedup_keep_order(t for g in group for t in g.get("tags", []))
        attached = sorted({lk["article_id"] for g in group for lk in g["_links"]})
        payload = {
            "case_id": cid,
            "case_type": "ruling",
            "decision_date": base["decision_date"],
            "url": base["url"],
            "relevance": "medium",
            "source_license": base["source_license"],
            "summary_source": base["summary_source"],
            "case_name_ja": base["case_name_ja"],
            "summary_ja": base["summary_ja"],
            "saiketsu_ref": base["saiketsu_ref"],
            "issue_code": base["issue_code"],
            "issue_codes": issue_codes,
            "tax_item": base["tax_item"],
            "tags": tags,
            "cited_refs": cited,
            "attached_article_ids": attached,
        }
        RulingStoreEntry.model_validate(payload)  # 全行 IR 検証 (fail-loud)
        rows.append(payload)
    return rows


def _dedup_keep_order(items) -> list[str]:
    out: list[str] = []
    for it in items:
        if it not in out:
            out.append(it)
    return out


def build_article_attachments(
    all_entries: list[dict],
) -> dict[str, dict[str, tuple[dict, int | None]]]:
    """article_id -> {case_id: (entry, relevant_paragraph)} を返す (条ごとに case_id dedup)."""
    per_article: dict[str, dict[str, tuple[dict, int | None]]] = {}
    for e in all_entries:
        if not e["case_id"]:
            continue
        for lk in e["_links"]:
            slot = per_article.setdefault(lk["article_id"], {})
            slot.setdefault(e["case_id"], (e, lk["relevant_paragraph"]))
    return per_article


def _find_article_md(article_id: str) -> Path | None:
    """article_id (<abbrev>-art-<N>) の md を data/v0.2 から探す (corpus 実在ガード後ゆえ存在前提)。"""
    abbrev, _, num = article_id.rpartition("-art-")
    fname = f"{abbrev}-article-{num}.md"
    matches = list(DATA_V02.glob(f"*/{abbrev}/{fname}"))
    return matches[0] if matches else None


def _article_paragraph_numbers(fm: dict) -> set[int]:
    """frontmatter の paragraphs から項番号集合を返す (relevant_paragraph ゲート用)。"""
    nums: set[int] = set()
    for p in fm.get("paragraphs") or []:
        n = p.get("number")
        if isinstance(n, int):
            nums.add(n)
    return nums


def _article_case_payload(entry: dict, rel_para: int | None, para_nums: set[int]) -> dict:
    """条 md cases: に入れる RulingReference payload (順序固定・store 専用 field は含めない)。

    relevant_paragraph は対象条の実項数以内のときのみ設定 (IR cases_relevant_paragraph_exists
    ゲート回避)。saiketsu_ref/tags/relevant_paragraph は値があるときだけ出力。
    """
    full = {
        "case_id": entry["case_id"],
        "case_type": "ruling",
        "source_license": entry["source_license"],
        "summary_source": entry["summary_source"],
        "decision_date": entry["decision_date"],
        "case_name_ja": entry["case_name_ja"],
        "url": entry["url"],
        "relevance": "medium",
        "relevant_paragraph": rel_para if (rel_para in para_nums) else None,
        "summary_ja": entry["summary_ja"],
        "saiketsu_ref": entry["saiketsu_ref"],
        "issue_code": entry["issue_code"],
        "tax_item": entry["tax_item"],
        "tags": list(entry.get("tags") or []),
    }
    out = {}
    for k in _ARTICLE_FIELD_ORDER:
        v = full.get(k)
        if k in ("relevant_paragraph", "saiketsu_ref") and v is None:
            continue
        if k == "tags" and not v:
            continue
        out[k] = v
    return out


def _splice_new_cases(md_text: str, new_payloads: list[dict]) -> str:
    """frontmatter の cases: に new_payloads を追記する (既存バイトを保存・末尾挿入).

    Why (べき等・佐藤修正①): commit 済 cases: は正しいので上書き再生成せず、新規のみを
    cases ブロックの末尾へ splice する。summary_ja の block scalar 中の空行も block 一部として
    正しく跨ぐ (インデント行/空行が続く限り block とみなす)。
    """
    import yaml

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


def _append_cases_to_md(md: Path, slot: dict[str, tuple[dict, int | None]]) -> int:
    """1 条 md の cases: に slot の裁決を idempotent append する。追加件数を返す (0=変更なし)。"""
    import yaml
    from juricode_shared import safe_write_text

    text = md.read_text(encoding="utf-8")
    fm_text = text.split("---\n", 2)[1]
    fm = yaml.safe_load(fm_text) or {}
    existing = {c["case_id"] for c in (fm.get("cases") or [])}
    para_nums = _article_paragraph_numbers(fm)

    new_payloads = [
        _article_case_payload(entry, rel_para, para_nums)
        for cid, (entry, rel_para) in sorted(slot.items())
        if cid not in existing
    ]
    if not new_payloads:
        return 0
    new_text = _splice_new_cases(text, new_payloads)
    if not new_text.endswith("\n"):
        new_text += "\n"
    safe_write_text(md, new_text)
    return len(new_payloads)


def do_write(all_entries: list[dict]) -> int:
    """store 書込 + article 付与 (承認後・gates green 前提)。"""
    from juricode_shared import safe_write_jsonl

    rows = build_store_rows(all_entries)
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_write_jsonl(STORE_PATH, rows)
    print(f"\n[write] store: {len(rows)} 行 -> {STORE_PATH.relative_to(REPO_ROOT)}")

    per_article = build_article_attachments(all_entries)
    total_added = 0
    touched = 0
    for aid in sorted(per_article):
        md = _find_article_md(aid)
        if md is None:
            sys.exit(f"ERROR: article md not found for {aid} (corpus 実在ガード矛盾)")
        added = _append_cases_to_md(md, per_article[aid])
        if added:
            touched += 1
            total_added += added
    print(f"[write] article 付与: {total_added} 裁決リンクを {touched} 条 md に append")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KFS 消費税 (MP/05) bulk dry-run / write.")
    ap.add_argument("--offline", action="store_true", help="network 不使用・既存 cache のみ。")
    ap.add_argument("--sleep", type=float, default=0.4, help="リクエスト間隔秒 (既定 0.4)。")
    ap.add_argument(
        "--write",
        action="store_true",
        help="dry-run gates が green のとき store 書込 + article 付与を実行 (承認後)。",
    )
    args = ap.parse_args(argv)
    all_entries, green = run(offline=args.offline, sleep=args.sleep)
    if not args.write:
        return 0
    if not green:
        sys.exit("ERROR: 完全性ゲート未 green のため書込中止 (上記 ★ を修正のこと)。")
    return do_write(all_entries)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP ERROR: {exc}")
    except urllib.error.URLError as exc:
        sys.exit(f"NETWORK ERROR: {exc}")

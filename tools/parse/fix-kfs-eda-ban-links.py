#!/usr/bin/env python3
"""fix-kfs-eda-ban-links.py -- FU-71 枝番脱落 偽リンク 30 件の一回限りの是正 (P0 hotfix).

Usage:
    python tools/parse/fix-kfs-eda-ban-links.py --check   # dry-run (差分を出すだけ・書込なし)
    python tools/parse/fix-kfs-eda-ban-links.py --write   # 是正を適用

Why:
    parse-kfs-saiketsu.py の `_ARTICLE_RE` が `第N条のM` の枝番を捨て、`第74条の9` を実在する
    別条 `art-74` に潰していた。潰れ先が corpus 実在ゆえ旧「偽リンク0」検査 (実在のみ確認) を
    素通りし、merge 済み 5 store に 30 件の偽リンクが commit された (report §1)。

    store (rulings.jsonl) は全上書き再生成で自己修復するが、条 md の `cases:` は bulk-kfs-*.py が
    **append 専用**ゆえ、parser を直して再 parse しても誤リンクが残り二重リンクに悪化する。
    そこで md 側は「除去 = ロック済リスト駆動の外科的削除」「追加 = 既存 append」で双方向に直す。

    **store 単位 reconcile を使わない理由**: case_id は 2 store に跨るものが 3 件あり (ntt-1988-12-21
    -j36-120 等)、「この store が持つべき集合との差分を消す」実装だと片方が他方の正当な付与を消す。
    除去は下記ロック済 29 ペアだけを対象とする (佐藤 GO-1 で目視ロック済)。

一回限り: 是正後は再実行しても no-op (べき等)。将来の再発は test_kfs_saiketsu.py の枝番回帰と
各 store test の「生引用の枝番一致」不変条件が捕捉する。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
_SHARED_SRC = REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

STORES = ("hojin", "kokutsu", "shohi", "shotoku", "sozoku")

# ---------------------------------------------------------------------------
# ロック済 expected (佐藤 GO-1・2026-07-08 / 31 件目でロック拡張・同日)。
# 正本 = business/fu71-枝番偽リンク-report-2026-07-08.md
# 除去 30 ペア = (store, case_id, 誤 article_id)。枝番 30 行のうち kokutsu/ntt-2015-05-26-j99-3 は
# 第74条の9 と 第74条の11 の 2 引用が同じ誤 id art-74 に潰れるため 1 ペアに統合され 29 ペア。
# これに map 成長由来の 31 件目 (shotoku/ntt-2014-12-04-j97-7) を加えて 30 ペア。
# ---------------------------------------------------------------------------
LOCKED_REMOVALS: tuple[tuple[str, str, str], ...] = (
    ("hojin", "ntt-2010-09-02-j80-8", "houjin-zei-hou-shikkourei-art-72"),
    ("hojin", "ntt-2011-05-30-j83-17", "houjin-zei-hou-shikkourei-art-136"),
    ("hojin", "ntt-2017-01-26-j106-4", "houjin-zei-hou-shikkourei-art-140"),
    ("hojin", "ntt-2018-12-14-j113-9", "houjin-zei-hou-art-23"),
    ("hojin", "ntt-2018-12-14-j113-9", "houjin-zei-hou-shikkourei-art-22"),
    ("hojin", "ntt-2023-12-21-j133-7", "houjin-zei-hou-art-22"),
    ("kokutsu", "ntt-2010-06-07-j79-6", "kokuzei-tsuusoku-hou-shikkourei-art-27"),
    ("kokutsu", "ntt-2011-08-02-j84-1", "chihou-zei-hou-art-9"),
    ("kokutsu", "ntt-2012-04-20-j87-3", "houjin-zei-hou-shikkourei-art-72"),
    ("kokutsu", "ntt-2013-09-18-j92-3", "kokuzei-tsuusoku-hou-shikkourei-art-27"),
    ("kokutsu", "ntt-2014-11-13-j97-6", "kokuzei-tsuusoku-hou-art-74"),
    ("kokutsu", "ntt-2015-05-26-j99-3", "kokuzei-tsuusoku-hou-art-74"),
    ("kokutsu", "ntt-2015-06-01-j99-2", "kokuzei-tsuusoku-hou-art-74"),
    ("kokutsu", "ntt-2023-05-18-j131-1", "kokuzei-tsuusoku-hou-art-74"),
    ("kokutsu", "ntt-2024-10-22-j137-1", "shotoku-zei-hou-shikoukisoku-art-47"),
    ("shohi", "ntt-2010-12-08-j81-14", "shouhi-zei-hou-shikkourei-art-14"),
    ("shohi", "ntt-2022-11-09-j129-7", "shouhi-zei-hou-shikoukisoku-art-15"),
    ("shohi", "ntt-2025-09-08-j140-7", "shouhi-zei-hou-shikkourei-art-11"),
    # 枝番ではない 31 件目 (佐藤裁定 2026-07-08 でロック拡張)。《参照条文等》は 国税通則法施行令
    # 第6条第2項 だが、shotoku store を commit した 8070017f の時点で 国税通則法施行令 が
    # FULLNAME_LAW_MAP に未登録で、_match_law_fullname が前方一致で 国税通則法 を拾い本則 art-6 に
    # 誤付与した。#69 が map に追加した後 shotoku store が refresh されず残存。store は全上書き
    # 再生成ゆえ回避不能 (温存には特別扱いコードが要る)。全 5 store 走査でロック外差分はこの 1 件のみ。
    ("shotoku", "ntt-2014-12-04-j97-7", "kokuzei-tsuusoku-hou-art-6"),
    ("shotoku", "ntt-2016-06-02-j103-7", "shotoku-zei-hou-art-57"),
    ("shotoku", "ntt-2019-05-28-j115-9", "shotoku-zei-hou-shikkourei-art-7"),
    ("shotoku", "ntt-2023-03-14-j130-6", "shotoku-zei-hou-shikoukisoku-art-47"),
    ("shotoku", "ntt-2024-07-03-j136-4", "shotoku-zei-hou-art-57"),
    ("sozoku", "ntt-2011-03-07-j82-13", "souzoku-zei-hou-art-1"),
    ("sozoku", "ntt-2011-06-10-j83-20", "souzoku-zei-hou-art-21"),
    ("sozoku", "ntt-2011-11-25-j85-13", "souzoku-zei-hou-art-19"),
    ("sozoku", "ntt-2012-04-24-j87-18", "souzoku-zei-hou-art-19"),
    ("sozoku", "ntt-2013-08-29-j92-16", "souzoku-zei-hou-art-11"),
    ("sozoku", "ntt-2020-08-11-j120-4", "souzoku-zei-hou-art-11"),
    ("sozoku", "ntt-2024-10-07-j137-5", "souzoku-zei-hou-art-21"),
)

# 追加 26 件 = (store, case_id, 正 article_id)。(ii) 5 件 (正 target が corpus 未収録) は追加なし。
LOCKED_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    ("hojin", "ntt-2017-01-26-j106-4", "houjin-zei-hou-shikkourei-art-140-2"),
    ("hojin", "ntt-2018-12-14-j113-9", "houjin-zei-hou-art-23-2"),
    ("hojin", "ntt-2018-12-14-j113-9", "houjin-zei-hou-shikkourei-art-22-4"),
    ("hojin", "ntt-2023-12-21-j133-7", "houjin-zei-hou-art-22-2"),
    ("kokutsu", "ntt-2010-06-07-j79-6", "kokuzei-tsuusoku-hou-shikkourei-art-27-2"),
    ("kokutsu", "ntt-2013-09-18-j92-3", "kokuzei-tsuusoku-hou-shikkourei-art-27-2"),
    ("kokutsu", "ntt-2014-11-13-j97-6", "kokuzei-tsuusoku-hou-art-74-9"),
    ("kokutsu", "ntt-2015-05-26-j99-3", "kokuzei-tsuusoku-hou-art-74-11"),
    ("kokutsu", "ntt-2015-05-26-j99-3", "kokuzei-tsuusoku-hou-art-74-9"),
    ("kokutsu", "ntt-2015-06-01-j99-2", "kokuzei-tsuusoku-hou-art-74-14"),
    ("kokutsu", "ntt-2023-05-18-j131-1", "kokuzei-tsuusoku-hou-art-74-9"),
    ("kokutsu", "ntt-2024-10-22-j137-1", "shotoku-zei-hou-shikoukisoku-art-47-2"),
    ("shohi", "ntt-2010-12-08-j81-14", "shouhi-zei-hou-shikkourei-art-14-2"),
    ("shohi", "ntt-2022-11-09-j129-7", "shouhi-zei-hou-shikoukisoku-art-15-3"),
    ("shotoku", "ntt-2014-12-04-j97-7", "kokuzei-tsuusoku-hou-shikkourei-art-6"),  # 31 件目 (上記)
    ("shotoku", "ntt-2016-06-02-j103-7", "shotoku-zei-hou-art-57-3"),
    ("shotoku", "ntt-2019-05-28-j115-9", "shotoku-zei-hou-shikkourei-art-7-2"),
    ("shotoku", "ntt-2023-03-14-j130-6", "shotoku-zei-hou-shikoukisoku-art-47-2"),
    ("shotoku", "ntt-2024-07-03-j136-4", "shotoku-zei-hou-art-57-3"),
    ("sozoku", "ntt-2011-03-07-j82-13", "souzoku-zei-hou-art-1-3"),
    ("sozoku", "ntt-2011-06-10-j83-20", "souzoku-zei-hou-art-21-3"),
    ("sozoku", "ntt-2011-11-25-j85-13", "souzoku-zei-hou-art-19-2"),
    ("sozoku", "ntt-2012-04-24-j87-18", "souzoku-zei-hou-art-19-2"),
    ("sozoku", "ntt-2013-08-29-j92-16", "souzoku-zei-hou-art-11-2"),
    ("sozoku", "ntt-2020-08-11-j120-4", "souzoku-zei-hou-art-11-2"),
    ("sozoku", "ntt-2024-10-07-j137-5", "souzoku-zei-hou-art-21-16"),
)


def _load_bulk(store: str) -> ModuleType:
    """bulk-kfs-<store>.py を importlib で読む (ハイフン名ゆえ import 文が使えない)。"""
    path = SCRIPT_DIR / f"bulk-kfs-{store}.py"
    spec = importlib.util.spec_from_file_location(f"bulk_kfs_{store}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _read_store(path: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for line in path.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            out[r["case_id"]] = set(r["attached_article_ids"])
    return out


def _expected(pairs: tuple[tuple[str, str, str], ...], store: str) -> set[tuple[str, str]]:
    return {(cid, aid) for st, cid, aid in pairs if st == store}


def run(*, write: bool) -> int:
    from juricode_shared import remove_cases_from_md_text, safe_write_jsonl, safe_write_text

    total_rm = total_add = 0
    for store in STORES:
        bulk = _load_bulk(store)
        before = _read_store(bulk.STORE_PATH)

        all_entries, green = bulk.run(offline=True, sleep=0.0)
        if not green:
            sys.exit(f"ERROR: {store}: 完全性ゲート未 green。是正中止。")
        rows = bulk.build_store_rows(all_entries)
        after = {r["case_id"]: set(r["attached_article_ids"]) for r in rows}

        # --- store 差分がロック済 expected と厳密一致するか (fail-loud) ---
        got_rm = {(c, a) for c in before for a in before[c] - after.get(c, set())}
        got_add = {(c, a) for c in after for a in after[c] - before.get(c, set())}
        exp_rm, exp_add = _expected(LOCKED_REMOVALS, store), _expected(LOCKED_ADDITIONS, store)
        if got_rm != exp_rm or got_add != exp_add:
            sys.exit(
                f"ERROR: {store}: store 差分がロック済 expected と不一致。\n"
                f"  除去 期待={sorted(exp_rm)}\n  除去 実際={sorted(got_rm)}\n"
                f"  追加 期待={sorted(exp_add)}\n  追加 実際={sorted(got_add)}"
            )
        print(f"[{store}] store 差分 OK (除去 {len(got_rm)} / 追加 {len(got_add)})")

        if not write:
            total_rm += len(got_rm)
            total_add += len(got_add)
            continue

        safe_write_jsonl(bulk.STORE_PATH, rows)

        # --- md 除去: ロック済リスト駆動のみ (reconcile 禁止) ---
        per_md: dict[str, set[str]] = {}
        for cid, aid in exp_rm:
            per_md.setdefault(aid, set()).add(cid)
        for aid, cids in sorted(per_md.items()):
            md = bulk._find_article_md(aid)
            if md is None:
                sys.exit(f"ERROR: {store}: 除去対象 md が無い ({aid})")
            new_text, removed = remove_cases_from_md_text(md.read_text(encoding="utf-8"), cids)
            if removed != len(cids):
                sys.exit(f"ERROR: {store}: {aid} 除去数 {removed} != 期待 {len(cids)}")
            safe_write_text(md, new_text)
            total_rm += removed
            print(f"[{store}] rm {removed} from {md.relative_to(REPO_ROOT).as_posix()}")

        # --- md 追加: 既存 append (case_id で idempotent) をロック済 (case,art) に限定 ---
        per_article = bulk.build_article_attachments(all_entries)
        for cid, aid in sorted(exp_add):
            md = bulk._find_article_md(aid)
            if md is None:
                sys.exit(f"ERROR: {store}: 追加対象 md が無い ({aid})")
            slot = {cid: per_article[aid][cid]}
            added = bulk._append_cases_to_md(md, slot)
            total_add += added
            print(f"[{store}] add {added} -> {md.relative_to(REPO_ROOT).as_posix()} ({cid})")

    verb = "適用" if write else "検出 (dry-run)"
    print(f"\n{verb}: 除去 {total_rm} / 追加 {total_add}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FU-71 枝番偽リンク 30 件の是正。")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="dry-run (書込なし)。")
    g.add_argument("--write", action="store_true", help="是正を適用。")
    args = ap.parse_args(argv)
    return run(write=args.write)


if __name__ == "__main__":
    sys.exit(main())

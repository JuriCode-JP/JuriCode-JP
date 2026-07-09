"""改正履歴 (amendments[]) を e-Gov 版間 diff から populate する (消費税法パイロット).

Why (改正履歴 Phase 1・条文単位帰属):
    条文 md frontmatter の `amendments[]` は 0 件のまま (層として未 populate)。本ツールは
    e-Gov 法令API v2 の改正版チェーンを取得し、施行済 (Previous/CurrentEnforced) 版を真の
    昇順に並べ、連続版を本則条 (MainProvision//Article) 単位で diff し、変化した条を
    その版 (施行日・改正法令番号) に帰属させて amendments エントリを機械生成する。
    IR (juricode_shared.Amendment・extra=forbid) の実フィールド
    (effective_date / law_num / law_name / description) にマップする
    (format-spec §4.5 の旧例 law_no/summary/diff_summary は IR と非整合ゆえ採らない)。

境界 (Tier B・忠実 populate):
    - 未施行版は除外 (corpus は現行版ゆえ未施行条は非実在)。
    - 本文実 diff が空の版 (omnibus 附則のみ) は付与しない。
    - version_date・本文セクション・他 frontmatter フィールドは非改変
      (amendments: ブロックを byte 保存で splice するのみ)。
    - amendments[] は「本則条の実質改正のみ」= 改正の完全一覧ではない (データ契約)。

決定論・べき等:
    同一入力 (同一 revision チェーン) から同一 amendments を生成する。二度書いても md は
    byte 不変 (既存 amendments: ブロックを検出し置換)。
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import json
import re
import sys
from datetime import date
from pathlib import Path

import defusedxml.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[2]
_SHARED_SRC = REPO_ROOT / "tools" / "shared" / "src"
_FETCH_SRC = REPO_ROOT / "tools" / "fetch-egov" / "src"
for _p in (_SHARED_SRC, _FETCH_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 消費税法 (パイロット対象)。
LAW_ID = "363AC0000000108"
LAW_ABBREV = "shouhi-zei-hou"
CORPUS_DIR = REPO_ROOT / "data" / "v0.2" / "phase1-tax" / "shouhi-zei-hou"
CACHE_ROOT = REPO_ROOT / "cache"
# 直近 5 年目安 (format-spec §4.5.1)。施行日 >= この日 の版に帰属する改正のみ populate。
WINDOW_FROM = date(2020, 4, 1)

_ENFORCED = ("PreviousEnforced", "CurrentEnforced")
# description 中の先頭 diff 断片の bounded 長さ (要点のみ・format-spec §4.5.1)。
_FRAG_CAP = 60


# ---- XML → 本則条テキスト ------------------------------------------------


def _normalize_num(num: str) -> str:
    """Article @Num を corpus の article_id 接尾辞に正規化 ("15_2" -> "15-2")."""
    return (num or "").strip().replace("_", "-")


def _canonical_text(el: ET.Element) -> str:
    """要素配下の全テキストを連結し空白を除去した canonical 文字列.

    Why: e-Gov XML はタグ間にインデント空白を挟む。日本語法令本文はトークン境界に
    空白を用いないので、全空白除去で版間 diff を XML 整形差に頑健化する (変化検知は
    実質的な文字列差のみを拾う)。
    """
    return re.sub(r"\s+", "", "".join(el.itertext()))


def article_text_map(xml: str) -> dict[str, str]:
    """法令全文 XML から {正規化条番号: canonical テキスト} を作る (本則条のみ).

    Why: 附則 (SupplProvision) 条は改正帰属対象外 (本則スコープ)。
    MainProvision 配下の Article だけを見る。
    """
    root = ET.fromstring(xml)
    out: dict[str, str] = {}
    for mp in root.iter("MainProvision"):
        for art in mp.iter("Article"):
            num = _normalize_num(art.get("Num") or "")
            if num:
                out[num] = _canonical_text(art)
    return out


# ---- 改正版チェーン ------------------------------------------------------


def build_enforced_chain(revisions: list[dict]) -> list[dict]:
    """API の改正版一覧から施行済チェーンを真の昇順で構築し不変条件を assert する.

    Why (fail-loud): API は施行日降順・同日は公布日降順で返すので
    reversed が真の昇順チェーン。同一施行日に複数改正が乗る日は公布日だけでは
    supersession 順を決められない (2026-04-01 の複数版で公布日が同一) ため、API の
    native 順を信頼し、CurrentEnforced が「ちょうど1件かつチェーン最終リンク」で
    施行日が単調非減少であることを assert する。崩れたら黙って誤帰属せず raise。
    """
    chain = [r for r in reversed(revisions) if r.get("current_revision_status") in _ENFORCED]
    if not chain:
        raise ValueError("enforced revision chain is empty")

    n_current = sum(1 for r in chain if r.get("current_revision_status") == "CurrentEnforced")
    if n_current != 1:
        raise ValueError(f"expected exactly 1 CurrentEnforced, found {n_current}")
    if chain[-1].get("current_revision_status") != "CurrentEnforced":
        raise ValueError("CurrentEnforced is not the final enforced chain link (order broken)")

    dates = [r.get("amendment_enforcement_date") or "" for r in chain]
    for a, b in itertools.pairwise(dates):
        if a > b:
            raise ValueError(f"enforcement dates not monotonic non-decreasing: {a} > {b}")
    return chain


# ---- diff → description --------------------------------------------------


def _cap(s: str) -> str:
    return s if len(s) <= _FRAG_CAP else s[:_FRAG_CAP] + "…"


def build_description(old: str | None, new: str | None) -> str:
    """版間 diff から条スコープの description を機械生成する (改正ラベル + 先頭 diff 断片).

    Why: format-spec §4.5.1「要点のみ記載」。新設は「本条を新設。」、削除は「本条を削除。」、
    変更は「本条を改正（<先頭の変化断片>[ほか]）」= 先頭 diff 断片 (旧→新) を生 (raw) で示し、
    追加断片があれば「ほか」を付す。prose 要約 (作文) は入れない = L3 人間残余を回避し忠実性を
    保つ。同一入力 -> 同一出力 (決定論)。
    """
    if old is None:
        return "本条を新設。"
    if new is None:
        return "本条を削除。"

    frags: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            frags.append(f"「{_cap(old[i1:i2])}」→「{_cap(new[j1:j2])}」")
        elif tag == "delete":
            frags.append(f"「{_cap(old[i1:i2])}」→（削除）")
        elif tag == "insert":
            frags.append(f"（追加）→「{_cap(new[j1:j2])}」")
    if not frags:
        return "本条を改正（字句修正）"
    tail = "ほか" if len(frags) > 1 else ""
    return f"本条を改正（{frags[0]}{tail}）"


# ---- 帰属 ----------------------------------------------------------------


def attribute_amendments(
    chain: list[dict],
    texts: dict[str, dict[str, str]],
    corpus_nums: set[str],
) -> tuple[dict[str, list[dict]], list[dict]]:
    """window 版を predecessor と diff し、変化した本則条に amendments を帰属する.

    Args:
        chain: 施行済チェーン (昇順)。
        texts: {law_revision_id: {条番号: canonical テキスト}} (window 版 + predecessor)。
        corpus_nums: corpus に実在する条番号集合 (現行版 85 条)。

    Returns:
        (per_article, skipped):
          per_article = {条番号: [amendment エントリ...]} 施行日昇順。
          skipped = corpus 非実在の変化条 (ログ用・populate 不能)。
    """
    per_article: dict[str, list[dict]] = {}
    skipped: list[dict] = []

    win_start = next(
        (
            i
            for i, r in enumerate(chain)
            if (r.get("amendment_enforcement_date") or "") >= WINDOW_FROM.isoformat()
        ),
        None,
    )
    if win_start is None:
        return per_article, skipped
    if win_start == 0:
        raise ValueError("earliest window version has no predecessor in full enforced chain")

    for i in range(win_start, len(chain)):
        prev_rid = chain[i - 1]["law_revision_id"]
        cur_rid = chain[i]["law_revision_id"]
        prev_map = texts[prev_rid]
        cur_map = texts[cur_rid]
        rev = chain[i]

        for num in sorted(cur_map.keys() | prev_map.keys(), key=_num_sort_key):
            old = prev_map.get(num)
            new = cur_map.get(num)
            if old == new:
                continue  # 変化なし
            if num not in corpus_nums:
                # 現行 corpus に無い条 (歴史的に削除/附則側) は populate 不能。
                skipped.append(
                    {
                        "num": num,
                        "revision": cur_rid,
                        "kind": "removed" if new is None else "changed",
                    }
                )
                continue
            entry = {
                "effective_date": rev.get("amendment_enforcement_date"),
                "law_num": rev.get("amendment_law_num"),
                "law_name": rev.get("amendment_law_title") or None,
                "description": build_description(old, new),
            }
            per_article.setdefault(num, []).append(entry)

    # 各条内は施行日昇順 (既に i 昇順ゆえ安定だが明示ソート)。
    for num in per_article:
        per_article[num].sort(key=lambda e: e["effective_date"] or "")
    return per_article, skipped


def _num_sort_key(num: str) -> tuple[int, int]:
    head, _, branch = num.partition("-")
    return (int(head) if head.isdigit() else 10**9, int(branch) if branch.isdigit() else 0)


# ---- md への byte 保存 splice --------------------------------------------


def _amendments_yaml(entries: list[dict]) -> str:
    """amendments エントリ列を frontmatter 用 YAML ブロックに整形する.

    Why: yaml.safe_dump で正しくエスケープ (description の 「」→ 等) しつつ、他フィールドの
    バイトは触らずこのブロックだけを splice する。フィールド順を固定し決定論を保つ。
    """
    import yaml

    ordered = [
        {
            k: e[k]
            for k in ("effective_date", "law_num", "law_name", "description")
            if e.get(k) is not None
        }
        for e in entries
    ]
    dumped = yaml.safe_dump(
        {"amendments": ordered},
        allow_unicode=True,
        sort_keys=False,
        width=10**6,
        default_flow_style=False,
    )
    return dumped.rstrip("\n")


def splice_amendments(md_text: str, entries: list[dict]) -> str:
    """frontmatter に amendments: ブロックを挿入/置換する (他バイト非改変・べき等).

    Why: 既存 amendments: があれば (再実行時) その top-level ブロックを置換、無ければ
    frontmatter 終端 '---' の直前に挿入する。cases_splice と同じく yaml 全体を再ダンプ
    せず行スライスで扱い、対象外バイトを保存する。
    """
    lines = md_text.split("\n")

    # frontmatter 終端 (2 つ目の '---')。
    fm_end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if fm_end is None:
        raise ValueError("frontmatter closing '---' not found")

    block_lines = _amendments_yaml(entries).split("\n")

    key_idx = next((i for i in range(fm_end) if re.match(r"^amendments:", lines[i])), None)
    if key_idx is not None:
        # 既存ブロック (key から次の top-level key か fm_end まで) を置換 (べき等)。
        end = key_idx + 1
        while end < fm_end and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*:", lines[end]):
            end += 1
        lines[key_idx:end] = block_lines
    else:
        lines[fm_end:fm_end] = block_lines

    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    return new_text


def _find_article_md(num: str) -> Path:
    return CORPUS_DIR / f"{LAW_ABBREV}-article-{num}.md"


def write_article_amendments(per_article: dict[str, list[dict]]) -> int:
    """per_article を各条 md に byte 保存で書き込む。変更した条数を返す (べき等)."""
    from juricode_shared import safe_write_text

    touched = 0
    for num in sorted(per_article, key=_num_sort_key):
        md = _find_article_md(num)
        if not md.exists():
            sys.exit(f"ERROR: article md not found for {num} (corpus 実在ガード矛盾): {md}")
        text = md.read_text(encoding="utf-8")
        new_text = splice_amendments(text, per_article[num])
        if new_text != text:
            safe_write_text(md, new_text)
            touched += 1
    return touched


# ---- driver --------------------------------------------------------------


def _revisions_cache_path() -> Path:
    return CACHE_ROOT / "revisions" / f"_revisions_{LAW_ID}.json"


def _load_revisions(*, offline: bool, sleep: float) -> list[dict]:
    if offline:
        p = _revisions_cache_path()
        if not p.exists():
            sys.exit(f"ERROR: offline かつ revisions cache 不在: {p} (先に online 実行が必要)")
        return json.loads(p.read_text(encoding="utf-8"))
    from fetch_egov.cache import FileCache
    from fetch_egov.client import EGovClient

    cache = FileCache(CACHE_ROOT)
    with EGovClient(cache=cache, rate_limit_seconds=sleep) as c:
        revs = c.get_revisions(LAW_ID)
    p = _revisions_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(revs, ensure_ascii=False, indent=2), encoding="utf-8")
    return revs


def _load_texts(
    chain: list[dict], win_start: int, *, offline: bool, sleep: float
) -> dict[str, dict[str, str]]:
    """window 版 + predecessor の {revision_id: 条テキスト map} を取得 (cache 経由)."""
    from fetch_egov.cache import FileCache

    cache = FileCache(CACHE_ROOT)
    need = [chain[i]["law_revision_id"] for i in range(win_start - 1, len(chain))]
    texts: dict[str, dict[str, str]] = {}
    client = None
    if not offline:
        from fetch_egov.client import EGovClient

        client = EGovClient(cache=cache, rate_limit_seconds=sleep)
    try:
        for rid in need:
            if cache.has_revision(rid):
                xml = cache.load_revision(rid)
            elif offline:
                sys.exit(f"ERROR: offline かつ revision cache 不在: {rid}")
            else:
                xml = client.get_law_by_revision(rid)
            texts[rid] = article_text_map(xml)
    finally:
        if client is not None:
            client.close()
    return texts


def run(*, offline: bool = False, sleep: float = 1.0, write: bool = False) -> dict:
    """改正履歴 populate の本体。dry-run (write=False) で実測サマリを返す."""
    revisions = _load_revisions(offline=offline, sleep=sleep)
    chain = build_enforced_chain(revisions)

    win_start = next(
        (
            i
            for i, r in enumerate(chain)
            if (r.get("amendment_enforcement_date") or "") >= WINDOW_FROM.isoformat()
        ),
        None,
    )
    if win_start is None:
        sys.exit("ERROR: window 内の施行済版が無い")
    if win_start == 0:
        sys.exit("ERROR: 最古 window 版の predecessor がチェーンに無い (下限を早める必要)")

    texts = _load_texts(chain, win_start, offline=offline, sleep=sleep)

    corpus_nums = {
        p.stem[len(f"{LAW_ABBREV}-article-") :]
        for p in CORPUS_DIR.glob(f"{LAW_ABBREV}-article-*.md")
    }
    per_article, skipped = attribute_amendments(chain, texts, corpus_nums)

    n_entries = sum(len(v) for v in per_article.values())
    versions_with_diff = {
        e_rid
        for num in per_article
        for e_rid in [(x["effective_date"], x["law_num"]) for x in per_article[num]]
    }

    summary = {
        "chain_len": len(chain),
        "window_versions": len(chain) - win_start,
        "current_enforced": chain[-1]["law_revision_id"],
        "n_entries": n_entries,
        "n_articles": len(per_article),
        "n_versions_with_diff": len(versions_with_diff),
        "corpus_articles": len(corpus_nums),
        "skipped_noncorpus": skipped,
        "per_article": per_article,
    }

    if write:
        touched = write_article_amendments(per_article)
        summary["touched"] = touched
    return summary


def _print_summary(s: dict, *, samples: int = 5) -> None:
    print("=== 改正履歴 populate (消費税法) ===")
    print(f"enforced chain     : {s['chain_len']} 版")
    print(f"window 版 (>=2020-04-01): {s['window_versions']}")
    print(f"CurrentEnforced    : {s['current_enforced']}")
    print(f"実 diff のあった版  : {s['n_versions_with_diff']}")
    print(f"amendments エントリ : {s['n_entries']}")
    print(f"付与条数            : {s['n_articles']} / corpus {s['corpus_articles']} 条")
    if s["skipped_noncorpus"]:
        nums = sorted({x["num"] for x in s["skipped_noncorpus"]}, key=_num_sort_key)
        print(f"corpus 非実在で除外 : {len(s['skipped_noncorpus'])} 変化 (条 {nums})")
    if "touched" in s:
        print(f"[write] 更新した条 md: {s['touched']}")
    print("\n--- サンプル ---")
    shown = 0
    for num in sorted(s["per_article"], key=_num_sort_key):
        for e in s["per_article"][num]:
            print(f"[art-{num}] {e['effective_date']} {e['law_num']}")
            print(f"    law_name   : {e.get('law_name')}")
            print(f"    description: {e['description']}")
            shown += 1
            if shown >= samples:
                return


def main() -> None:
    ap = argparse.ArgumentParser(
        description="消費税法の改正履歴 (amendments[]) を e-Gov 版間 diff から populate する."
    )
    ap.add_argument(
        "--write", action="store_true", help="条 md に amendments を書き込む (既定は dry-run)."
    )
    ap.add_argument("--offline", action="store_true", help="cache のみ使用 (ネットワーク非依存).")
    ap.add_argument("--sleep", type=float, default=1.0, help="API rate limit 秒 (既定 1.0).")
    ap.add_argument("--samples", type=int, default=5, help="表示するサンプル件数.")
    args = ap.parse_args()

    s = run(offline=args.offline, sleep=args.sleep, write=args.write)
    _print_summary(s, samples=args.samples)


if __name__ == "__main__":
    main()

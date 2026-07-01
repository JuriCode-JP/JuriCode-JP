#!/usr/bin/env python3
"""taxanswer-fetcher.py -- NTA タックスアンサー HTML をコード順総索引から取得する.

使い方:
    cd JuriCode-JP
    python tools/fetch-egov/taxanswer-fetcher.py --category hojin   # 法人税カテゴリ全コード
    python tools/fetch-egov/taxanswer-fetcher.py --category hojin --force  # 既存 cache を上書き

取得対象 (2026-07-01 実測):
    hojin : 法人税タックスアンサー  /taxes/shiraberu/taxanswer/hojin/<code>.htm
            -> cache/taxanswer/hojin/<code>.htm

Why (設計):
    - タックスアンサーは通達のような階層目次を持たず、コード順総索引
      ('.../taxanswer/code/index.htm') が全カテゴリの leaf への root-relative href
      を列挙する (2026-07-01 時点で 1,082 href)。カテゴリ別 'bunya-<cat>.htm' は
      「分野」ページで、そのカテゴリ path ('/taxanswer/hojin/') への直リンクを
      持たない (法人税分野ページは源泉/印紙等の他 path コードを列挙する) ため
      母集団ソースには使えない。よって総索引を単一ソースとし、href に
      '/taxanswer/<category>/' を含むものだけを抽出する。cross-category な
      path (例: '/hojin/3429.htm') もこの基準で自然に拾える。
    - 生バイト保存: urlopen(...).read() を write_bytes で verbatim 保存し、
      charset 判定は parser 側 _detect_charset に委ねる (cp932/shift_jis を
      requests.text で ISO-8859-1 誤認させない)。errors='replace' 等の非可逆
      変換は禁止。
    - skip-if-exists 既定: 既存 cache を保全し byte 不変を担保する (--force のみ
      上書き)。既存 PoC 8 htm を壊さないための前提。
    - リダイレクト dedup: urllib は既定でリダイレクトを追従する。最終 URL の
      code で重複排除し、旧->新コードの二重取得を防ぐ。
    - soft-404 除外: NTA は削除ページを HTTP 200 のエラー本文で返すことがある。
      本文マーカーを検出したら fail-loud でなく記録して除外する (削除済み
      コードで全体を止めない)。
    - stdlib urllib + User-Agent + sleep で実装 (requests/bs4 依存を増やさない)。

完全性:
    discover した code 数と保存/skip/除外の内訳を実測ログする (silent drop ゼロ)。
    baseline は Phase 3 で人間がロックするため、初回取得ではハードゲートを置かず
    実測値を記録するに留める。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

HOST = "https://www.nta.go.jp"
USER_AGENT = "JuriCode-JP/0.2 (+https://github.com/JuriCode-JP) taxanswer-fetcher"
# コード順総索引 (全カテゴリの leaf href を列挙する単一ソース)。
CODE_INDEX_PATH = "/taxes/shiraberu/taxanswer/code/index.htm"
# NTA の soft-404 ページ (HTTP 200 で返るエラー本文) の目印。
_SOFT_404_MARK = "指定されたページを表示できませんでした".encode("cp932")
_HREF_RE = re.compile(rb'href="([^"]+)"')


@dataclass(frozen=True)
class Category:
    """1 カテゴリ分の取得設定 (Why: カテゴリごとに path 断片と cache 先が変わる)."""

    key: str
    label: str
    path_segment: str  # taxanswer 配下の path 断片 (例: 'hojin')
    cache_dir: Path


CATEGORIES: dict[str, Category] = {
    "hojin": Category(
        key="hojin",
        label="法人税タックスアンサー",
        path_segment="hojin",
        cache_dir=REPO_ROOT / "cache" / "taxanswer" / "hojin",
    ),
    # 2026-07-01 FU-527: 相続・贈与タックスアンサー (相続税 4100 番台 + 贈与税 4400 番台は
    # 同一 path '/taxanswer/sozoku/' に同居する)。hojin と逐語同型 (discover/枝番ソート/
    # リダイレクト正規化/skip-if-exists は共通実装)。
    "sozoku": Category(
        key="sozoku",
        label="相続・贈与タックスアンサー",
        path_segment="sozoku",
        cache_dir=REPO_ROOT / "cache" / "taxanswer" / "sozoku",
    ),
}


def http_get(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """URL を GET して (応答 bytes, 最終 URL) を返す (fail-loud: HTTP エラーは送出).

    Why: urllib はリダイレクトを既定追従するので geturl() で最終 URL を得て
    dedup に使う。
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定 https host)
        return resp.read(), resp.geturl()


def discover_codes(category: Category) -> list[str]:
    """総索引から当カテゴリの leaf code を昇順で返す (実在 href のみ, dedup 済).

    Why: href に '/taxanswer/<segment>/<code>.htm' を含むものだけ抽出。枝番
    ('5364-2' 等) も 1 段だけ許容する。索引内の重複リンクは code で dedup。
    """
    html, _ = http_get(HOST + CODE_INDEX_PATH)
    leaf_re = re.compile(
        rf"/taxes/shiraberu/taxanswer/{re.escape(category.path_segment)}/"
        r"(\d{4,5}(?:-\d+)?)\.htm".encode()
    )
    codes: set[str] = set()
    for m in _HREF_RE.finditer(html):
        href = m.group(1)
        lm = leaf_re.search(href)
        if lm:
            codes.add(lm.group(1).decode("ascii"))
    return sorted(codes, key=_code_sort_key)


def _code_sort_key(code: str) -> tuple[int, int]:
    """'5364-2' -> (5364, 2), '5200' -> (5200, 0)。数値順に並べる。"""
    if "-" in code:
        base, branch = code.split("-", 1)
        return (int(base), int(branch))
    return (int(code), 0)


def leaf_url(category: Category, code: str) -> str:
    return f"{HOST}/taxes/shiraberu/taxanswer/{category.path_segment}/{code}.htm"


def _code_from_final_url(final_url: str, category: Category) -> str | None:
    """最終 URL から当カテゴリの code を取り出す (リダイレクト先の正規化用)。"""
    m = re.search(
        rf"/taxanswer/{re.escape(category.path_segment)}/(\d{{4,5}}(?:-\d+)?)\.htm",
        final_url,
    )
    return m.group(1) if m else None


def fetch_category(category: Category, sleep: float, *, force: bool) -> dict[str, int]:
    """1 カテゴリを取得して cache に保存。内訳カウントを返す (fail-loud on HTTP)."""
    print("=" * 60)
    print(f"{category.label} ({category.key})  index={CODE_INDEX_PATH}")
    print("=" * 60)
    codes = discover_codes(category)
    print(f"  discovered codes: {len(codes)} (branched: {[c for c in codes if '-' in c]})")

    saved = skipped = soft404 = redirected = 0
    seen_final: set[str] = set()
    for i, code in enumerate(codes, 1):
        url = leaf_url(category, code)
        html, final = http_get(url)
        if _SOFT_404_MARK in html:
            soft404 += 1
            print(f"  SKIP soft-404: {code}")
            time.sleep(sleep)
            continue
        final_code = _code_from_final_url(final, category)
        if final_code is None:
            # 別カテゴリ等へリダイレクト -> 当カテゴリ外なので除外して記録。
            redirected += 1
            print(f"  SKIP redirect out-of-category: {code} -> {final}")
            time.sleep(sleep)
            continue
        if final_code != code:
            redirected += 1
            print(f"  redirect {code} -> {final_code}")
        if final_code in seen_final:
            skipped += 1
            time.sleep(sleep)
            continue
        seen_final.add(final_code)
        dest = category.cache_dir / f"{final_code}.htm"
        if dest.exists() and not force:
            skipped += 1
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(html)
            os.replace(tmp, dest)
            saved += 1
        if i % 20 == 0:
            print(f"  {i}/{len(codes)} processed (saved={saved}, skipped={skipped})")
        time.sleep(sleep)

    total_leaves = len(seen_final)
    print(
        f"  DONE: discovered={len(codes)} leaves={total_leaves} "
        f"saved={saved} skipped(existing/dup)={skipped} "
        f"soft404={soft404} redirected={redirected}"
    )
    print(f"  cache: {category.cache_dir}")
    return {
        "discovered": len(codes),
        "leaves": total_leaves,
        "saved": saved,
        "skipped": skipped,
        "soft404": soft404,
        "redirected": redirected,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch NTA タックスアンサー HTML into cache.")
    parser.add_argument(
        "--category",
        choices=[*sorted(CATEGORIES), "all"],
        default="all",
        help="取得対象カテゴリ (既定: all)。",
    )
    parser.add_argument("--sleep", type=float, default=0.5, help="リクエスト間隔秒 (既定 0.5)。")
    parser.add_argument("--force", action="store_true", help="既存 cache を上書き。")
    args = parser.parse_args(argv)

    targets = sorted(CATEGORIES) if args.category == "all" else [args.category]
    for key in targets:
        fetch_category(CATEGORIES[key], args.sleep, force=args.force)
    print("=" * 60)
    print(f"ALL DONE across {len(targets)} category(ies).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:  # fail-loud
        sys.exit(f"HTTP ERROR: {exc}")
    except urllib.error.URLError as exc:
        sys.exit(f"NETWORK ERROR: {exc}")

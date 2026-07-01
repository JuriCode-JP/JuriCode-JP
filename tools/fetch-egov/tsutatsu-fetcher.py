#!/usr/bin/env python3
"""tsutatsu-fetcher.py -- NTA 基本通達 HTML を目次から辿って cache に取得する.

使い方:
    cd JuriCode-JP
    python tools/fetch-egov/tsutatsu-fetcher.py                 # souzoku + hyoka 両方
    python tools/fetch-egov/tsutatsu-fetcher.py --circular souzoku
    python tools/fetch-egov/tsutatsu-fetcher.py --force         # 既存 cache を上書き

取得対象 (2026-07-01 実測でロック):
    souzoku : 相続税法基本通達   /law/tsutatsu/kihon/sisan/sozoku2   -> cache/tsutatsu/souzoku
    hyoka   : 財産評価基本通達   /law/tsutatsu/kihon/sisan/hyoka_new -> cache/tsutatsu/hyoka

Why (設計):
    - NTA は目次ディレクトリ ('.../<circular>/') を索引配信しない (302->404) が、
      目次ページ '01.htm' は全 leaf への root-relative href を列挙する。よって
      索引ページ (1 セグメント '<NN>.htm') を BFS で辿り、content leaf
      (2 セグメント以上 '<NN>/<NN>.htm') だけを保存する。ページに実在する href
      だけを辿るので、soft-404 ('03.htm' 等は HTTP 200 でも本文はエラー) や
      相互参照ページ (leaf 0) は自然に cache へ入らない。
    - パーサ (parse-nta-tsutatsu.py) は cache を raw bytes で読み _detect_charset
      で per-file にデコードする。よって取得時に再エンコードせず、応答の bytes を
      verbatim 保存する (errors='replace' 等の非可逆変換は禁止)。
    - 既存 bulk-ingest.py と同じく stdlib urllib + User-Agent + sleep で実装
      (requests/bs4 依存を増やさない)。

完全性ゲート:
    leaf 数を実測ロック値 (sozoku=34 / hyoka=37) と突合し、不一致なら fail-loud。
    NTA がページを増減した場合は --expect で人間が新値を追認してから続行する
    (silent な取りこぼし/増加を握りつぶさない)。
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
USER_AGENT = "JuriCode-JP/0.2 (+https://github.com/JuriCode-JP) tsutatsu-fetcher"
_HREF_RE = re.compile(rb'href="([^"]+)"')
# NTA の soft-404 ページ (HTTP 200 で返るエラー本文) の目印。leaf 取得で出たら異常。
_SOFT_404_MARK = "指定されたページを表示できませんでした".encode("cp932")


@dataclass(frozen=True)
class Circular:
    """1 通達分の取得設定 (Why: 通達ごとに base path と cache 先だけが変わる)."""

    key: str
    label: str
    base_path: str  # host を除いた root-relative の目次 base (末尾 '/' なし)
    cache_dir: Path
    expected_leaves: int


CIRCULARS: dict[str, Circular] = {
    "souzoku": Circular(
        key="souzoku",
        label="相続税法基本通達",
        base_path="/law/tsutatsu/kihon/sisan/sozoku2",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "souzoku",
        expected_leaves=34,
    ),
    "hyoka": Circular(
        key="hyoka",
        label="財産評価基本通達",
        base_path="/law/tsutatsu/kihon/sisan/hyoka_new",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "hyoka",
        expected_leaves=37,
    ),
}


def http_get(url: str, timeout: int = 30) -> bytes:
    """URL を GET して応答 bytes を返す (fail-loud: HTTP エラーは送出)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定 https host)
        return resp.read()


def extract_links(html: bytes, base_path: str) -> tuple[set[str], set[str]]:
    """目次 HTML から (索引ページ集合, leaf 集合) を root-relative path で返す.

    Why: 索引 = base 直下 1 セグメント '<NN>.htm'、leaf = 2 セグメント以上
    '<NN>/<NN>.htm'。fragment (#a-N) と subtree 外の nav リンクは捨てる。
    """
    prefix = base_path + "/"
    index_pages: set[str] = set()
    leaves: set[str] = set()
    for m in _HREF_RE.finditer(html):
        href = m.group(1).decode("ascii", "ignore").split("#", 1)[0]
        if not href.startswith(prefix) or not href.endswith(".htm"):
            continue
        segments = href[len(prefix) :].split("/")
        if len(segments) == 1:
            index_pages.add(href)
        else:
            leaves.add(href)
    return index_pages, leaves


def discover_leaves(base_path: str, sleep: float) -> list[str]:
    """目次を BFS で辿り、全 content leaf を昇順で返す (実在 href のみ辿る)."""
    to_visit: list[str] = [f"{base_path}/01.htm"]
    seen_index: set[str] = set()
    all_leaves: set[str] = set()
    while to_visit:
        idx = to_visit.pop()
        if idx in seen_index:
            continue
        seen_index.add(idx)
        html = http_get(HOST + idx)
        index_pages, leaves = extract_links(html, base_path)
        all_leaves |= leaves
        for nxt in sorted(index_pages):
            if nxt not in seen_index:
                to_visit.append(nxt)
        time.sleep(sleep)
    return sorted(all_leaves)


def save_leaf(href: str, base_path: str, cache_dir: Path, *, force: bool) -> bool:
    """1 leaf を取得し cache_dir/<rel> へ raw bytes で保存。保存したら True。

    Why: 一時ファイルへ書いてから os.replace で原子的に置換し、途中失敗で
    壊れた cache を残さない (safe_write は text 専用のため bytes は自前で原子化)。
    """
    rel = href[len(base_path) + 1 :]  # 例: '01/01.htm'
    dest = cache_dir / rel
    if dest.exists() and not force:
        return False
    html = http_get(HOST + href)
    if _SOFT_404_MARK in html:
        raise RuntimeError(f"soft-404 page returned for leaf (NTA 側の異常): {href}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(html)
    os.replace(tmp, dest)
    return True


def fetch_circular(circ: Circular, sleep: float, *, force: bool, expect: int | None) -> int:
    """1 通達を取得して cache に保存。保存した leaf 数を返す (fail-loud)."""
    print("=" * 60)
    print(f"{circ.label} ({circ.key})  base={circ.base_path}")
    print("=" * 60)
    leaves = discover_leaves(circ.base_path, sleep)
    want = circ.expected_leaves if expect is None else expect
    print(f"  discovered leaves: {len(leaves)} (expected {want})")
    if len(leaves) != want:
        raise SystemExit(
            f"ERROR: leaf 数 {len(leaves)} != expected {want} for {circ.key}. "
            "NTA がページを増減した可能性。実測で確認し、正なら --expect で追認すること "
            "(silent な取りこぼし/増加を防ぐ完全性ゲート)。"
        )
    saved = 0
    for i, href in enumerate(leaves, 1):
        if save_leaf(href, circ.base_path, circ.cache_dir, force=force):
            saved += 1
        if i % 10 == 0:
            print(f"  {i}/{len(leaves)} processed ({saved} saved)")
        time.sleep(sleep)
    skipped = len(leaves) - saved
    print(f"  DONE: saved={saved}, skipped(existing)={skipped}, total={len(leaves)}")
    print(f"  cache: {circ.cache_dir}")
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch NTA 基本通達 HTML into cache.")
    parser.add_argument(
        "--circular",
        choices=[*sorted(CIRCULARS), "all"],
        default="all",
        help="取得対象 (既定: all = sozoku + hyoka)。",
    )
    parser.add_argument("--sleep", type=float, default=0.5, help="リクエスト間隔秒 (既定 0.5)。")
    parser.add_argument("--force", action="store_true", help="既存 cache を上書き。")
    parser.add_argument(
        "--expect",
        type=int,
        default=None,
        help="leaf 数の期待値を上書き (NTA 更新を人間が追認する場合のみ)。",
    )
    args = parser.parse_args(argv)

    targets = sorted(CIRCULARS) if args.circular == "all" else [args.circular]
    if args.expect is not None and len(targets) != 1:
        parser.error("--expect は --circular で 1 件に絞った時のみ指定可能。")

    total = 0
    for key in targets:
        total += fetch_circular(CIRCULARS[key], args.sleep, force=args.force, expect=args.expect)
    print("=" * 60)
    print(f"ALL DONE: {total} leaf saved across {len(targets)} circular(s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:  # fail-loud
        sys.exit(f"HTTP ERROR: {exc}")
    except urllib.error.URLError as exc:
        sys.exit(f"NETWORK ERROR: {exc}")

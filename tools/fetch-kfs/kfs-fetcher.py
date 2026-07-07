#!/usr/bin/env python3
"""kfs-fetcher.py -- 国税不服審判所 (KFS) 公表裁決事例要旨リーフ HTML を cache に取得する.

使い方:
    cd JuriCode-JP
    python tools/fetch-kfs/kfs-fetcher.py                 # 既定リーフ (固定資産の取得価額)
    python tools/fetch-kfs/kfs-fetcher.py --leaf MP/03/0204040000
    python tools/fetch-kfs/kfs-fetcher.py --force         # 既存 cache を上書き
    python tools/fetch-kfs/kfs-fetcher.py --no-permalinks # permalink index を取得しない

取得対象 (2026-07-04 P0 実測でロック):
    法人税 争点1 固定資産の取得価額 リーフ   /service/MP/03/0204040000.html
        -> cache/kfs/03/0204040000.html  (13 裁決要旨・Shift_JIS)
    上記リーフが参照する permalink index (平成4年度以降の裁決のみ・5 本)
        -> cache/kfs/JP/<巻号>/<通番>/index.html

Why (設計・tsutatsu-fetcher.py 逐語流用):
    - KFS は e-Gov でなく国税不服審判所の独自 CMS。リーフ HTML は Shift_JIS (cp932)。
      パーサ (parse-kfs-saiketsu.py) は cache を raw bytes で読み per-file にデコードする。
      よって取得時に再エンコードせず応答の bytes を verbatim 保存する
      (errors='replace' 等の非可逆変換は禁止・要旨は PDL1.0 で byte 忠実が必須)。
    - stdlib urllib + User-Agent + sleep で実装 (requests/bs4 依存を増やさない)。既存
      tsutatsu-fetcher.py と同じ http_get / 一時ファイル+os.replace 原子的保存を流用。
    - permalink (../../JP/<巻号>/<通番>/index.html) はリーフ本文の <a href> に実在する
      ものだけを辿る (soft-404 を握り込まない)。要旨自体はリーフに載るため permalink 本文は
      パースに不要だが、出所 (provenance) の保全のため cache する (--no-permalinks で無効化)。

完全性ゲート:
    リーフ内の permalink href 数を実測ロック値 (--expect-permalinks 既定 5) と突合し、不一致なら
    fail-loud。KFS がページを増減した場合は --expect-permalinks で人間が新値を追認してから続行する。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

HOST = "https://www.kfs.go.jp"
SERVICE_BASE = "/service"
USER_AGENT = "JuriCode-JP/0.2 (+https://github.com/JuriCode-JP) kfs-fetcher"
CACHE_ROOT = REPO_ROOT / "cache" / "kfs"

DEFAULT_LEAF = "MP/03/0204040000"  # 法人税 争点1 固定資産の取得価額 (パイロット)

_HREF_RE = re.compile(rb'href="([^"]+)"')
# permalink 相対パス例: ../../JP/88/09/index.html (リーフ MP/03/xxxx.html 基準)
_PERMALINK_RE = re.compile(r"(?:\.\./)*(JP/\d+/\d+/index\.html)")


def http_get(url: str, timeout: int = 30) -> bytes:
    """URL を GET して応答 bytes を返す (fail-loud: HTTP エラーは送出)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # 固定 https host
        return resp.read()


def _save_bytes(dest: Path, data: bytes, *, force: bool) -> bool:
    """raw bytes を dest へ原子的に保存。保存したら True (skip-if-exists)。

    Why: 一時ファイルへ書いてから os.replace で原子的に置換し、途中失敗で壊れた cache を
    残さない (safe_write は text 専用のため bytes は自前で原子化・tsutatsu-fetcher と同一)。
    """
    if dest.exists() and not force:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return True


def extract_permalinks(html: bytes) -> list[str]:
    """リーフ HTML から permalink 相対パス (JP/<巻号>/<通番>/index.html) を昇順一意で返す."""
    found: set[str] = set()
    for m in _HREF_RE.finditer(html):
        href = m.group(1).decode("ascii", "ignore")
        pm = _PERMALINK_RE.search(href)
        if pm:
            found.add(pm.group(1))
    return sorted(found)


def fetch_leaf(
    leaf: str, sleep: float, *, force: bool, fetch_permalinks: bool, expect_permalinks: int | None
) -> int:
    """1 リーフ (+ permalink index) を取得して cache に保存。保存件数を返す (fail-loud)."""
    leaf_url = f"{HOST}{SERVICE_BASE}/{leaf}.html"
    # cache は service/ を除いた相対 (MP/03/0204040000 -> cache/kfs/03/0204040000.html)。
    # 先頭セグメント (MP) はカテゴリ記号ゆえ剥がし、以降を cache パスにする (permalink JP/ と衝突しない)。
    rel = leaf.split("/", 1)[1] if "/" in leaf else leaf
    leaf_dest = CACHE_ROOT / f"{rel}.html"
    print("=" * 60)
    print(f"KFS leaf  {leaf}  -> {leaf_dest}")
    print("=" * 60)
    html = http_get(leaf_url)
    saved = 1 if _save_bytes(leaf_dest, html, force=force) else 0
    print(f"  leaf: {'saved' if saved else 'skipped(existing)'} ({len(html)} bytes)")

    permalinks = extract_permalinks(html)
    want = expect_permalinks
    print(
        f"  permalinks in leaf: {len(permalinks)}"
        + (f" (expected {want})" if want is not None else "")
    )
    if want is not None and len(permalinks) != want:
        raise SystemExit(
            f"ERROR: permalink 数 {len(permalinks)} != expected {want} for {leaf}. "
            "KFS がページを増減した可能性。実測で確認し、正なら --expect-permalinks で追認すること "
            "(silent な取りこぼし/増加を防ぐ完全性ゲート)。"
        )
    time.sleep(sleep)

    if fetch_permalinks:
        for i, rel_pl in enumerate(permalinks, 1):
            pl_url = f"{HOST}{SERVICE_BASE}/{rel_pl}"
            pl_dest = CACHE_ROOT / rel_pl  # cache/kfs/JP/<巻号>/<通番>/index.html
            data = http_get(pl_url)
            if _save_bytes(pl_dest, data, force=force):
                saved += 1
            print(f"  [{i}/{len(permalinks)}] permalink {rel_pl} ({len(data)} bytes)")
            time.sleep(sleep)

    print(f"  DONE: saved={saved} (leaf + permalinks)")
    print(f"  cache root: {CACHE_ROOT}")
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch KFS 公表裁決事例要旨 leaf HTML into cache.")
    parser.add_argument(
        "--leaf",
        default=DEFAULT_LEAF,
        help=f"リーフ path (service/ 以下・.html 除く。既定 {DEFAULT_LEAF})。",
    )
    parser.add_argument("--sleep", type=float, default=0.5, help="リクエスト間隔秒 (既定 0.5)。")
    parser.add_argument("--force", action="store_true", help="既存 cache を上書き。")
    parser.add_argument(
        "--no-permalinks", action="store_true", help="permalink index を取得しない (リーフのみ)。"
    )
    parser.add_argument(
        "--expect-permalinks",
        type=int,
        default=None,
        help="リーフ内 permalink 数の期待値 (完全性ゲート・人間追認用)。",
    )
    args = parser.parse_args(argv)

    saved = fetch_leaf(
        args.leaf,
        args.sleep,
        force=args.force,
        fetch_permalinks=not args.no_permalinks,
        expect_permalinks=args.expect_permalinks,
    )
    print("=" * 60)
    print(f"ALL DONE: {saved} file(s) saved for leaf {args.leaf}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:  # fail-loud
        sys.exit(f"HTTP ERROR: {exc}")
    except urllib.error.URLError as exc:
        sys.exit(f"NETWORK ERROR: {exc}")

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
追加 (2026-07-03・FU-536):
    sochi-hojin : 租税特別措置法関係通達(法人税編) /law/tsutatsu/kobetsu/hojin/sochiho/750214
                  -> cache/tsutatsu/sochi-hojin (個別通達・発遣日ルート・leaf 130)

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
    # 目次 (TOC) が leaf として live リンクするが実体が soft-404 の leaf 相対パス集合。
    # 通常 soft-404 は「索引が実在 leaf のみ列挙するので自然に除外」されるが、NTA の一部
    # 通達 (801226 申告所得税編・FU-540) は TOC が title 付きで live リンクする leaf の実体を
    # 掲載しておらず (NTA 側の stale TOC)、discover_leaves に混入する。ここに明示列挙して
    # discover 後に機械除外する (expected_leaves は除外後の実コンテンツ数)。NTA が TOC/実体を
    # 増減したら完全性ゲート (除外後 != expected_leaves) が fail-loud で捕捉する。
    known_soft404: frozenset[str] = frozenset()
    # TOC->content モード (FU-547・800423 措法40条取扱通達)。既定 False は既存 BFS。True のとき
    # 目次 01.htm がリストする **同階層の 1 セグメント content ページ** (02.htm..23.htm) を content
    # leaf として取得する。この通達は 01.htm=目次・02..23.htm=本文という flat 構成で、本文ページの
    # href が base 相対 1 セグメント ('02.htm') ゆえ既存 discover_leaves は全て「索引」と誤分類し
    # BFS しても 2 セグメント leaf がゼロ = 0 leaf になる (FU-547 P0 実測)。toc_content=True は
    # 目次から 1 セグメント href を content として拾い、flat rel ('02.htm') で cache 保存する。
    # 既存 7 Circular は False ゆえ discover 経路不変 (後方互換 byte-regression で実証)。
    toc_content: bool = False


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
    # 租税特別措置法関係通達(法人税編)・FU-536。個別通達ゆえ base は kobetsu/.../発遣日 750214。
    # leaf 130 (数値12章 128 + bessi + zenbun・cache 実測ロック。soft-404 の欠番章は索引に leaf を
    # 出さないので自然に除外される)。
    "sochi-hojin": Circular(
        key="sochi-hojin",
        label="租税特別措置法関係通達（法人税編）",
        base_path="/law/tsutatsu/kobetsu/hojin/sochiho/750214",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-hojin",
        expected_leaves=130,
    ),
    # 租税特別措置法関係通達(山林所得・譲渡所得関係)・FU-539。所得税分野の個別通達ゆえ base は
    # shotoku/sochiho/発遣日 710826/sanrin/sanjyou (発遣 直資3-8・昭46.8.26・NTA menu 実確認)。
    # leaf 52 (soti30〜41 章 + fusoku・cache 実測ロック。soti36=01/03/06・soti38 なし等の欠番章は
    # 索引が実在 leaf のみ列挙するので自然に除外される・P0-1 で確認)。
    "sochi-joto": Circular(
        key="sochi-joto",
        label="租税特別措置法関係通達（山林所得・譲渡所得関係）",
        base_path="/law/tsutatsu/kobetsu/shotoku/sochiho/710826/sanrin/sanjyou",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-joto",
        expected_leaves=52,
    ),
    # 租税特別措置法関係通達(申告所得税関係)・FU-540。所得税分野の個別通達ゆえ base は
    # shotoku/sochiho/発遣日 801226/sinkoku (NTA sotihou.htm ランディング実確認・P0-1)。
    # leaf 54 (単一トップ索引 01.htm が全 leaf を 3 階層 '57/NN/NN.htm' で直接列挙・多階層
    # サブ索引なし=既存 discover_leaves で全発見・P0-1 実測)。TOC が live リンクする 6 leaf
    # (57/10/02・05・05_3・05_5・11/02・13/02 = 措置法 10の2/10の5/10の5の2/10の5の5/11の2/
    # 13の3 系の 17 directive) は実体が soft-404 = NTA 側 stale TOC ゆえ known_soft404 で機械除外
    # (実コンテンツ 54 leaf → corpus 344 directive・佐藤ロック 2026-07-04)。17 directive は NTA が
    # 該当 URL で公開しておらず取込不能 (将来 NTA 公開 or 020624 他編で再取込)。
    "sochi-shotoku": Circular(
        key="sochi-shotoku",
        label="租税特別措置法関係通達（申告所得税関係）",
        base_path="/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-shotoku",
        expected_leaves=54,
        known_soft404=frozenset(
            {
                "57/10/02.htm",
                "57/10/05.htm",
                "57/10/05_3.htm",
                "57/10/05_5.htm",
                "57/11/02.htm",
                "57/13/02.htm",
            }
        ),
    ),
    # 租税特別措置法関係通達(相続税法の特例関係)・FU-541。相続税分野の個別通達ゆえ base は
    # sozoku/sochiho/発遣日 080708 (NTA sochiho landing 実確認・P0-1)。leaf 58 (単一/二段トップ
    # 索引 01.htm+02.htm が全 leaf を 3 階層 '69_4/NN.htm' 等で直接列挙・多階層サブ索引なし=既存
    # discover_leaves で全発見・P0-1 実測 58/58 取りこぼしなし)。soft-404 は 0 (全 58 leaf 実体あり
    # ・P0-4 実測) ゆえ known_soft404 不要。corpus は STEP A parse で実測ロック (2 レベル現行分)。
    "sochi-sozoku": Circular(
        key="sochi-sozoku",
        label="租税特別措置法関係通達（相続税法の特例関係）",
        base_path="/law/tsutatsu/kobetsu/sozoku/sochiho/080708",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-sozoku",
        expected_leaves=58,
    ),
    # 租税特別措置法(株式等に係る譲渡所得等関係)の取扱い・FU-542。所得税(譲渡所得)分野の個別通達。
    # base は shotoku/sochiho/発遣日 020624/sanrin (NTA sochiho landing 実確認・P0-1・唯一の entry。
    # 020624 直下 index は soft-404 で landing のみが sanrin/01.htm を live リンク)。leaf 18
    # (1273 系 37の10〜37の14 + 1273_1 + zenbun・索引 01/03 を BFS 全発見・sanrin 外なし)。
    # soft-404 は 0 (全 18 leaf 実体あり・P0-4) ゆえ known_soft404 不要。旧版 1273_1 は parser 側
    # (_CHAPTER_DIR_RE の \d{4} 接尾なし) で除外。corpus は STEP A parse で実測ロック。
    "sochi-kabushiki": Circular(
        key="sochi-kabushiki",
        label="租税特別措置法（株式等に係る譲渡所得等関係）の取扱い",
        base_path="/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-kabushiki",
        expected_leaves=18,
    ),
    # 租税特別措置法に係る所得税の取扱い(源泉所得税関係)・FU-546。所得税分野の個別通達ゆえ
    # base は shotoku/sochiho/発遣日 880331/gensen/58 (NTA sotihou.htm landing の唯一 live
    # href = 880331/gensen/58/01.htm を実確認・P0-1)。leaf 18 (章 dir 03〜42 の 16 leaf +
    # zenbun/fusoku を BFS 全発見・P0-1 実測)。soft-404 は 0 (全 18 leaf 実体あり・P0-4) ゆえ
    # known_soft404 不要。zenbun/fusoku は parser 側 (_CHAPTER_DIR_RE) で非 directive として除外。
    "sochi-gensen": Circular(
        key="sochi-gensen",
        label="租税特別措置法に係る所得税の取扱い（源泉所得税関係）",
        base_path="/law/tsutatsu/kobetsu/shotoku/sochiho/880331/gensen/58",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-gensen",
        expected_leaves=18,
    ),
    # 租税特別措置法関係通達(第40条 取扱い)・FU-547。所得税(譲渡所得)分野の個別通達 (直資2-181・
    # 昭55.4.23)。base は shotoku/sochiho/発遣日 800423 (NTA sotihou.htm landing の live href
    # 800423/01.htm を実確認・P0-1)。この通達は 01.htm=目次・02..23.htm=本文の flat 構成で、本文
    # href が base 相対 1 セグメントゆえ既存 BFS では 0 leaf になる (toc_content=True で目次から
    # content を拾う)。content ページ 24 (02..21 + 12_2 + 21_2 + 22(附則) + 23 を 01.htm 目次が
    # 全列挙・P0 実測)。soft-404 は 0 (全 24 ページ実体あり) ゆえ known_soft404 不要。附則 22.htm は
    # <li> 構造ゆえ parser の <p><strong> 抽出で自然に 0 directive (本則 60 directive)。
    "sochi-40jou": Circular(
        key="sochi-40jou",
        label="租税特別措置法関係通達（第40条 取扱い）",
        base_path="/law/tsutatsu/kobetsu/shotoku/sochiho/800423",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-40jou",
        expected_leaves=24,
        toc_content=True,
    ),
    # 租税特別措置法関係通達(間接諸税関係)・FU-551。揮発油税・石油石炭税・航空機燃料税・
    # 自動車重量税・印紙税の間接諸税に係る措置法通達 (平11.6.25 課消4-15 ほか)。base は
    # kansetsu/sochiho/発遣日 990625 (NTA landing 実確認・PS-6)。sochi-40jou (800423) と同じ
    # 01.htm=目次・02..08.htm=本文の flat TOC 構成 (本文 href が base 相対 1 セグメントゆえ既存
    # BFS では 0 leaf・toc_content=True で目次から content を拾う)。content ページ 14
    # (02/03/03_2/04/04_2/05/05_2/06/07/07_2/07_3/07_4/07_5/08 を 01.htm 目次が全列挙・PS-6 実測。
    # 頁順≠章順: 06=第3章・07 系=第5章・08=第4章)。soft-404 は 0 (全 14 ページ実体あり) ゆえ
    # known_soft404 不要。
    "sochi-kansetsu": Circular(
        key="sochi-kansetsu",
        label="租税特別措置法関係通達（間接諸税関係）",
        base_path="/law/tsutatsu/kobetsu/kansetsu/sochiho/990625",
        cache_dir=REPO_ROOT / "cache" / "tsutatsu" / "sochi-kansetsu",
        expected_leaves=14,
        toc_content=True,
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


def discover_toc_content(base_path: str, sleep: float) -> list[str]:
    """TOC->content モード (FU-547): 目次 01.htm がリストする同階層 content ページを返す。

    Why: 800423 措法40条取扱通達は 01.htm=目次・02..23.htm=本文の flat 構成。本文 href は base
    相対 1 セグメント ('02.htm') ゆえ discover_leaves は「索引」と誤分類し 0 leaf になる。ここでは
    目次 01.htm 内の base 直下 1 セグメント href を content leaf として拾い (自己参照 01.htm を
    除外)、昇順で返す。実在 href のみ辿るので nav / 外部リンクは extract_links の base prefix
    ゲートで除外。
    """
    landing = f"{base_path}/01.htm"
    html = http_get(HOST + landing)
    index_pages, leaves = extract_links(html, base_path)
    # 1 セグメント href = content ページ (目次自身を除く)。2 セグメント leaf が万一あれば併合する
    # (この通達は 0 だが後続の TOC 型通達で入れ子があっても取りこぼさない・完全性ゲートで検算)。
    content = {h for h in index_pages if h != landing} | set(leaves)
    time.sleep(sleep)
    return sorted(content)


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
    if circ.toc_content:
        leaves = discover_toc_content(circ.base_path, sleep)
    else:
        leaves = discover_leaves(circ.base_path, sleep)
    # 既知の soft-404 leaf (NTA stale TOC・live リンクだが実体なし) を機械除外する。
    # 除外後の実コンテンツ数を完全性ゲートにかけるので、NTA が TOC/実体を増減したら
    # (未知の soft-404 混入・既知の soft-404 復活/消滅) 除外後 != expected で fail-loud になる。
    if circ.known_soft404:
        prefix_len = len(circ.base_path) + 1
        kept = [h for h in leaves if h[prefix_len:] not in circ.known_soft404]
        removed = len(leaves) - len(kept)
        print(f"  excluded {removed} known soft-404 leaf(s) (NTA stale TOC・FU-540)")
        leaves = kept
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

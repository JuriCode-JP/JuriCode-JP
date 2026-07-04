"""test_tsutatsu_fetcher.py -- tsutatsu-fetcher.py の純関数 (network なし) テスト.

Why this test exists:
    fetcher の唯一の壊れやすいロジックは目次 HTML から leaf / 索引ページを
    振り分ける extract_links。ここが誤ると (a) subtree 外の nav リンクや
    (b) fragment 違いの重複、(c) 索引ページの leaf 誤認 が cache を汚す。
    network を叩かずに合成 HTML で分類規則を pin する (CI-safe / hermetic)。

    fetcher 本体はハイフン入りファイル名 (tsutatsu-fetcher.py) ゆえ import 文で
    読めないので importlib.util.spec_from_file_location で読み込む
    (parse-nta-tsutatsu.py と同じ方式)。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_FETCHER = _THIS.parents[1] / "tsutatsu-fetcher.py"


def _load():
    spec = importlib.util.spec_from_file_location("tsutatsu_fetcher", _FETCHER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_MOD = _load()
_BASE = "/law/tsutatsu/kihon/sisan/hyoka_new"


def _html(hrefs: list[str]) -> bytes:
    body = "".join(f'<a href="{h}">x</a>' for h in hrefs)
    return f"<html><body>{body}</body></html>".encode("cp932")


def test_leaf_vs_index_classification() -> None:
    """1 セグメント='<NN>.htm'=索引、2 セグメント以上=leaf に振り分ける."""
    index, leaves = _MOD.extract_links(
        _html(
            [
                f"{_BASE}/02.htm",  # 索引 (1 seg)
                f"{_BASE}/01/01.htm",  # leaf (2 seg)
                f"{_BASE}/08/09.htm",  # leaf
            ]
        ),
        _BASE,
    )
    assert index == {f"{_BASE}/02.htm"}
    assert leaves == {f"{_BASE}/01/01.htm", f"{_BASE}/08/09.htm"}


def test_fragment_stripped_and_deduped() -> None:
    """#a-N fragment を除去し、同一 leaf の複数アンカーを 1 件に畳む."""
    _, leaves = _MOD.extract_links(
        _html(
            [
                f"{_BASE}/01/01.htm#a-1",
                f"{_BASE}/01/01.htm#a-4_2",
                f"{_BASE}/01/01.htm",
            ]
        ),
        _BASE,
    )
    assert leaves == {f"{_BASE}/01/01.htm"}


def test_out_of_subtree_and_nonhtm_excluded() -> None:
    """base subtree 外の nav リンク・非 .htm を除外する."""
    index, leaves = _MOD.extract_links(
        _html(
            [
                "/law/tsutatsu/menu.htm",  # subtree 外
                "/law/index.htm",  # subtree 外
                f"{_BASE}/01/01.pdf",  # 非 .htm
                f"{_BASE}/02/03.htm",  # 正しい leaf
            ]
        ),
        _BASE,
    )
    assert index == set()
    assert leaves == {f"{_BASE}/02/03.htm"}


def test_deeper_leaf_paths_are_leaves() -> None:
    """目 レベル (3 セグメント '<NN>/<NN>/<NN>.htm') も leaf として拾う."""
    _, leaves = _MOD.extract_links(_html([f"{_BASE}/09/01/01.htm"]), _BASE)
    assert leaves == {f"{_BASE}/09/01/01.htm"}


def test_expected_leaf_counts_locked() -> None:
    """実測ロック値 (sozoku=34 / hyoka=37 / sochi-hojin=130) が config に固定されている."""
    assert _MOD.CIRCULARS["souzoku"].expected_leaves == 34
    assert _MOD.CIRCULARS["hyoka"].expected_leaves == 37
    assert _MOD.CIRCULARS["souzoku"].base_path.endswith("/sisan/sozoku2")
    assert _MOD.CIRCULARS["hyoka"].base_path.endswith("/sisan/hyoka_new")
    # FU-536: 措置法通達(法人税編) は個別通達ゆえ kobetsu/.../発遣日 750214・leaf 130。
    assert _MOD.CIRCULARS["sochi-hojin"].expected_leaves == 130
    assert _MOD.CIRCULARS["sochi-hojin"].base_path.endswith("/kobetsu/hojin/sochiho/750214")
    # FU-539: 措置法通達(山林所得・譲渡所得編) は所得税分野の個別通達・発遣 710826・leaf 52。
    assert _MOD.CIRCULARS["sochi-joto"].expected_leaves == 52
    assert _MOD.CIRCULARS["sochi-joto"].base_path.endswith(
        "/kobetsu/shotoku/sochiho/710826/sanrin/sanjyou"
    )
    # FU-540: 措置法通達(申告所得税編)・発遣 801226・実コンテンツ leaf 54 (6 soft-404 除外後)。
    assert _MOD.CIRCULARS["sochi-shotoku"].expected_leaves == 54
    assert _MOD.CIRCULARS["sochi-shotoku"].base_path.endswith(
        "/kobetsu/shotoku/sochiho/801226/sinkoku"
    )
    # 既知 soft-404 (NTA stale TOC) を明示列挙し discover 後に機械除外する。
    assert _MOD.CIRCULARS["sochi-shotoku"].known_soft404 == frozenset(
        {
            "57/10/02.htm",
            "57/10/05.htm",
            "57/10/05_3.htm",
            "57/10/05_5.htm",
            "57/11/02.htm",
            "57/13/02.htm",
        }
    )
    # FU-541: 措置法通達(相続税法の特例関係)・発遣 080708・leaf 58 (soft-404 0=known_soft404 空)。
    assert _MOD.CIRCULARS["sochi-sozoku"].expected_leaves == 58
    assert _MOD.CIRCULARS["sochi-sozoku"].base_path.endswith("/kobetsu/sozoku/sochiho/080708")
    assert _MOD.CIRCULARS["sochi-sozoku"].known_soft404 == frozenset()
    # FU-542: 措置法通達(株式等譲渡)・発遣 020624/sanrin・leaf 18 (soft-404 0=known_soft404 空)。
    assert _MOD.CIRCULARS["sochi-kabushiki"].expected_leaves == 18
    assert _MOD.CIRCULARS["sochi-kabushiki"].base_path.endswith(
        "/kobetsu/shotoku/sochiho/020624/sanrin"
    )
    assert _MOD.CIRCULARS["sochi-kabushiki"].known_soft404 == frozenset()
    # FU-546: 措置法通達(源泉所得税)・発遣 880331/gensen/58・leaf 18 (soft-404 0=known_soft404 空)。
    assert _MOD.CIRCULARS["sochi-gensen"].expected_leaves == 18
    assert _MOD.CIRCULARS["sochi-gensen"].base_path.endswith(
        "/kobetsu/shotoku/sochiho/880331/gensen/58"
    )
    assert _MOD.CIRCULARS["sochi-gensen"].known_soft404 == frozenset()
    # FU-547: 措置法通達(第40条 取扱い)・発遣 800423・TOC->content モード・content ページ 24
    # (01.htm=目次・02..23.htm=本文)。soft-404 0 (全 24 ページ実体あり)=known_soft404 空。
    assert _MOD.CIRCULARS["sochi-40jou"].expected_leaves == 24
    assert _MOD.CIRCULARS["sochi-40jou"].base_path.endswith("/kobetsu/shotoku/sochiho/800423")
    assert _MOD.CIRCULARS["sochi-40jou"].known_soft404 == frozenset()
    assert _MOD.CIRCULARS["sochi-40jou"].toc_content is True

    # FU-551: 措置法通達(間接諸税関係)・発遣 990625・TOC->content モード・content ページ 14
    # (01.htm=目次・02..08.htm 系=本文)。soft-404 0 (全 14 ページ実体あり)=known_soft404 空。
    assert _MOD.CIRCULARS["sochi-kansetsu"].expected_leaves == 14
    assert _MOD.CIRCULARS["sochi-kansetsu"].base_path.endswith("/kobetsu/kansetsu/sochiho/990625")
    assert _MOD.CIRCULARS["sochi-kansetsu"].known_soft404 == frozenset()
    assert _MOD.CIRCULARS["sochi-kansetsu"].toc_content is True


def test_toc_content_flag_backward_compat() -> None:
    """toc_content は TOC->content 型 (sochi-40jou/sochi-kansetsu) のみ True。他は BFS で False."""
    toc_content_keys = {"sochi-40jou", "sochi-kansetsu"}
    for key, circ in _MOD.CIRCULARS.items():
        expected = key in toc_content_keys
        assert circ.toc_content is expected, (
            f"{key} の toc_content が想定外: {circ.toc_content} (期待 {expected})"
        )


def test_discover_toc_content(monkeypatch) -> None:
    """TOC->content モード: 目次 01.htm の同階層 1 セグメント content ページを拾い、自己参照
    01.htm と subtree 外リンクを除外する (FU-547・network なし=http_get を monkeypatch)."""
    base = "/law/tsutatsu/kobetsu/shotoku/sochiho/800423"
    toc = _html(
        [
            f"{base}/01.htm",  # 目次自身 (除外)
            f"{base}/02.htm#a-1",  # content (fragment 付き)
            f"{base}/03.htm",  # content
            f"{base}/12_2.htm",  # 枝章 content
            "/law/tsutatsu/menu.htm",  # subtree 外 (除外)
            "/law/index.htm",  # subtree 外 (除外)
        ]
    )
    monkeypatch.setattr(_MOD, "http_get", lambda url, timeout=30: toc)
    got = _MOD.discover_toc_content(base, sleep=0.0)
    assert got == [
        f"{base}/02.htm",
        f"{base}/03.htm",
        f"{base}/12_2.htm",
    ]

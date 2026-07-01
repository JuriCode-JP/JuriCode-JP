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
    """実測ロック値 (sozoku=34 / hyoka=37) が config に固定されている."""
    assert _MOD.CIRCULARS["sozoku"].expected_leaves == 34
    assert _MOD.CIRCULARS["hyoka"].expected_leaves == 37
    assert _MOD.CIRCULARS["sozoku"].base_path.endswith("/sisan/sozoku2")
    assert _MOD.CIRCULARS["hyoka"].base_path.endswith("/sisan/hyoka_new")

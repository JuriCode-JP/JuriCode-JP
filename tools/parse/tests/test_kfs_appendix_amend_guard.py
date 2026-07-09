"""test_kfs_appendix_amend_guard.py -- [A][B] 附則 + 改正prefix 偽リンク恒久ガードの hermetic test.

Why ([A][B] 防御・偽リンク0 恒久ガード):
    - [A] 附則: 参照条文の 附則第N条 が本則条番号にマップされると、将来その本則条が corpus に
      追加された時点で偽リンク化する (附則は独立 corpus 非保持)。附則トークンを分離し、後続条を
      reason="appendix" で非リンク化して恒久的に本則マップを止める。
    - [B] 改正 prefix: 「○○法の一部を改正する法律」「○○法を改正する法律・政令」「○○法等の…」は
      別法令の名称。埋め込み法令名 (○○法) が governing law と誤認されると続く条が偽リンク化する
      (現データ不在=latent)。law の負の先読みで 3 形 (等 / の一部を改正 / を改正する) を除外する。

    本 FU は link-neutral (実リンク数を変えない防御ガード)。よって #72 の複数条解決・正当引用は
    不変であることを回帰ケースで固定する。corpus は module-global 注入で data/v0.2 非依存。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

_PARSER_PATH = _REPO_ROOT / "tools" / "parse" / "parse-kfs-saiketsu.py"

# 回帰ガード用の最小 corpus (正当引用が link することを確認する)。
_CORPUS = {
    "shouhi-zei-hou-art-30",
    "shouhi-zei-hou-art-6",
    "shouhi-zei-hou-shikkourei-art-14",
    "chihou-zei-hou-art-343",
    "chihou-zei-hou-art-9-10",  # 本則が実在しても附則参照は appendix で非リンクであること
    "shotoku-zei-hou-art-9",
}


def _load_parser():
    spec = importlib.util.spec_from_file_location("parse_kfs_saiketsu", _PARSER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._ARTICLE_CORPUS = set(_CORPUS)
    return mod


def _links(mod, line: str) -> list[str]:
    return [lk["article_id"] for lk in mod.resolve_sanshou_jouken([line])["links"]]


def _reasons(mod, line: str) -> list[str]:
    return [u["reason"] for u in mod.resolve_sanshou_jouken([line])["unlinked"]]


# ---- [A] 附則 -----------------------------------------------------------


def test_appendix_reference_not_mapped_to_main_article():
    """附則第N条 は本則 (art-N) にマップせず reason=appendix で非リンク。

    corpus に本則 chihou-art-9-10 が存在しても附則参照は link しないこと (将来の偽リンク防止)。
    """
    mod = _load_parser()
    line = "地方税法附則第9条の10第1項"
    assert _links(mod, line) == []
    assert _reasons(mod, line) == ["appendix"]


def test_same_law_after_appendix_returns_to_main():
    """附則の後に 同法第N条 が来たら本則へ戻ってリンクする (base_name 保持)。"""
    mod = _load_parser()
    # 地方税法附則... の後の 同法第343条 は本則 chihou-art-343 へ戻る。
    line = "地方税法附則第9条の10第1項、同法第343条第1項"
    assert _links(mod, line) == ["chihou-zei-hou-art-343"]


# ---- [B] 改正 prefix 3 形 -----------------------------------------------


def test_amendment_prefix_ichibu_not_linked():
    """『○○法の一部を改正する法律第N条』は別法令名ゆえ非リンク。"""
    mod = _load_parser()
    assert _links(mod, "消費税法の一部を改正する法律第7条") == []


def test_amendment_prefix_tou_not_linked():
    """『○○法等の一部を改正する法律第N条』(等形) も非リンク。"""
    mod = _load_parser()
    assert _links(mod, "消費税法等の一部を改正する法律第7条") == []


def test_amendment_prefix_wo_kaisei_not_linked():
    """『○○法を改正する法律第N条』も非リンク。"""
    mod = _load_parser()
    assert _links(mod, "所得税法を改正する法律第9条") == []


# ---- link-neutral 回帰ガード (正当引用は不変) ---------------------------


def test_legitimate_citations_still_link():
    """正当な引用は従来どおり link する (link-neutral)。"""
    mod = _load_parser()
    assert _links(mod, "消費税法第30条") == ["shouhi-zei-hou-art-30"]
    assert _links(mod, "地方税法第343条第1項") == ["chihou-zei-hou-art-343"]


def test_number72_multiarticle_and_shikkourei_unchanged():
    """#72 の複数条 + 同法施行令解決が壊れていないこと。"""
    mod = _load_parser()
    assert _links(mod, "消費税法第6条第1項、同法施行令第14条") == [
        "shouhi-zei-hou-art-6",
        "shouhi-zei-hou-shikkourei-art-14",
    ]

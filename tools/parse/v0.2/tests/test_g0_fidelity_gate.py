"""test_g0_fidelity_gate.py -- G0 忠実性ゲート (Phase 0 調査コード) の unit tests.

Why: G0 は「欠落の全体像」を数値化する計測器。計測器自体が誤ると Phase 0 の
結論全体が汚染されるため、分類ロジック (欠落/順序/過剰/書式差) を合成データで固定する。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_V02_DIR = Path(__file__).resolve().parent.parent
if str(_V02_DIR) not in sys.path:
    sys.path.insert(0, str(_V02_DIR))

_spec = importlib.util.spec_from_file_location("g0_fidelity_gate", _V02_DIR / "g0_fidelity_gate.py")
g0 = importlib.util.module_from_spec(_spec)
sys.modules["g0_fidelity_gate"] = g0
_spec.loader.exec_module(g0)

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET


SYNTH_XML = """<Law><LawBody><LawTitle>テスト法</LawTitle><MainProvision>
<Article Num="1">
  <ArticleTitle>第一条</ArticleTitle>
  <Paragraph Num="1">
    <ParagraphNum/>
    <ParagraphSentence>
      <Sentence Function="main">本文である。</Sentence>
      <Sentence Function="proviso">ただし、例外とする。</Sentence>
    </ParagraphSentence>
    <Item Num="1">
      <ItemTitle>一</ItemTitle>
      <ItemSentence><Sentence>一号の本文として十分に長い内容をここに記載する。</Sentence></ItemSentence>
      <Subitem1 Num="1">
        <Subitem1Title>イ</Subitem1Title>
        <Subitem1Sentence><Sentence>イの細別の本文として十分に長い内容を記載する。</Sentence></Subitem1Sentence>
      </Subitem1>
    </Item>
  </Paragraph>
</Article>
<Article Num="2_2">
  <ArticleTitle>第二条の二</ArticleTitle>
  <Paragraph Num="1">
    <ParagraphSentence><Sentence>枝番条文の本文。</Sentence></ParagraphSentence>
  </Paragraph>
</Article>
<Article Num="3:5"><ArticleTitle>第三条から第五条まで</ArticleTitle>
  <Paragraph Num="1"><ParagraphSentence><Sentence>削除</Sentence></ParagraphSentence></Paragraph>
</Article>
</MainProvision></LawBody></Law>"""


def _article(num: str) -> dict:
    root = ET.fromstring(SYNTH_XML)
    articles, _ = g0.walk_main_articles(root)
    return articles[num]


def _compare(num: str, md_blocks: list[str]) -> dict:
    art = _article(num)
    return g0.compare_article(art["groups"], art["extra"], md_blocks)


def test_norm_collapses_all_whitespace_only():
    assert g0.norm("あ 　い\nう\tえ") == "あいうえ"
    # 文字は変えない (全角半角・漢数字はそのまま)
    assert g0.norm("第１２３条ＡＢＣ") == "第１２３条ＡＢＣ"


def test_walk_main_articles_units_and_ranges():
    root = ET.fromstring(SYNTH_XML)
    articles, ranges = g0.walk_main_articles(root)
    assert set(articles) == {"1", "2-2"}  # underscore -> hyphen 正規化
    assert ranges == ["3:5"]
    assert len(articles["1"]["groups"]) == 1  # 項 1 つ
    kinds = [u.kind for u in articles["1"]["groups"][0]]
    assert kinds == ["para", "proviso", "item", "subitem"]
    assert articles["1"]["extra"] == []


_ITEM = "一号の本文として十分に長い内容をここに記載する。"
_SUBITEM = "イの細別の本文として十分に長い内容を記載する。"


def test_compare_exact_match():
    r = _compare("1", ["本文である。ただし、例外とする。" + _ITEM + _SUBITEM])
    assert r["exact"] is True


def test_compare_missing_item_and_subitem_classified():
    r = _compare("1", ["本文である。ただし、例外とする。"])  # 号・細別が正本に無い
    assert r["exact"] is False
    assert r["missing"] == {"kou_missing": 1, "saibetsu_missing": 1}
    assert r["excess_chars"] == 0


def test_compare_missing_proviso_classified():
    r = _compare("1", ["本文である。" + _ITEM + _SUBITEM])
    assert r["missing"] == {"tadashi_missing": 1}


def test_compare_order_violation_detected():
    """骨格 unit (>= 30 字) の順序入れ替わりは order_violations に計上される."""
    long_a = "第一の項の本文としてここに三十文字を超える長さの文章を確実に記載するものとする。"
    long_b = "第二の項の本文としてここに三十文字を超える長さの文章を別途確実に記載するものとする。"
    groups = [[g0.Unit("para", long_a)], [g0.Unit("para", long_b)]]
    # md 側で項の中身が入れ替わっている
    r = g0.compare_article(groups, [], [long_b, long_a])
    assert r["exact"] is False
    assert r["order_violations"] >= 1
    assert r["missing"] == {}


def test_compare_short_unit_coincidence_not_order():
    """短 unit のブロック外一致は順序と主張せず欠落 + ambiguous に分類する.

    Why: houjin-zei-hou art 10 / art 150 で短い号 (「第八十条」「その該当する
    こととなつた日」) が他の項本文中に偶然出現し ORDER/OK と誤判定された
    実測 false positive の再発防止。
    """
    para = "資本金の額は第八十条による。ここに三十文字を超える十分な長さの本文を確実に置く。"
    groups = [[g0.Unit("para", para), g0.Unit("item", "第八十条")]]
    r = g0.compare_article(groups, [], [para])
    assert r["order_violations"] == 0
    assert r["short_match_ambiguous"] == 1
    assert r["missing"] == {"kou_missing": 1}


def test_compare_cross_block_no_false_order():
    """繰り返しの多い条文で unit が別項に吸着しない (art 64-7 実測バグの再現).

    第 1 項の号テキストが第 2 項本文にも出現するケースで、第 2 項の para が
    順序違反と誤判定されないこと。
    """
    p1 = "第一の項の本文としてここに三十文字を超える長さの文章を確実に記載するものとする。"
    kou = "その該当することとなつた日"
    p2 = "第二の項は" + kou + "を含む三十文字を超える長さの本文をここに確実に記載する。"
    groups = [[g0.Unit("para", p1), g0.Unit("item", kou)], [g0.Unit("para", p2)]]
    # md: 号は欠落、項は正順 (旧実装は kou が p2 内に吸着し p2 を ORDER と誤判定)
    r = g0.compare_article(groups, [], [p1, p2])
    assert r["order_violations"] == 0
    assert r["missing"] == {"kou_missing": 1}
    assert r["short_match_ambiguous"] == 1


def test_compare_paragraph_count_mismatch_flagged():
    p1 = "第一の項の本文としてここに三十文字を超える長さの文章を確実に記載するものとする。"
    groups = [[g0.Unit("para", p1)]]
    r = g0.compare_article(groups, [], [p1, "余分なブロック"])
    assert r["paragraph_count_mismatch"] is True


def test_compare_excess_detected():
    r = _compare("2-2", ["枝番条文の本文。勝手に追加された文。"])
    assert r["exact"] is False
    assert r["excess_chars"] == len(g0.norm("勝手に追加された文。"))
    assert "勝手に追加された文" in r["excess_sample"]


def test_md_paragraph_texts_strips_markers():
    md_text = (
        "---\narticle_id: x\n---\n\n# テスト法 第1条\n\n## 原文 (日本語)\n\n"
        "### 第一条\n\n<!-- segment: simple id: x-p1 -->\n本文である。\n"
    )
    paras, marker_lines = g0.md_paragraph_texts(md_text)
    assert marker_lines == 1
    assert paras == ["本文である。"]


def test_strip_format_pipes_preserves_escaped_pipe():
    assert g0._strip_format_pipes("| セルA | セル\\|B |") == " セルA  セル|B "


def test_compare_md_to_chunks_all_missing():
    r = g0.compare_md_to_chunks(["本文である。"], [], [])
    assert r["all_chunks_missing"] is True
    assert r["parser_chunks_missing"] is True
    assert r["exact"] is False


def test_compare_md_to_chunks_exact_and_kou_only_in_chunks():
    chunks = [
        {"segment_type": "simple", "text": "本文である。"},
        {"segment_type": "kou", "text": "一号の本文"},  # XML 別経路 (F3)
        {"segment_type": "rollup", "text": "本文である。一号の本文"},  # 派生: 除外
    ]
    r = g0.compare_md_to_chunks(["本文である。"], chunks, [])
    assert r["exact"] is True
    assert r["kou_chunks"] == 1
    assert r["kou_chunks_not_in_md"] == 1
    assert r["all_chunks_missing"] is False

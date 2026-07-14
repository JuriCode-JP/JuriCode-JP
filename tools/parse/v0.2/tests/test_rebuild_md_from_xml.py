"""test_rebuild_md_from_xml.py -- 正本 md 再生成 (format-spec §5.2 = 案A) の unit tests.

固定する不変条件:
  1. 空白畳み込み後、生成本文 == XML 条文本文 (G0-a exact が自明に成立すること)
  2. 号・細別・表・SupplNote を落とさない
  3. 内部マーカーを本文に入れない
  4. **curated frontmatter (cases / amendments) と 原文セクション以降を破壊しない**
     (parse-egov 再実行だと消える。これが in-place rebuild である理由)
  5. Column 構造 (定義規定の号) で XML の整形用改行を本文に混ぜない
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import yaml

_V02 = Path(__file__).resolve().parent.parent
if str(_V02) not in sys.path:
    sys.path.insert(0, str(_V02))

_spec = importlib.util.spec_from_file_location(
    "rebuild_md_from_xml", _V02 / "rebuild_md_from_xml.py"
)
rb = importlib.util.module_from_spec(_spec)
sys.modules["rebuild_md_from_xml"] = rb
_spec.loader.exec_module(rb)

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

_WS = re.compile(r"[\s　]+")


def norm(s: str) -> str:
    return _WS.sub("", s)


ARTICLE_XML = """<Article Num="132_2">
  <ArticleCaption>（テスト条）</ArticleCaption>
  <ArticleTitle>第百三十二条の二</ArticleTitle>
  <Paragraph Num="1">
    <ParagraphNum/>
    <ParagraphSentence>
      <Sentence Function="main">次に掲げる法人は、これを行うものとする。</Sentence>
      <Sentence Function="proviso">ただし、この限りでない。</Sentence>
    </ParagraphSentence>
    <Item Num="1">
      <ItemTitle>一</ItemTitle>
      <ItemSentence>
        <Column><Sentence>国内</Sentence></Column>
        <Column><Sentence>この法律の施行地をいう。</Sentence></Column>
      </ItemSentence>
    </Item>
    <Item Num="2">
      <ItemTitle>二</ItemTitle>
      <ItemSentence><Sentence>次に掲げるもの</Sentence></ItemSentence>
      <Subitem1 Num="1">
        <Subitem1Title>イ</Subitem1Title>
        <Subitem1Sentence><Sentence>イの本文</Sentence></Subitem1Sentence>
        <Subitem2 Num="1">
          <Subitem2Title>（１）</Subitem2Title>
          <Subitem2Sentence><Sentence>（１）の本文</Sentence></Subitem2Sentence>
        </Subitem2>
      </Subitem1>
    </Item>
  </Paragraph>
  <Paragraph Num="2">
    <ParagraphNum>２</ParagraphNum>
    <ParagraphSentence><Sentence>第二項の本文である。</Sentence></ParagraphSentence>
    <TableStruct>
      <TableStructTitle>別表</TableStructTitle>
      <Table>
        <TableRow>
          <TableColumn><Sentence>区分</Sentence></TableColumn>
          <TableColumn><Sentence>税率</Sentence></TableColumn>
        </TableRow>
        <TableRow>
          <TableColumn><Sentence>甲</Sentence></TableColumn>
          <TableColumn><Sentence>十分の一</Sentence></TableColumn>
        </TableRow>
      </Table>
    </TableStruct>
  </Paragraph>
  <SupplNote>（罰則　第百十九条）</SupplNote>
</Article>"""


def _article():
    return ET.fromstring(ARTICLE_XML)


def _xml_body_norm(article) -> str:
    """XML の条文本文 (見出し・項番号ラベル・キャプションを除く) の正規化テキスト."""
    parts: list[str] = []
    for para in article.findall("Paragraph"):
        for child in para:
            if child.tag in ("ParagraphNum", "ParagraphCaption"):
                continue
            parts.append("".join(child.itertext()))
    for child in article:
        if child.tag not in ("ArticleTitle", "ArticleCaption", "Paragraph"):
            parts.append("".join(child.itertext()))
    return norm("".join(parts))


def test_generated_body_equals_xml_after_whitespace_collapse():
    """★最重要: 空白畳み込み後、生成本文 == XML 本文 (GFM 区切り行は描画用ゆえ除外)."""
    body, _fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    kept: list[str] = []
    for ln in body.splitlines():
        stripped = ln.strip()
        if ln.startswith("### "):
            continue  # 項見出し (構造。XML の ParagraphNum に対応)
        if stripped and set(stripped) <= {"|", "-", " "}:
            continue  # GFM 区切り行 (描画用。hash からも除外される)
        kept.append(ln.replace("|", ""))  # 表の書式パイプは構造
    assert norm("\n".join(kept)) == _xml_body_norm(_article())


def test_items_and_subitems_are_present():
    body, _fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    assert "一　国内　この法律の施行地をいう。" in body  # Column は全角スペース区切り
    assert "\n二　次に掲げるもの" in body
    assert "\n　イ　イの本文" in body  # 細別 = 全角スペース 1 個の段付け
    assert "\n　　（１）　（１）の本文" in body  # Subitem2 = 2 個


def test_no_xml_pretty_print_whitespace_in_body():
    """Column 構造で XML の整形用改行・インデントが本文に漏れないこと."""
    body, _fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    for line in body.splitlines():
        assert "  " not in line.strip(), f"半角連続スペースが混入: {line!r}"


def test_no_internal_markers_in_body():
    body, _fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    assert "<!--" not in body


def test_table_is_emitted_in_document_order_with_gfm_separator():
    body, _fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    lines = body.splitlines()
    assert "| 区分 | 税率 |" in lines
    assert "| --- | --- |" in lines
    # 表は第2項 (第二項の本文である。) の後に来る
    assert lines.index("| 区分 | 税率 |") > lines.index("第二項の本文である。")


def test_supplnote_is_kept():
    body, _fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    assert "（罰則　第百十九条）" in body


def test_branch_article_heading_uses_article_title():
    body, _fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    assert "### 第百三十二条の二第一項" in body
    assert "### 第百三十二条の二第二項" in body


def test_kou_segments_generated_and_are_substrings_of_body():
    """G0-c: 各 segment の text は本文の部分列 (空白畳み込み後)."""
    body, fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    body_n = norm(body)
    kou = [s for p in fm for s in p["segments"] if s["type"] == "kou"]
    assert [s["id"] for s in kou] == [
        "test-art-132-2-p1-kou-1",
        "test-art-132-2-p1-kou-2",
    ]
    for p in fm:
        for s in p["segments"]:
            assert norm(s["text"]) in body_n, f"segment not a substring of body: {s['id']}"


RANGE_ITEM_XML = """<Article Num="2">
  <ArticleTitle>第二条</ArticleTitle>
  <Paragraph Num="1">
    <ParagraphSentence><Sentence>次に掲げるものとする。</Sentence></ParagraphSentence>
    <Item Num="1">
      <ItemTitle>一</ItemTitle>
      <ItemSentence><Sentence>第一号の本文</Sentence></ItemSentence>
    </Item>
    <Item Num="1_2">
      <ItemTitle>一の二</ItemTitle>
      <ItemSentence><Sentence>第一号の二の本文</Sentence></ItemSentence>
    </Item>
    <Item Num="3:4">
      <ItemTitle>三及び四</ItemTitle>
      <ItemSentence><Sentence>削除</Sentence></ItemSentence>
    </Item>
  </Paragraph>
</Article>"""


def test_range_and_branch_items_are_not_dropped():
    """範囲号 (Num="3:4") と枝番号 (Num="1_2") が chunk 化されること.

    旧実装は int("3:4") が ValueError -> 無言スキップで、md には「三及び四　削除」が
    出るのに chunk が無い状態だった (G0-b 不一致)。枝番号は id が -kou-1 に潰れて
    第一号と衝突していた。
    """
    body, fm, _w = rb.build_article_md(ET.fromstring(RANGE_ITEM_XML), "x-art-2")
    kou = [s for p in fm for s in p["segments"] if s["type"] == "kou"]
    ids = [s["id"] for s in kou]
    assert ids == ["x-art-2-p1-kou-1", "x-art-2-p1-kou-1-2", "x-art-2-p1-kou-3-4"]
    assert len(set(ids)) == len(ids)  # id 衝突なし
    assert [s["item_number"] for s in kou] == [1, 1, 3]
    assert "三及び四　削除" in body
    body_n = norm(body)
    for s in kou:
        assert norm(s["text"]) in body_n


RUBY_XML = """<Article Num="1">
  <ArticleTitle>第一条</ArticleTitle>
  <Paragraph Num="1">
    <ParagraphSentence><Sentence>価額を<Ruby>按<Rt>あん</Rt></Ruby>分した額とする。</Sentence></ParagraphSentence>
  </Paragraph>
</Article>"""


def test_ruby_reading_is_not_written_into_the_body():
    """ルビの読み (<Rt>) は注記であって本文ではない.

    取り込むと法令本文が「按あん分」に改変される (原文非改変の違反)。旧 corpus に
    実在した汚染で、生成器と検証器が同じ抽出器を共有していたため G0-a では見えず、
    Rt を除外していた table_core との食い違い (G0-c) で初めて露見した。
    """
    body, fm, _w = rb.build_article_md(ET.fromstring(RUBY_XML), "x-art-1")
    assert "按分した額" in body
    assert "あん" not in body
    assert "あん" not in fm[0]["segments"][0]["text"]


def test_h1_caption_is_rebuilt_without_ruby():
    """H1 の見出し語 (ArticleCaption 由来) にもルビが混入していた.

    本文だけ直して H1 を残すと、同じ条の中で「瑕疵」と「瑕疵かし」が併存する。
    """
    art = ET.fromstring(
        "<Article Num='101'><ArticleCaption>（代理行為の<Ruby>瑕疵<Rt>かし</Rt></Ruby>）"
        "</ArticleCaption><ArticleTitle>第百一条</ArticleTitle>"
        "<Paragraph Num='1'><ParagraphSentence><Sentence>本文。</Sentence>"
        "</ParagraphSentence></Paragraph></Article>"
    )
    h1 = rb.build_h1(art, "民法", "101")
    assert h1 == "# 民法 第101条(（代理行為の瑕疵）)"
    assert "かし" not in h1


def test_parent_section_names_are_rebuilt_without_ruby():
    """節名 (parent_section) にもルビが混入していた (「乗車、積載及び牽けん引」).

    parent_section は chunk にも複製されるので、本文だけ直しても索引側に汚染が残る。
    構造スタックの抽出は parse-egov._walk_articles を再利用している。
    """
    law = ET.fromstring(
        "<Law><LawBody><MainProvision>"
        "<Section Num='11'><SectionTitle>第十一節　乗車、積載及び"
        "<Ruby>牽<Rt>けん</Rt></Ruby>引</SectionTitle>"
        "<Article Num='59'><ArticleTitle>第五十九条</ArticleTitle>"
        "<Paragraph Num='1'><ParagraphSentence><Sentence>本文。</Sentence>"
        "</ParagraphSentence></Paragraph></Article></Section>"
        "</MainProvision></LawBody></Law>"
    )
    main = law.find("LawBody").find("MainProvision")
    articles = rb._parse_egov._walk_articles(main, [])
    ps = articles[0]["parent_section"]
    assert ps["setsu_name_ja"] == "第十一節　乗車、積載及び牽引"
    assert "けん" not in ps["setsu_name_ja"]


def test_both_xml_text_extractors_agree():
    """本文抽出器が 2 系統ある以上、両者が一致することを固定する.

    Why: `parse-egov.extract_all_text` (正本 md の生成 + G0 ゲートの ground truth) と
    `table_core.get_text_recursive` (表・chunk 系) は別実装。**生成器と検証器が同じ
    抽出器を共有していると、抽出器のバグは検証をすり抜ける** (ルビ混入 = 実際に
    そうなった)。両者の食い違いを CI で検出できるようにしておく。
    """
    from table_core import get_text_recursive

    el = ET.fromstring("<Sentence>価額を<Ruby>按<Rt>あん</Rt></Ruby>分した額とする。</Sentence>")
    assert rb.extract_all_text(el) == get_text_recursive(el) == "価額を按分した額とする。"


def test_has_items_and_has_proviso_come_from_xml():
    _b, fm, _w = rb.build_article_md(_article(), "test-art-132-2")
    assert fm[0]["has_items"] is True
    assert fm[0]["has_proviso"] is True
    assert fm[1]["has_items"] is False
    assert fm[1]["has_proviso"] is False


EXISTING_MD = """---
law_id: 340AC0000000034
article_number: 132-2
article_id: houjin-zei-hou-art-132-2
paragraphs:
- number: 1
  has_proviso: false
  has_items: false
  is_added_by_amendment: false
  segments: []
cases:
- case_id: scj-1969-12-04
  court: 最高裁判所
amendments:
- date: '2022-04-01'
  law_num: 令和二年法律第八号
tags:
- phase1-tax
---

# 法人税法 第132-2条(（テスト条）)

## 原文 (日本語)

### 第百三十二条の二

<!-- segment: simple id: old -->
古い本文。

## 判例リンク (Case Law)

- 既存の判例リンク
"""


def test_rewrite_md_preserves_curated_frontmatter_and_trailing_sections():
    """★ parse-egov 再実行なら消える curated データが保存されること."""
    body, fm_paragraphs, _w = rb.build_article_md(_article(), "houjin-zei-hou-art-132-2")
    out = rb.rewrite_md(EXISTING_MD, body, fm_paragraphs)

    fm = yaml.safe_load(re.match(r"^---\n(.*?)\n---\n", out, re.DOTALL).group(1))
    assert fm["cases"][0]["case_id"] == "scj-1969-12-04"  # 判例リンク保存
    assert fm["amendments"][0]["law_num"] == "令和二年法律第八号"  # 改正履歴保存
    assert fm["law_id"] == "340AC0000000034"
    assert fm["paragraphs"][0]["has_items"] is True  # paragraphs は差し替わる

    assert "## 判例リンク (Case Law)" in out  # 後続セクション保存
    assert "- 既存の判例リンク" in out
    assert "# 法人税法 第132-2条(（テスト条）)" in out  # H1 保存
    assert "<!-- segment:" not in out  # マーカーは消える
    assert "古い本文。" not in out  # 本文は差し替わる
    assert "一　国内　この法律の施行地をいう。" in out


def test_rewrite_md_fails_loud_without_ja_section():
    body, fm_paragraphs, _w = rb.build_article_md(_article(), "x-art-1")
    bad = "---\nlaw_id: X\n---\n\n# 見出し\n\n## English Translation\n\nfoo\n"
    try:
        rb.rewrite_md(bad, body, fm_paragraphs)
    except ValueError as e:
        assert "原文" in str(e)
    else:
        raise AssertionError("原文セクションが無い md は fail loud すべき")

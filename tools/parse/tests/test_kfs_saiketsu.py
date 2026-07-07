"""test_kfs_saiketsu.py -- parse-kfs-saiketsu.py の hermetic unit tests.

Why hermetic: 実 KFS fetch なしで parser ロジック (和暦変換 / case_id 生成 / 正式名マッパー /
corpus 実在ガード / 要旨 byte 忠実 / RulingReference IR 適合) を検証する。HTML fixture は本
ファイル内に UTF-8 で埋め込み (charset meta を付けて _detect_charset に utf-8 を返させる)、corpus
実在集合は module-global _ARTICLE_CORPUS を注入して data/v0.2 非依存にする (test_taxanswer_related
と同型)。フルコーパスの expected ロックは佐藤 review 後 (§7) ゆえ本 test は構造/ロジック契約のみ。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

_PARSER_PATH = _REPO_ROOT / "tools" / "parse" / "parse-kfs-saiketsu.py"

# corpus 実在ガードに注入する最小集合 (data/v0.2 非依存で hermetic 化)。
_MIN_CORPUS = {"houjin-zei-hou-shikkourei-art-54", "chihou-zei-hou-art-343"}


def _load_parser():
    """ハイフン名モジュール parse-kfs-saiketsu.py を importlib で読み、corpus を注入して返す。"""
    spec = importlib.util.spec_from_file_location("parse_kfs_saiketsu", _PARSER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._ARTICLE_CORPUS = set(_MIN_CORPUS)
    return mod


# ---------------------------------------------------------------------------
# HTML fixture (実 KFS リーフの markup 構造を最小再現)
# ---------------------------------------------------------------------------

_FIXTURE_HTML = """<html><head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"></head><body>
<h2 class="likeH3" id="y01"><span>鉄道の高架下を賃借するために支払った権利金は繰延資産ではない事例</span></h2>
<div class="article">
<p class="article_point">裁決事例集 No.4 - 14頁</p>
<p>　請求人は鉄道の高架下の賃借は建物の賃借であると主張するが、繰延資産としての償却は認められない。</p>
<p>昭和47年5月12日裁決</p>
</div>
<h2 class="likeH3" id="a88"><span>不動産の取得に際して支払った固定資産税等相当額は取得価額に算入すべき事例</span></h2>
<div class="article">
<p class="article_point">▼ <a href="../../JP/88/09/index.html">平成24年7月5日裁決</a></p>
<p class="marginT1em">《ポイント》<br />　本事例はポイント本文である。</p>
<p class="marginT1em">《要旨》<br />　請求人は主張するが、当該相当額は取得価額に算入すべきである。</p>
<p class="marginT1em">《参照条文等》<br />　法人税法施行令第54条第1項<br />　法人税基本通達7-3-16の2<br />　地方税法第343条</p>
<p class="marginT1em">《参考判決・裁決》<br />　平成24年3月13日裁決（裁決事例集No.86）</p>
</div>
<h2 class="likeH3" id="a99"><span>存在しない条を参照する裁決 (corpus_gap テスト)</span></h2>
<div class="article">
<p class="article_point">▼ <a href="../../JP/99/01/index.html">令和2年1月15日裁決</a></p>
<p class="marginT1em">《要旨》<br />　テスト要旨本文。</p>
<p class="marginT1em">《参照条文等》<br />　法人税法施行令第9999条</p>
</div>
</body></html>"""


@pytest.fixture()
def entries():
    mod = _load_parser()
    return mod, mod.parse_leaf(
        _FIXTURE_HTML.encode("utf-8"), "0204040000", "法人税", "MP/03/0204040000"
    )


# ---------------------------------------------------------------------------
# 和暦 -> 西暦 (§4・境界)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("era", "year", "month", "day", "expected"),
    [
        ("昭和", "47", 5, 12, "1972-05-12"),  # 昭和47 = 1972
        ("平成", "24", 7, 5, "2012-07-05"),  # 平成24 = 2012
        ("令和", "2", 1, 15, "2020-01-15"),  # 令和2 = 2020
        ("令和", "元", 5, 1, "2019-05-01"),  # 令和元 = 2019
        ("平成", "元", 1, 8, "1989-01-08"),  # 平成元 = 1989
        ("昭和", "元", 12, 25, "1926-12-25"),  # 昭和元 = 1926
    ],
)
def test_wareki_to_iso(era, year, month, day, expected):
    mod = _load_parser()
    assert mod.wareki_to_iso(era, year, month, day) == expected


def test_wareki_unknown_era_raises():
    mod = _load_parser()
    with pytest.raises(ValueError):
        mod.wareki_to_iso("大正", "5", 1, 1)


# ---------------------------------------------------------------------------
# エントリ抽出・case_id (§5)
# ---------------------------------------------------------------------------


def test_three_entries_parsed(entries):
    _mod, es = entries
    assert len(es) == 3


def test_old_entry_case_id_from_no_and_page(entries):
    """permalink なしの古い裁決: case_id は No + 頁 (§5)。metadata のみ (link なし)。"""
    _mod, es = entries
    e = es[0]
    assert e["case_id"] == "ntt-1972-05-12-j4-14"
    assert e["decision_date"] == "1972-05-12"
    assert e["saiketsu_ref"] == "No.4-14頁"
    assert e["_has_sanshou"] is False
    assert e["_links"] == []
    # url は permalink なしゆえリーフ URL + アンカー (h2 id)。カテゴリ 03 は issue_code 由来でない。
    assert e["url"].endswith("/MP/03/0204040000.html#y01")


def test_new_entry_case_id_from_permalink(entries):
    """permalink ありの新しい裁決: case_id は 巻号 + 通番 (頁でなく通番)。"""
    _mod, es = entries
    e = es[1]
    assert e["case_id"] == "ntt-2012-07-05-j88-9"
    assert e["decision_date"] == "2012-07-05"
    assert e["saiketsu_ref"] is None  # 88/92 は 裁決事例集 No 非掲載
    assert e["url"] == "https://www.kfs.go.jp/service/JP/88/09/index.html"


def test_decision_date_ignores_sanko_hanketsu(entries):
    """《参考判決・裁決》の別日付 (平成24年3月13日) を裁決日に誤採用しない。"""
    _mod, es = entries
    assert es[1]["decision_date"] == "2012-07-05"  # article_point の 7月5日、3月13日でない


# ---------------------------------------------------------------------------
# 参照条文解決: 正式名マッパー + 通達→tags + 地方税法 link + corpus_gap
# ---------------------------------------------------------------------------


def test_sanshou_links_articles_and_paragraph(entries):
    """法人税法施行令第54条第1項 -> art-54 (relevant_paragraph=1)、地方税法第343条 -> art-343。"""
    _mod, es = entries
    e = es[1]
    assert e["_has_sanshou"] is True
    by_id = {link["article_id"]: link for link in e["_links"]}
    assert by_id["houjin-zei-hou-shikkourei-art-54"]["relevant_paragraph"] == 1
    assert by_id["chihou-zei-hou-art-343"]["relevant_paragraph"] is None
    assert len(e["_links"]) == 2  # 施行令54 + 地方税法343 (通達は link せず)


def test_tsutatsu_goes_to_tags_not_links(entries):
    """D1: 法人税基本通達は link せず tags に記録 (参照通達:...)。"""
    _mod, es = entries
    e = es[1]
    assert e["tags"] == ["参照通達:法人税基本通達7-3-16の2"]
    assert all("通達" not in link["article_id"] for link in e["_links"])


def test_corpus_gap_not_linked(entries):
    """存在しない条 (施行令第9999条) は link せず corpus_gap で記録 (偽リンク0)。"""
    _mod, es = entries
    e = es[2]
    assert e["_links"] == []
    reasons = [u["reason"] for u in e["_unlinked"]]
    assert "corpus_gap" in reasons


def test_resolve_unresolved_law_recorded():
    """正式名マッパーに無い法令は偽リンクせず unresolved_law で記録。"""
    mod = _load_parser()
    res = mod.resolve_sanshou_jouken(["消費税法第30条"])
    assert res["links"] == []
    assert res["unlinked"] == [{"raw": "消費税法第30条", "reason": "unresolved_law"}]


def test_resolve_longest_prefix_first():
    """法人税法施行令 が 法人税法 に誤マッチしない (longest-first)。"""
    mod = _load_parser()
    res = mod.resolve_sanshou_jouken(["法人税法施行令第54条"])
    assert res["links"][0]["law_abbrev"] == "houjin-zei-hou-shikkourei"
    assert res["links"][0]["article_id"] == "houjin-zei-hou-shikkourei-art-54"


# ---------------------------------------------------------------------------
# 要旨 byte 忠実 (§8) + RulingReference IR 適合
# ---------------------------------------------------------------------------


def test_summary_is_youshi_not_point(entries):
    """summary_ja は 《要旨》本文 (《ポイント》を含めない)。"""
    _mod, es = entries
    s = es[1]["summary_ja"]
    assert s == "請求人は主張するが、当該相当額は取得価額に算入すべきである。"
    assert "ポイント" not in s


def test_old_entry_summary_excludes_date_line(entries):
    """古い裁決の summary_ja は本文のみ (末尾の裁決日行を含めない)。"""
    _mod, es = entries
    s = es[0]["summary_ja"]
    assert "繰延資産としての償却は認められない。" in s
    assert "裁決" not in s  # 昭和47年5月12日裁決 の行は除外


def test_all_entries_validate_as_ruling_reference(entries):
    """全裁決が RulingReference (case_type=ruling・ntt- prefix) として IR valid。"""
    _mod, es = entries
    from juricode_shared import RulingReference

    for e in es:
        payload = {k: v for k, v in e.items() if not k.startswith("_")}
        obj = RulingReference.model_validate(payload)
        assert obj.case_type == "ruling"
        assert obj.case_id.startswith("ntt-")

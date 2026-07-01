"""test_sozoku_taxanswer_corpus.py -- 相続・贈与タックスアンサー corpus fixture のゲート (FU-527).

Why this test exists:
    相続・贈与タックスアンサー (URL path /taxanswer/sozoku/・相続税 4100 番台 + 贈与税
    4400/4600 番台) の committed 実体は build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/sozoku-taxanswer.corpus.chunks.baseline.jsonl`
    (hojin/souzoku/hyoka と同じ場所・同じ規約)。本テストは佐藤ロック値 (全 52 件・枝番 0・
    links 154/57/133/161・content 画像 33・version_date None 0・body 211..8738) を fixture に
    対して pin し、cache がある push 前ローカルでは parser が fixture を byte 再現することを
    検証する。

    母集団 (2026-07-01 実測・佐藤ロック):
        code/index.htm の /taxanswer/sozoku/ href = 52 codes
        soft-404 0 / redirect 0 / dup 0 -> corpus 52 chunks (枝番なし)

    FU-527 の中核回帰を pin する:
    - **相続バーティカルのリンク**: 相基通 (souzoku-kihon-tsutatsu 46) と 評基通
      (zaisan-hyoka-kihon-tsutatsu 11) が related_directives として linked であること。
      これは taxanswer parser を法人税ハードコードから多法令化した本丸の証跡。相基通/評基通
      の通達番号は衝突し得る (例 16-1) ため、nested corpus (law_abbrev キー) で分離照合する。
    - **越境参照の非リンク記録**: 措/所/通/民/郵政 等の他法令参照は corpus_unregistered として
      unlinked に記録 (false link でも silent drop でもない)。個別通達番号 (直評/課評) は
      nta_notice。amendment 附則は kaisei_funsoku。
    - **偽リンクゼロ**: related_articles の law_abbrev は souzoku 系のみ・article_id は必ず
      対応略称で前置される (相法/相令/相規 のみ。裸 "相" prefix を持たない)。
    - **trailer 非漏洩**: 根拠法令等 以降の 関連コード/関連リンク/QAリンク が body に漏れない
      (mega-<p> 異形ページ 4103/4168 等でも terminated latch + wrapper skip で除外)。

    **落ちたら直すのはパーサ/キャッシュであって fixture/期待値ではない** (source-locked)。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-taxanswer.py"
_FIXTURE = _THIS.parent / "fixtures" / "sozoku-taxanswer.corpus.chunks.baseline.jsonl"
_SOZOKU_CACHE = _REPO_ROOT / "cache" / "taxanswer" / "sozoku"

# LOCKED 確定値 (実パーサ dry-run + 母集団突合で確定・佐藤ロック 2026-07-01・改変は明示承認必須)。
#
# 2026-07-01 FU-529 再ロック (佐藤明示承認): 所得税バーティカル活性化により、相続・贈与
# タックスアンサーが引用する 所法系/所基通 参照が unlinked->linked に昇格 (相続税と所得税の
# 二重課税調整文脈)。related_articles 154->157 (+3)・related_directives 57->61 (+4)・
# unlinked 161->154 (-7)。本文・title・qa・images・version は完全不変。Cowork 独立カウント
# (baseline に眠る明示 所-prefix unlinked = 5ref/3chunk) と一致。
EXPECTED_TOTAL = 52  # dedup 後のユニーク code 数 (母集団 52 - soft-404 0)
EXPECTED_BRANCHED: frozenset[str] = frozenset()  # 枝番コードなし
EXPECTED_ARTICLES = 157  # related_articles 総数 (FU-529: 154->157, 所法系昇格)
EXPECTED_DIRECTIVES = 61  # related_directives 総数 (FU-529: 57->61, 所基通昇格)
EXPECTED_QA = 133  # related_qa 総数 (href 由来・body 非依存)
EXPECTED_UNLINKED = 154  # unlinked_refs 総数 (FU-529: 161->154, 所法系 unlinked->linked 昇格)
EXPECTED_IMAGES = 33  # content 画像 (計算表・フローチャート) 総数
EXPECTED_IMAGE_PAGES = 13  # content 画像を持つページ数
EXPECTED_VERSION_NONE = 0  # version_date が None のページ数 (捏造禁止 = パース不能なら None)
BODY_MIN, BODY_MAX = 211, 8738  # body 文字数の最小/最大
EXPECTED_CACHE_HTM = 52  # 取得済 htm 数 (soft-404 0)

# 相続バーティカルの article/directive リンク内訳 (多法令化の証跡・ロック)。
# FU-529: 所得税 cross-vertical (所法/所令 -> shotoku-*・所基通 -> shotoku-kihon-tsutatsu) を追加。
EXPECTED_ARTICLE_ABBREVS = {
    "souzoku-zei-hou": 129,
    "souzoku-zei-hou-shikkourei": 18,
    "souzoku-zei-hou-shikoukisoku": 7,
    "shotoku-zei-hou": 2,
    "shotoku-zei-hou-shikkourei": 1,
}
EXPECTED_DIRECTIVE_ABBREVS = {
    "souzoku-kihon-tsutatsu": 46,
    "zaisan-hyoka-kihon-tsutatsu": 11,
    "shotoku-kihon-tsutatsu": 4,
}
_HOST = "https://www.nta.go.jp/"


def _records() -> list[dict]:
    return [
        json.loads(line)
        for line in _FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _images(body: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body)


def _import_parser():
    spec = importlib.util.spec_from_file_location("parse_nta_taxanswer", _PARSER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ===========================================================
# fixture 不変条件 (CI-safe: committed fixture のみ参照)
# ===========================================================


def test_fixture_exists() -> None:
    assert _FIXTURE.exists(), f"corpus fixture 不在: {_FIXTURE}"


def test_chunk_count_locked() -> None:
    assert len(_records()) == EXPECTED_TOTAL


def test_code_unique() -> None:
    codes = [r["code"] for r in _records()]
    assert len(codes) == len(set(codes)), "code に重複 (dedup 漏れ)"


def test_no_branched_codes() -> None:
    """sozoku は枝番コードなし (母集団実測)。"""
    branched = {r["code"] for r in _records() if "-" in r["code"]}
    assert branched == EXPECTED_BRANCHED, f"想定外の枝番: {sorted(branched)}"


def test_id_equals_code_prefixed() -> None:
    """id は 'sozoku-taxanswer-<code>' 形式で code と整合。

    Why: record_id は FU-527 で law_abbrev をパラメタ化した (旧 'hojin-taxanswer-' ハード
    コードでは sozoku で誤 id を生む silent bug だった)。
    """
    for r in _records():
        assert r["id"] == f"sozoku-taxanswer-{r['code']}", r["id"]


def test_link_totals_locked() -> None:
    """リンク総数 (related_articles/directives/qa/unlinked) がロック値と一致。"""
    recs = _records()
    assert sum(len(r["related_articles"]) for r in recs) == EXPECTED_ARTICLES
    assert sum(len(r["related_directives"]) for r in recs) == EXPECTED_DIRECTIVES
    assert sum(len(r["related_qa"]) for r in recs) == EXPECTED_QA
    assert sum(len(r["unlinked_refs"]) for r in recs) == EXPECTED_UNLINKED


def test_inheritance_vertical_directives_linked() -> None:
    """相続バーティカルの通達リンク (多法令化の本丸証跡)。

    相基通 -> souzoku-kihon-tsutatsu (46)・評基通 -> zaisan-hyoka-kihon-tsutatsu (11) が
    related_directives として linked であること。番号衝突する 2 通達を nested corpus で
    分離照合できている証拠。
    """
    recs = _records()
    counts = Counter(d["law_abbrev"] for r in recs for d in r["related_directives"])
    assert dict(counts) == EXPECTED_DIRECTIVE_ABBREVS, f"通達リンク内訳が不一致: {dict(counts)}"


def test_article_link_breakdown_locked() -> None:
    """条文リンク内訳が相続税法ファミリのみ (相法/相令/相規) でロック値一致。"""
    recs = _records()
    counts = Counter(a["law_abbrev"] for r in recs for a in r["related_articles"])
    assert dict(counts) == EXPECTED_ARTICLE_ABBREVS, f"条文リンク内訳が不一致: {dict(counts)}"


def test_directive_ids_prefixed_by_law_abbrev() -> None:
    """全 directive_id が対応 law_abbrev で前置される (相基通/評基通 の取り違えゼロ)。"""
    for r in _records():
        for d in r["related_directives"]:
            assert d["directive_id"].startswith(d["law_abbrev"]), d


def test_version_date_none_count() -> None:
    """version_date が None のページ数 (パース不能のみ None・実行日等の捏造禁止)。"""
    none_count = sum(1 for r in _records() if r["version_date"] is None)
    assert none_count == EXPECTED_VERSION_NONE


def test_content_images_locked() -> None:
    """content 画像が 33 枚 (13 ページ)・全て絶対 URL・/template/ ナビは drop。"""
    recs = _records()
    all_imgs = [u for r in recs for u in _images(r["body"])]
    assert len(all_imgs) == EXPECTED_IMAGES, f"content 画像数: {len(all_imgs)}"
    assert sum(1 for r in recs if _images(r["body"])) == EXPECTED_IMAGE_PAGES
    assert all(u.startswith(_HOST) for u in all_imgs), "相対 URL の画像がある"
    assert not any("/template/" in u for u in all_imgs), "ナビ/装飾 (/template/) 画像が混入"


def test_body_length_bounds_locked() -> None:
    """body 文字数の最小/最大がロック値 (スコープ拡張後)。"""
    lengths = [len(r["body"]) for r in _records()]
    assert min(lengths) == BODY_MIN, f"body 最小長: {min(lengths)}"
    assert max(lengths) == BODY_MAX, f"body 最大長: {max(lengths)}"


def test_no_nav_trailer_leak() -> None:
    """根拠法令等 以降の trailer (関連コード/関連リンク/QAリンク/お問い合わせ/アンケート) が
    body に漏れない (mega-<p> 異形ページ 4103/4168 でも wrapper skip + terminated で除外)。

    Why: mega-<p> が section 見出しを入れ子で内包する異形構造だと、get_text が 根拠法令等
    以降まで丸ごと吐いて trailer を本文に流入させる。trailer 由来の署名で回帰を pin。
    """
    markers = ("QAリンク", "お問い合わせ先", "アンケ-トへ", "根拠法令等")
    leaked = [r["code"] for r in _records() if any(m in r["body"] for m in markers)]
    assert leaked == [], f"trailer が body に漏れている: {leaked}"


def test_no_related_code_list_leak() -> None:
    """関連コードのリスト項目署名 ('- NNNN　') が body に漏れない。"""
    leaked = [r["code"] for r in _records() if re.search(r"(?m)^- \d{4}　", r["body"])]
    assert leaked == [], f"関連コードが body に漏れている: {leaked[:5]}"


def test_articles_not_false_linked() -> None:
    """related_articles の法略称が相続税法ファミリのみ・article_id が law_abbrev で前置される。

    Why: LAW_PREFIX_MAP は裸 "相" を持たず 相法/相令/相規 の specific prefix のみゆえ、
    他法令が相続税法へ偽リンクしない。全 article_id が対応略称で始まること + 数字欄に
    非 ASCII (日本語 prefix の漏れ) が無いことを機械検証。
    """
    allowed = set(EXPECTED_ARTICLE_ABBREVS)
    bad = [
        (r["code"], a["law_abbrev"], a["article_id"])
        for r in _records()
        for a in r["related_articles"]
        if a["law_abbrev"] not in allowed
        or not a["article_id"].startswith(a["law_abbrev"])
        or re.search(r"[^\x00-\x7f]", a["article_id"])
    ]
    assert bad == [], f"偽リンク疑い: {bad[:5]}"


def test_all_source_urls_under_sozoku() -> None:
    """全 source_url が NTA taxanswer/sozoku パスを指す (URL 一次確認済)。"""
    for r in _records():
        assert f"/taxanswer/sozoku/{r['code']}.htm" in r["source_url"], r["source_url"]


def test_license_and_attribution() -> None:
    """全レコードが NTA タックスアンサーのライセンス/帰属を持つ (PDL1.0 = CC BY 互換)。"""
    for r in _records():
        assert r["license"] == "cc-by-jp-nta", r["license"]
        assert r["attribution"] == "国税庁タックスアンサー", r["attribution"]


# ===========================================================
# byte 再現 + htm 数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _SOZOKU_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/sozoku/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_cache_htm_count() -> None:
    """取得済 htm が 52 (soft-404 0・NTA 目次の増減検知)。"""
    htm = list(_SOZOKU_CACHE.glob("*.htm"))
    assert len(htm) == EXPECTED_CACHE_HTM, f"htm 数が {EXPECTED_CACHE_HTM} でない: {len(htm)}"


@pytest.mark.skipif(
    not _SOZOKU_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/sozoku/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を byte 再現する (決定性 + 完全性)。

    Note: 通達リンク解決は build/chunks の souzoku/hyoka tsutatsu corpus に依存するため、
    build/chunks 不在時は directives が全 unlink になり byte 不一致になり得る。よって
    build/chunks の相続通達 corpus がある push 前ローカルでのみ意味を持つ (cache と併せ skipif)。
    """
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        [
            "--cache-dir",
            str(_SOZOKU_CACHE),
            "--tax-category",
            "sozoku",
            "--law-abbrev",
            "sozoku-taxanswer",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    produced = out_dir / "sozoku-taxanswer.taxanswer.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュの出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

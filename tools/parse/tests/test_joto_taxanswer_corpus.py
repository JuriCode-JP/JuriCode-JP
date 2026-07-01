"""test_joto_taxanswer_corpus.py -- 譲渡所得タックスアンサー corpus fixture のゲート (FU-531).

Why this test exists:
    譲渡所得タックスアンサー (URL path /taxanswer/joto/・3000 番台) の committed 実体は
    build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/joto-taxanswer.corpus.chunks.baseline.jsonl`
    (hojin/sozoku/shohi/gensen/shotoku と同じ場所・同じ規約)。本テストは佐藤ロック値 (全 71 件・
    枝番なし・links 81/40/181/239・content 画像 26/18・version_date None 0・body 156..5761) を
    fixture に対して pin し、cache がある push 前ローカルでは parser が fixture を byte 再現する
    ことを検証する。

    母集団 (2026-07-02 実測・佐藤ロック):
        code/index.htm の /taxanswer/joto/ href = 71 codes
        soft-404 0 / redirect 0 / dup 0 -> corpus 71 chunks (枝番なし)

    FU-531 は所得税バーティカル (FU-529/530 で活性化済) 上の純 additive 取込 (parser 無変更):
    - **所得税ファミリのリンク**: 所法/所令 (shotoku-zei-hou 系 60/18) が article、所基通
      (shotoku-kihon-tsutatsu 40) が directive として linked。譲渡所得タックスアンサーの参照が
      所得税法・同施行令・所得税基本通達 (FU-523) corpus へ実解決する証跡。
    - **cross-vertical リンク**: 譲渡所得は消費税と相互参照するため消法/消令 (shouhi-zei-hou 2 /
      shouhi-zei-hou-shikkourei 1) へ link。越境ではなく実在 corpus への正当な相互参照 (明示 prefix)。
    - **越境偽リンクゼロ**: 所得税バーティカル外の別法令 (措法系=順序5 予約 UNREG /震災特例法/財形法/
      復興財確法/実施特例法系/耐省令/地方税法/条約・協定/旧法令 等) と 告示 は related_articles に
      混入せず unlinked に記録 (corpus_unregistered)。譲渡は措置法特例参照が多く unlinked が大きい
      (順序5 措置法取込で link 化予定)。個別通達 (直/課・中黒形含む) は nta_notice、amendment 附則は
      kaisei_funsoku、展開不能なレンジは range_not_expandable。
    - **config-light additive**: 本 FU は parse-nta-taxanswer.py を 1 バイトも変更しない
      (fetcher に joto Category を追加するのみ)。既存5カテゴリ (hojin/sozoku/shohi/gensen/shotoku)
      のパース出力は構造上 byte 不変 (それぞれの corpus テストで実証)。probe (71 htm 全走) で未知
      越境 prefix ゼロ・未知 H2 終端ゼロを確認済ゆえ UNREG/STOP の追加も不要。

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
_FIXTURE = _THIS.parent / "fixtures" / "joto-taxanswer.corpus.chunks.baseline.jsonl"
_JOTO_CACHE = _REPO_ROOT / "cache" / "taxanswer" / "joto"

# LOCKED 確定値 (実パーサ dry-run + 母集団突合で確定・佐藤ロック 2026-07-02・改変は明示承認必須)。
EXPECTED_TOTAL = 71  # dedup 後のユニーク code 数 (母集団 71 - soft-404 0)
EXPECTED_ARTICLES = 81  # related_articles 総数
EXPECTED_DIRECTIVES = 40  # related_directives 総数
EXPECTED_QA = 181  # related_qa 総数 (href 由来・body 非依存)
EXPECTED_UNLINKED = 239  # unlinked_refs 総数 (措法系特例参照が主・順序5 で link 化予定)
EXPECTED_IMAGES = 26  # content 画像 (計算表・フローチャート) 総数
EXPECTED_IMAGE_PAGES = 18  # content 画像を持つページ数
EXPECTED_VERSION_NONE = 0  # version_date が None のページ数 (捏造禁止 = パース不能なら None)
BODY_MIN, BODY_MAX = 156, 5761  # body 文字数の最小/最大
EXPECTED_CACHE_HTM = 71  # 取得済 htm 数 (soft-404 0)

# article/directive リンク内訳 (所得税ファミリ + 消費税 cross-vertical・ロック)。
EXPECTED_ARTICLE_ABBREVS = {
    "shotoku-zei-hou": 60,
    "shotoku-zei-hou-shikkourei": 18,
    "shouhi-zei-hou": 2,
    "shouhi-zei-hou-shikkourei": 1,
}
EXPECTED_DIRECTIVE_ABBREVS = {
    "shotoku-kihon-tsutatsu": 40,
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
    """joto は枝番コードを持たない (母集団実測でロック)。将来 NTA が枝番を追加したら検知。"""
    branched = {r["code"] for r in _records() if "-" in r["code"]}
    assert branched == set(), f"想定外の枝番コード: {sorted(branched)}"


def test_id_equals_code_prefixed() -> None:
    """id は 'joto-taxanswer-<code>' 形式で code と整合。"""
    for r in _records():
        assert r["id"] == f"joto-taxanswer-{r['code']}", r["id"]


def test_link_totals_locked() -> None:
    """リンク総数 (related_articles/directives/qa/unlinked) がロック値と一致。"""
    recs = _records()
    assert sum(len(r["related_articles"]) for r in recs) == EXPECTED_ARTICLES
    assert sum(len(r["related_directives"]) for r in recs) == EXPECTED_DIRECTIVES
    assert sum(len(r["related_qa"]) for r in recs) == EXPECTED_QA
    assert sum(len(r["unlinked_refs"]) for r in recs) == EXPECTED_UNLINKED


def test_income_tax_vertical_directives_linked() -> None:
    """所得税バーティカルの通達リンク (所得税基本通達への実解決の証跡)。

    所基通 -> shotoku-kihon-tsutatsu (40) が related_directives の主体。FU-523 所得税基本通達
    corpus (build/chunks) への実解決の証拠。
    """
    recs = _records()
    counts = Counter(d["law_abbrev"] for r in recs for d in r["related_directives"])
    assert dict(counts) == EXPECTED_DIRECTIVE_ABBREVS, f"通達リンク内訳が不一致: {dict(counts)}"


def test_article_link_breakdown_locked() -> None:
    """条文リンク内訳が所得税ファミリ + 消費税 cross-vertical でロック値一致。"""
    recs = _records()
    counts = Counter(a["law_abbrev"] for r in recs for a in r["related_articles"])
    assert dict(counts) == EXPECTED_ARTICLE_ABBREVS, f"条文リンク内訳が不一致: {dict(counts)}"


def test_directive_ids_prefixed_by_law_abbrev() -> None:
    """全 directive_id が対応 law_abbrev で前置される。"""
    for r in _records():
        for d in r["related_directives"]:
            assert d["directive_id"].startswith(d["law_abbrev"]), d


def test_version_date_none_count() -> None:
    """version_date が None のページ数 (パース不能のみ None・実行日等の捏造禁止)。"""
    none_count = sum(1 for r in _records() if r["version_date"] is None)
    assert none_count == EXPECTED_VERSION_NONE


def test_content_images_locked() -> None:
    """content 画像が 26 枚 (18 ページ)・全て絶対 URL・/template/ ナビは drop。"""
    recs = _records()
    all_imgs = [u for r in recs for u in _images(r["body"])]
    assert len(all_imgs) == EXPECTED_IMAGES, f"content 画像数: {len(all_imgs)}"
    assert sum(1 for r in recs if _images(r["body"])) == EXPECTED_IMAGE_PAGES
    assert all(u.startswith(_HOST) for u in all_imgs), "相対 URL の画像がある"
    assert not any("/template/" in u for u in all_imgs), "ナビ/装飾 (/template/) 画像が混入"


def test_body_length_bounds_locked() -> None:
    """body 文字数の最小/最大がロック値。"""
    lengths = [len(r["body"]) for r in _records()]
    assert min(lengths) == BODY_MIN, f"body 最小長: {min(lengths)}"
    assert max(lengths) == BODY_MAX, f"body 最大長: {max(lengths)}"


def test_no_nav_trailer_leak() -> None:
    """根拠法令等 以降の trailer (関連コード/関連リンク/QAリンク/お問い合わせ/アンケート) が
    body に漏れない (terminated latch + wrapper skip で除外)。
    """
    markers = ("QAリンク", "お問い合わせ先", "アンケ-トへ", "根拠法令等")
    leaked = [r["code"] for r in _records() if any(m in r["body"] for m in markers)]
    assert leaked == [], f"trailer が body に漏れている: {leaked}"


def test_no_related_code_list_leak() -> None:
    """関連コードのリスト項目署名 ('- NNNN　') が body に漏れない。"""
    leaked = [r["code"] for r in _records() if re.search(r"(?m)^- \d{4}　", r["body"])]
    assert leaked == [], f"関連コードが body に漏れている: {leaked[:5]}"


def test_no_crossborder_false_links() -> None:
    """related_articles の law_abbrev が所得税/消費税ファミリのみ・article_id が law_abbrev で
    前置される (越境偽リンクゼロ)。

    Why: 所得税バーティカル外の別法令 (措法系=順序5 予約 UNREG /震災特例法/財形法/復興財確法/
    実施特例法系/耐省令/地方税法/条約・協定/旧法令) は UNREG で、告示 は article prefix を継承させ
    ない guard (FU-528) で、NTA個別通達 (直/課・中黒形含む) は _NOTICE_RE で unlinked に落ちる。
    よって related_articles には所得税 (shotoku-*) と消費税 cross-vertical (shouhi-*) しか現れない。
    """
    allowed = set(EXPECTED_ARTICLE_ABBREVS)
    bad = [
        (r["code"], a["law_abbrev"], a["article_id"])
        for r in _records()
        for a in r["related_articles"]
        if a["law_abbrev"] not in allowed or not a["article_id"].startswith(a["law_abbrev"])
    ]
    assert bad == [], f"越境偽リンク疑い: {bad[:5]}"


def test_no_foreign_law_tokens_in_links() -> None:
    """越境法令名/告示/個別通達が related_articles の raw に混入しない (unlinked 証跡)。

    Why: 措法系/震災特例法/財形法/復興系/実施特例/耐省令/地方税法/条約・協定/旧法令/告示/民法 は
    corpus 未取込 or 別バーティカルゆえ link せず、NTA個別通達番号 (直法/直所/課法/課所/課個・中黒形
    含む) は nta_notice に落ちる。これらのトークンが linked article の raw に現れない = 継承偽リンクが
    構造的にゼロである証跡。
    """
    foreign = (
        "措法",
        "措令",
        "措規",
        "措通",
        "通法",
        "通令",
        "震災特例法",
        "財形法",
        "電子帳簿保存法",
        "復興財確法",
        "復興所得税令",
        "実施特例",
        "実特",
        "耐省令",
        "地方税法",
        "納税貯蓄組合法",
        "郵便法",
        "通基通",
        "条約",
        "協定",
        "告示",
        "民法",
        "直法",
        "直所",
        "課法",
        "課所",
        "課個",
    )
    leaked = [
        (r["code"], a["raw"])
        for r in _records()
        for a in r["related_articles"]
        if any(f in a["raw"] for f in foreign)
    ]
    assert leaked == [], f"越境/通達トークンが link に混入: {leaked[:5]}"


def test_no_fullwidth_digits_in_ids() -> None:
    """article_id/directive_id に全角アラビア数字 (０-９) が残らない (FU-528 正規化の維持)。"""
    fw = re.compile(r"[０-９]")
    bad = [
        (r["code"], ref.get("article_id") or ref.get("directive_id"))
        for r in _records()
        for ref in (*r["related_articles"], *r["related_directives"])
        if fw.search(ref.get("article_id") or ref.get("directive_id") or "")
    ]
    assert bad == [], f"全角数字が id に残存: {bad[:5]}"


def test_all_source_urls_under_joto() -> None:
    """全 source_url が NTA taxanswer/joto パスを指す (URL 一次確認済)。"""
    for r in _records():
        assert f"/taxanswer/joto/{r['code']}.htm" in r["source_url"], r["source_url"]


def test_license_and_attribution() -> None:
    """全レコードが NTA タックスアンサーのライセンス/帰属を持つ (PDL1.0 = CC BY 互換)。"""
    for r in _records():
        assert r["license"] == "cc-by-jp-nta", r["license"]
        assert r["attribution"] == "国税庁タックスアンサー", r["attribution"]


# ===========================================================
# byte 再現 + htm 数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _JOTO_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/joto/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_cache_htm_count() -> None:
    """取得済 htm が 71 (soft-404 0・NTA 目次の増減検知)。"""
    htm = list(_JOTO_CACHE.glob("*.htm"))
    assert len(htm) == EXPECTED_CACHE_HTM, f"htm 数が {EXPECTED_CACHE_HTM} でない: {len(htm)}"


@pytest.mark.skipif(
    not _JOTO_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/joto/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を byte 再現する (決定性 + 完全性)。

    Note: 通達リンク解決は build/chunks の所得税基本通達 (FU-523) corpus に依存するため、
    build/chunks 不在時は directives が全 unlink になり byte 不一致になり得る。よって
    build/chunks の通達 corpus がある push 前ローカルでのみ意味を持つ (cache と併せ skipif)。
    """
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        [
            "--cache-dir",
            str(_JOTO_CACHE),
            "--tax-category",
            "joto",
            "--law-abbrev",
            "joto-taxanswer",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    produced = out_dir / "joto-taxanswer.taxanswer.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュの出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

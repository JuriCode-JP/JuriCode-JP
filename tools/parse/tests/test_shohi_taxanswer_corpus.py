"""test_shohi_taxanswer_corpus.py -- 消費税タックスアンサー corpus fixture のゲート (FU-528).

Why this test exists:
    消費税タックスアンサー (URL path /taxanswer/shohi/・6000 番台) の committed 実体は
    build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/shohi-taxanswer.corpus.chunks.baseline.jsonl`
    (hojin/sozoku/souzoku/hyoka と同じ場所・同じ規約)。本テストは佐藤ロック値 (全 114 件・
    枝番 0・links 395/54/151/336・content 画像 22/8・version_date None 0・body 118..6449) を
    fixture に対して pin し、cache がある push 前ローカルでは parser が fixture を byte 再現する
    ことを検証する。

    母集団 (2026-07-01 実測・佐藤ロック):
        code/index.htm の /taxanswer/shohi/ href = 115 codes
        soft-404 1 (6950) / redirect 0 / dup 0 -> corpus 114 chunks (枝番なし)

    FU-528 (config-light) の中核回帰を pin する:
    - **消費税バーティカルのリンク**: 消基通 (shouhi-kihon-tsutatsu 54) が related_directives
      として linked であること。FU-527 で多法令化した基盤の上に消費税 prefix を config 追加
      した結果、消基通参照が FU-519 消費税通達 corpus へ実解決する証跡。
    - **cross-vertical リンク**: 消費税タックスアンサーが引用する法人税法 (法法/法令/法規) は
      既取込の houjin corpus へ link する (houjin-zei-hou 系 4 件)。越境ではなく実在 corpus への
      正当な相互参照。
    - **越境偽リンクゼロ**: 消費税バーティカル外の別法令参照 (輸徴法/旧消法/印法/所規/措/所/
      通/民 等) と 告示 (厚生省/国税庁告示) は related_articles に混入せず unlinked に記録
      (corpus_unregistered / nta_kokuji)。amendment 附則は kaisei_funsoku、個別通達 (直/課) は
      nta_notice / tsutatsu_not_in_corpus。
    - **全角数字正規化 (FU-528)**: article_id/directive_id に全角アラビア数字 (０-９) が残らない
      (消法15の２ -> art-15-2、同一参照 消法2①九の二 が 6102/6303 で単一 id に統一)。
    - **同一法・非標準 article_number の受容 (佐藤裁定 2026-07-01・(A)(C))**: 別表/号 (別表第2一・
      2九の二) と source 読点欠落 (31消令48) は消費税法内の参照ゆえ受容ロック。id に日本語を
      含み得る (越境ではない)。
    - **trailer 非漏洩**: 根拠法令等 以降の 関連コード/関連リンク/QAリンク が body に漏れない。

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
_FIXTURE = _THIS.parent / "fixtures" / "shohi-taxanswer.corpus.chunks.baseline.jsonl"
_SHOHI_CACHE = _REPO_ROOT / "cache" / "taxanswer" / "shohi"

# LOCKED 確定値 (実パーサ dry-run + 母集団突合で確定・佐藤ロック 2026-07-01・改変は明示承認必須)。
EXPECTED_TOTAL = 114  # dedup 後のユニーク code 数 (母集団 115 - soft-404 1[6950])
EXPECTED_BRANCHED: frozenset[str] = frozenset()  # 枝番コードなし
EXPECTED_ARTICLES = 395  # related_articles 総数
EXPECTED_DIRECTIVES = 54  # related_directives 総数
EXPECTED_QA = 151  # related_qa 総数 (href 由来・body 非依存)
EXPECTED_UNLINKED = 336  # unlinked_refs 総数
EXPECTED_IMAGES = 22  # content 画像 (計算表・フローチャート) 総数
EXPECTED_IMAGE_PAGES = 8  # content 画像を持つページ数
EXPECTED_VERSION_NONE = 0  # version_date が None のページ数 (捏造禁止 = パース不能なら None)
BODY_MIN, BODY_MAX = 118, 6449  # body 文字数の最小/最大
EXPECTED_CACHE_HTM = 114  # 取得済 htm 数 (soft-404 1[6950] 除外後)

# article/directive リンク内訳 (config-light 多法令化の証跡・ロック)。消費税ファミリ +
# 法人税 cross-vertical (法法/法令/法規)。
EXPECTED_ARTICLE_ABBREVS = {
    "shouhi-zei-hou": 279,
    "shouhi-zei-hou-shikkourei": 93,
    "shouhi-zei-hou-shikoukisoku": 19,
    "houjin-zei-hou": 2,
    "houjin-zei-hou-shikkourei": 1,
    "houjin-zei-hou-shikoukisoku": 1,
}
EXPECTED_DIRECTIVE_ABBREVS = {
    "shouhi-kihon-tsutatsu": 54,
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
    """shohi は枝番コードなし (母集団実測)。"""
    branched = {r["code"] for r in _records() if "-" in r["code"]}
    assert branched == EXPECTED_BRANCHED, f"想定外の枝番: {sorted(branched)}"


def test_id_equals_code_prefixed() -> None:
    """id は 'shohi-taxanswer-<code>' 形式で code と整合。

    Why: record_id は FU-527 で law_abbrev をパラメタ化した (旧 'hojin-taxanswer-' ハード
    コードでは他カテゴリで誤 id を生む silent bug だった)。
    """
    for r in _records():
        assert r["id"] == f"shohi-taxanswer-{r['code']}", r["id"]


def test_link_totals_locked() -> None:
    """リンク総数 (related_articles/directives/qa/unlinked) がロック値と一致。"""
    recs = _records()
    assert sum(len(r["related_articles"]) for r in recs) == EXPECTED_ARTICLES
    assert sum(len(r["related_directives"]) for r in recs) == EXPECTED_DIRECTIVES
    assert sum(len(r["related_qa"]) for r in recs) == EXPECTED_QA
    assert sum(len(r["unlinked_refs"]) for r in recs) == EXPECTED_UNLINKED


def test_consumption_vertical_directives_linked() -> None:
    """消費税バーティカルの通達リンク (config-light 多法令化の証跡)。

    消基通 -> shouhi-kihon-tsutatsu (54) が related_directives として linked であること。
    FU-519 消費税通達 corpus (build/chunks) への実解決の証拠。
    """
    recs = _records()
    counts = Counter(d["law_abbrev"] for r in recs for d in r["related_directives"])
    assert dict(counts) == EXPECTED_DIRECTIVE_ABBREVS, f"通達リンク内訳が不一致: {dict(counts)}"


def test_article_link_breakdown_locked() -> None:
    """条文リンク内訳が消費税ファミリ + 法人税 cross-vertical でロック値一致。"""
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
    """content 画像が 22 枚 (8 ページ)・全て絶対 URL・/template/ ナビは drop。"""
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
    """related_articles の law_abbrev が消費税/法人税ファミリのみ・article_id が law_abbrev で
    前置される (越境偽リンクゼロ)。

    Why: 消費税バーティカル外の別法令 (輸徴法/旧消法/印法/所規/措/所/通/民) は UNREG で、
    告示 (厚生省/国税庁) は article prefix を継承させない guard (FU-528) で unlinked に落ちる。
    よって related_articles には消費税 (shouhi-*) と法人税 cross-vertical (houjin-*) しか
    現れない。全 article_id が対応略称で前置されることも機械検証する。
    非標準 article_number (別表/号/31消令48) は消費税法内ゆえ id に日本語を含み得るが (佐藤
    裁定 (A)(C) で受容)、越境ではない。
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
    """越境法令名/告示が related_articles の raw に混入しない (unlinked に落ちている証跡)。"""
    foreign = ("輸徴法", "旧消法", "印法", "所規", "措法", "措令", "措規", "措通", "告示", "民法")
    leaked = [
        (r["code"], a["raw"])
        for r in _records()
        for a in r["related_articles"]
        if any(f in a["raw"] for f in foreign)
    ]
    assert leaked == [], f"越境トークンが link に混入: {leaked[:5]}"


def test_no_fullwidth_digits_in_ids() -> None:
    """article_id/directive_id に全角アラビア数字 (０-９) が残らない (FU-528 正規化 pin)。"""
    fw = re.compile(r"[０-９]")
    bad = [
        (r["code"], ref.get("article_id") or ref.get("directive_id"))
        for r in _records()
        for ref in (*r["related_articles"], *r["related_directives"])
        if fw.search(ref.get("article_id") or ref.get("directive_id") or "")
    ]
    assert bad == [], f"全角数字が id に残存: {bad[:5]}"


def test_all_source_urls_under_shohi() -> None:
    """全 source_url が NTA taxanswer/shohi パスを指す (URL 一次確認済)。"""
    for r in _records():
        assert f"/taxanswer/shohi/{r['code']}.htm" in r["source_url"], r["source_url"]


def test_license_and_attribution() -> None:
    """全レコードが NTA タックスアンサーのライセンス/帰属を持つ (PDL1.0 = CC BY 互換)。"""
    for r in _records():
        assert r["license"] == "cc-by-jp-nta", r["license"]
        assert r["attribution"] == "国税庁タックスアンサー", r["attribution"]


# ===========================================================
# byte 再現 + htm 数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _SHOHI_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/shohi/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_cache_htm_count() -> None:
    """取得済 htm が 114 (soft-404 1[6950] 除外後・NTA 目次の増減検知)。"""
    htm = list(_SHOHI_CACHE.glob("*.htm"))
    assert len(htm) == EXPECTED_CACHE_HTM, f"htm 数が {EXPECTED_CACHE_HTM} でない: {len(htm)}"


@pytest.mark.skipif(
    not _SHOHI_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/shohi/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を byte 再現する (決定性 + 完全性)。

    Note: 通達リンク解決は build/chunks の消費税通達 corpus (FU-519) に依存するため、
    build/chunks 不在時は directives が全 unlink になり byte 不一致になり得る。よって
    build/chunks の消費税通達 corpus がある push 前ローカルでのみ意味を持つ (cache と併せ skipif)。
    """
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        [
            "--cache-dir",
            str(_SHOHI_CACHE),
            "--tax-category",
            "shohi",
            "--law-abbrev",
            "shohi-taxanswer",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    produced = out_dir / "shohi-taxanswer.taxanswer.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュの出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

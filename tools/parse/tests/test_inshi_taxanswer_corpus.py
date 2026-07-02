"""test_inshi_taxanswer_corpus.py -- 印紙税・その他の国税タックスアンサー corpus fixture のゲート (FU-532).

Why this test exists:
    印紙税・その他の国税タックスアンサー (URL path /taxanswer/inshi/・7000 番台 + その他) の
    committed 実体は build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/inshi-taxanswer.corpus.chunks.baseline.jsonl`
    (hojin/sozoku/shohi/gensen/shotoku/joto と同じ場所・同じ規約)。本テストは佐藤ロック値
    (全 30 件・枝番なし・links 2/0/30/131・content 画像 16/3・version_date None 0・
    body 335..7035) を fixture に対して pin し、cache がある push 前ローカルでは parser が
    fixture を byte 再現することを検証する。

    母集団 (2026-07-02 実測・佐藤ロック):
        code/index.htm の /taxanswer/inshi/ href = 30 codes
        soft-404 0 / redirect 0 / dup 0 -> corpus 30 chunks (枝番なし)

    FU-532 は所得税/法人税バーティカル上の純 config-light 取込 (parser の本文/リンクロジックは
    無変更・CORPUS_UNREGISTERED_PREFIXES に印紙/登録免許税/その他国税の未取込 prefix を 9 件追加のみ):
    - **本文 corpus なし = ほぼ全 unlinked**: 印紙税法/登録免許税法/自動車重量税法/国際観光旅客税法
      は本 corpus に本文を持たないため、根拠法令等 の参照は基本すべて unlinked に記録される
      (印令/印規/印基通/登法/登規/自法/旅客法/旅客令/旅客通達 = corpus_unregistered、その継続は
      corpus_unregistered_continuation)。措法系 (順序5 予約 UNREG) も同様。これが「リンク先はほぼ空」
      が正常である証跡。
    - **cross-vertical リンク (7131 のみ)**: 印紙税の一部トピックが法人税法・所得税法を引用するため
      法法55 -> houjin-zei-hou / 所法45 -> shotoku-zei-hou へ link (計 2)。越境ではなく実在 corpus への
      正当な相互参照 (明示 prefix)。**既知の軽微な瑕疵 (佐藤ロック・案A)**: 共有パーサは丸数字 ④ (項) を
      除去する一方、漢字号番号 (一/三) を除去しないため article_id は houjin-zei-hou-art-55一 /
      shotoku-zei-hou-art-45三 となる。法令特定は正しく越境偽リンクではないため案A (parser 無変更) で
      ロックし、号番号正規化は follow-up FU 候補として記録する。
    - **印紙税額一覧表 (7140/7141)**: 根拠法令等 を持たない一覧表ページ。**入れ子テーブル**により
      body の税額表 markdown が重複・行崩れする (§4 案A で許容・佐藤ロック)。クラッシュせず税額数値は
      全て body に残り retrieval 可能。nav trailer は お問い合わせ先 STOP 見出しで正しく終端 (漏れなし)。
      表処理の scoped fix (_table_to_markdown の recursive=False 化) は follow-up FU 候補。
    - **越境偽リンクゼロ**: 所得税/法人税バーティカル外の別法令 (印紙/登免/自重/旅客/措法系/告示) は
      related_articles に混入せず unlinked に記録。個別通達/名称付き通達タイトルは unresolved_no_context
      または corpus_unregistered_continuation、amendment 附則は kaisei_funsoku。

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
_FIXTURE = _THIS.parent / "fixtures" / "inshi-taxanswer.corpus.chunks.baseline.jsonl"
_INSHI_CACHE = _REPO_ROOT / "cache" / "taxanswer" / "inshi"

# LOCKED 確定値 (実パーサ dry-run + 母集団突合で確定・佐藤ロック 2026-07-02・改変は明示承認必須)。
EXPECTED_TOTAL = 30  # dedup 後のユニーク code 数 (母集団 30 - soft-404 0)
EXPECTED_ARTICLES = 2  # related_articles 総数 (7131 の 法法55/所法45 のみ)
EXPECTED_DIRECTIVES = 0  # related_directives 総数 (印基通/旅客通達 等は全て UNREG ゆえ 0)
EXPECTED_QA = 30  # related_qa 総数 (href 由来・body 非依存)
EXPECTED_UNLINKED = 131  # unlinked_refs 総数 (印紙/登免/その他国税・措法系の本文なし参照が主)
EXPECTED_IMAGES = 16  # content 画像 (計算表・フローチャート) 総数
EXPECTED_IMAGE_PAGES = 3  # content 画像を持つページ数
EXPECTED_VERSION_NONE = 0  # version_date が None のページ数 (捏造禁止 = パース不能なら None)
BODY_MIN, BODY_MAX = 335, 7035  # body 文字数の最小/最大
EXPECTED_CACHE_HTM = 30  # 取得済 htm 数 (soft-404 0)

# article リンク内訳 (7131 の cross-vertical のみ・ロック)。directive は 0 (印基通等は全 UNREG)。
EXPECTED_ARTICLE_ABBREVS = {
    "houjin-zei-hou": 1,
    "shotoku-zei-hou": 1,
}
EXPECTED_DIRECTIVE_ABBREVS: dict[str, int] = {}
_HOST = "https://www.nta.go.jp/"

# 印紙税額一覧表ページ (根拠法令等 を持たず入れ子テーブルを body に含む・§4 案A ロック)。
_TABLE_PAGES = ("7140", "7141")


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
    """inshi は枝番コードを持たない (母集団実測でロック)。将来 NTA が枝番を追加したら検知。"""
    branched = {r["code"] for r in _records() if "-" in r["code"]}
    assert branched == set(), f"想定外の枝番コード: {sorted(branched)}"


def test_id_equals_code_prefixed() -> None:
    """id は 'inshi-taxanswer-<code>' 形式で code と整合。"""
    for r in _records():
        assert r["id"] == f"inshi-taxanswer-{r['code']}", r["id"]


def test_link_totals_locked() -> None:
    """リンク総数 (related_articles/directives/qa/unlinked) がロック値と一致。"""
    recs = _records()
    assert sum(len(r["related_articles"]) for r in recs) == EXPECTED_ARTICLES
    assert sum(len(r["related_directives"]) for r in recs) == EXPECTED_DIRECTIVES
    assert sum(len(r["related_qa"]) for r in recs) == EXPECTED_QA
    assert sum(len(r["unlinked_refs"]) for r in recs) == EXPECTED_UNLINKED


def test_no_linked_directives() -> None:
    """directive リンクは 0 (印基通/旅客通達 等は本 corpus に無く全て UNREG unlinked)。

    印紙税・その他の国税は基本通達 corpus を取込んでいないため、通達参照は全て
    corpus_unregistered に落ちる (link しない)。将来 印紙税法基本通達 を取込む際に検知。
    """
    recs = _records()
    counts = Counter(d["law_abbrev"] for r in recs for d in r["related_directives"])
    assert dict(counts) == EXPECTED_DIRECTIVE_ABBREVS, f"通達リンク内訳が不一致: {dict(counts)}"


def test_article_link_breakdown_locked() -> None:
    """条文リンク内訳が 7131 の cross-vertical (法人税/所得税) のみでロック値一致。"""
    recs = _records()
    counts = Counter(a["law_abbrev"] for r in recs for a in r["related_articles"])
    assert dict(counts) == EXPECTED_ARTICLE_ABBREVS, f"条文リンク内訳が不一致: {dict(counts)}"


def test_version_date_none_count() -> None:
    """version_date が None のページ数 (パース不能のみ None・実行日等の捏造禁止)。"""
    none_count = sum(1 for r in _records() if r["version_date"] is None)
    assert none_count == EXPECTED_VERSION_NONE


def test_content_images_locked() -> None:
    """content 画像が 16 枚 (3 ページ)・全て絶対 URL・/template/ ナビは drop。"""
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
    body に漏れない (terminated latch + wrapper skip で除外)。根拠法令等 を持たない一覧表
    ページ (7140/7141) でも お問い合わせ先 STOP 見出しで終端されるため漏れない。
    """
    markers = ("QAリンク", "お問い合わせ先", "アンケ-トへ", "根拠法令等")
    leaked = [r["code"] for r in _records() if any(m in r["body"] for m in markers)]
    assert leaked == [], f"trailer が body に漏れている: {leaked}"


def test_no_related_code_list_leak() -> None:
    """関連コードのリスト項目署名 ('- NNNN　') が body に漏れない。"""
    leaked = [r["code"] for r in _records() if re.search(r"(?m)^- \d{4}　", r["body"])]
    assert leaked == [], f"関連コードが body に漏れている: {leaked[:5]}"


def test_stamp_duty_table_pages_locked() -> None:
    """印紙税額一覧表 (7140/7141) は 根拠法令等 なし = 0 link・body に税額表を含む (§4 案A ロック)。

    Why: 入れ子テーブルにより body の税額表 markdown は重複するが (§4 で佐藤ロック・案A)、
    クラッシュせず税額数値は body に残る。ここでは (a) 両ページが corpus に存在し、(b) 参照リンクが
    0 (根拠法令等 不在ゆえ) で、(c) body が非空で「印紙税額」を含む ことを pin する。表処理の
    scoped fix は follow-up FU (本テストは案A の意図的挙動を記録し、無言の退行を防ぐ)。
    """
    by_code = {r["code"]: r for r in _records()}
    for code in _TABLE_PAGES:
        assert code in by_code, f"一覧表ページ {code} が corpus に不在"
        r = by_code[code]
        assert len(r["related_articles"]) == 0, f"{code}: 根拠法令等 なしのはずが article link あり"
        assert len(r["related_directives"]) == 0, (
            f"{code}: 根拠法令等 なしのはずが directive link あり"
        )
        assert r["body"].strip(), f"{code}: body が空"
        assert "印紙税額" in r["body"] or "非課税" in r["body"], f"{code}: 税額表が body に欠落"


def test_no_crossborder_false_links() -> None:
    """related_articles の law_abbrev が法人税/所得税ファミリのみ・article_id が law_abbrev で
    前置される (越境偽リンクゼロ)。

    Why: 印紙税本体 (印令/印規/印基通)・登録免許税 (登法/登規)・その他の国税 (自法/旅客法系)・
    措法系・告示 は UNREG または guard で unlinked に落ちる。よって related_articles には 7131 の
    法人税 (houjin-zei-hou) と所得税 (shotoku-zei-hou) の cross-vertical しか現れない。
    article_id は houjin-zei-hou-art-55一 / shotoku-zei-hou-art-45三 で law_abbrev 前置は満たす
    (漢字号の末尾は §4 案A の既知瑕疵・別 FU で正規化候補)。
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

    Why: 印紙/登録免許税/自動車重量税/国際観光旅客税/措法系/告示 は corpus 未取込 or 別バーティカル
    ゆえ link せず unlinked に記録される。これらのトークンが linked article の raw (7131 の 法法/所法
    のみ) に現れない = 継承偽リンクが構造的にゼロである証跡。
    """
    foreign = (
        "印令",
        "印規",
        "印基通",
        "印法",
        "登法",
        "登規",
        "自法",
        "旅客法",
        "旅客令",
        "旅客通達",
        "措法",
        "措令",
        "措規",
        "措通",
        "登録免許税",
        "自動車重量税",
        "国際観光旅客税",
        "告示",
        "別表第一",
        "改正",
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


def test_all_source_urls_under_inshi() -> None:
    """全 source_url が NTA taxanswer/inshi パスを指す (URL 一次確認済)。"""
    for r in _records():
        assert f"/taxanswer/inshi/{r['code']}.htm" in r["source_url"], r["source_url"]


def test_license_and_attribution() -> None:
    """全レコードが NTA タックスアンサーのライセンス/帰属を持つ (PDL1.0 = CC BY 互換)。"""
    for r in _records():
        assert r["license"] == "cc-by-jp-nta", r["license"]
        assert r["attribution"] == "国税庁タックスアンサー", r["attribution"]


# ===========================================================
# byte 再現 + htm 数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _INSHI_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/inshi/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_cache_htm_count() -> None:
    """取得済 htm が 30 (soft-404 0・NTA 目次の増減検知)。"""
    htm = list(_INSHI_CACHE.glob("*.htm"))
    assert len(htm) == EXPECTED_CACHE_HTM, f"htm 数が {EXPECTED_CACHE_HTM} でない: {len(htm)}"


@pytest.mark.skipif(
    not _INSHI_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/inshi/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を byte 再現する (決定性 + 完全性)。

    Note: 印紙税は基本通達 corpus を取込んでいないため directive link は 0 で、byte 再現は
    build/chunks の tsutatsu corpus 有無に依存しない (7131 の cross-vertical article link は
    corpus 不在でも解決する / article は LAW_PREFIX_MAP のみで link)。cache がある push 前
    ローカルでのみ意味を持つ (skipif)。
    """
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        [
            "--cache-dir",
            str(_INSHI_CACHE),
            "--tax-category",
            "inshi",
            "--law-abbrev",
            "inshi-taxanswer",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    produced = out_dir / "inshi-taxanswer.taxanswer.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュの出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

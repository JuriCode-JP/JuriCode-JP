"""test_hojin_taxanswer_corpus.py -- 法人税タックスアンサー corpus fixture のゲート (FU-526).

Why this test exists:
    法人税タックスアンサーの committed 実体は build/chunks (gitignored, 再生成) ではなく
    `tools/parse/tests/fixtures/hojin-taxanswer.corpus.chunks.baseline.jsonl`
    (souzoku/hyoka と同じ場所・同じ規約)。本テストは佐藤ロック値 (全 111 件・枝番 5・
    links 222/28/132/361・content 画像 22・version_date None 0・body 189..8338) を fixture に
    対して pin し (links 221/28/132/399・content 画像 22・version_date None 0・body 189..6418,
    2026-07-01 FU-527 再ロック済)、cache がある push 前ローカルでは parser が fixture を byte
    再現することを検証する。

    母集団 (2026-07-01 実測・佐藤一次突合済でロック):
        code/index.htm の /taxanswer/hojin/ href = 115 codes
        soft-404 (索引に残る削除済リンク) 4 件 (5207/5209/5435/5437) を除外 -> 111 leaves
        redirect 0 / dup 0 -> corpus 111 chunks

    FU-526 の中核回帰を pin する:
    - 枝番コード (5364-2 等 5 件) が main 経路で SKIP されず取り込まれ、title に枝番片 "-2"
      が残らないこと (旧 `^\\d{4,5}$` guard + int() sort が枝番を落としていた回帰)。
    - 本文スコープがブロックリスト (Phase 2): 計算方法/具体例/手続き 等の実体的節が本文に
      入り (拡張)、根拠法令等 以降の trailer (関連コード/関連リンク/QAリンク) は body に
      漏れないこと。既存 8 PoC は byte 不変。
    - content 画像 (計算表・フローチャート) を絶対 URL の markdown で保持し、/template/ の
      ナビ画像は drop すること。
    - named-law 参照が houjin 系以外へ偽リンクしないこと (LAW_PREFIX_MAP は裸 "法" を持たない)。

    **落ちたら直すのはパーサ/キャッシュであって fixture/期待値ではない** (source-locked)。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-taxanswer.py"
_FIXTURE = _THIS.parent / "fixtures" / "hojin-taxanswer.corpus.chunks.baseline.jsonl"
_HOJIN_CACHE = _REPO_ROOT / "cache" / "taxanswer" / "hojin"

# LOCKED 確定値 (実パーサ dry-run + 母集団突合で確定・佐藤ロック 2026-07-01・改変は明示承認必須)。
#
# 2026-07-01 FU-527 再ロック (佐藤明示承認): taxanswer parser の多法令化 (相続バーティカル
# 対応) が、旧ロック値に潜んでいた 3 つのバグを修正した (expected がバグだった時のみの再ロック)。
#   1. 偽リンク除去 (5100): `通法10` (国税通則法10条) が houjin-zei-hou-shikoukisoku-art-通法10
#      という壊れた article_id で誤リンクされていた -> related_articles 222->221。
#   2. silent-drop 記録 (24 件): 耐令/旧法令/租特透明化法/NTA通達番号 等の越境参照が silent に
#      捨てられていた -> unlinked_refs に記録 (reason 精緻化と併せ 361->399)。
#   3. body de-dup (5927-3 のみ): mega-<p> 異形構造で 12 段落が二重取得され trailer も漏れていた
#      -> de-dup + trailer 除去で body 最大 8338->6418 (全 content 文 probe 検証で欠落ゼロ)。
# directives/qa/title/version/images/total/branched は全 111 チャンク不変。
EXPECTED_TOTAL = 111  # dedup 後のユニーク code 数 (母集団 115 - soft-404 4)
EXPECTED_BRANCHED = frozenset({"5364-2", "5400-2", "5409-2", "5927-2", "5927-3"})  # 枝番 5 件
EXPECTED_ARTICLES = 221  # related_articles 総数 (FU-527: 222->221, 通法10 偽リンク除去)
EXPECTED_DIRECTIVES = 28  # related_directives 総数
EXPECTED_QA = 132  # related_qa 総数 (href 由来・body 非依存)
EXPECTED_UNLINKED = 399  # unlinked_refs 総数 (FU-527: 361->399, silent-drop 24 記録+reason 精緻化)
EXPECTED_IMAGES = 22  # content 画像 (計算表・フローチャート) 総数
EXPECTED_IMAGE_PAGES = 8  # content 画像を持つページ数
EXPECTED_VERSION_NONE = 0  # version_date が None のページ数 (捏造禁止 = パース不能なら None)
BODY_MIN, BODY_MAX = 189, 6418  # body 文字数の最小/最大 (FU-527: 8338->6418, 5927-3 de-dup)
EXPECTED_CACHE_HTM = 111  # 取得済 htm 数 (soft-404 4 は保存されない)
_HOST = "https://www.nta.go.jp/"


def _records() -> list[dict]:
    return [
        json.loads(line)
        for line in _FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _code_key(code: str) -> tuple[int, int]:
    """'5364-2' -> (5364, 2), '5200' -> (5200, 0)。パーサの _code_sort_key と同等。"""
    if "-" in code:
        base, branch = code.split("-", 1)
        return (int(base), int(branch))
    return (int(code), 0)


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


def test_id_equals_code_prefixed() -> None:
    """id は 'hojin-taxanswer-<code>' 形式で code と整合 (枝番含む)。"""
    for r in _records():
        assert r["id"] == f"hojin-taxanswer-{r['code']}", r["id"]


def test_globally_numeric_sorted() -> None:
    """corpus が code の数値キー (枝番 base, branch) で全体ソート済。"""
    codes = [r["code"] for r in _records()]
    assert codes == sorted(codes, key=_code_key), "corpus が数値順に並んでいない"


def test_branched_codes_present() -> None:
    """枝番コード 5 件が取り込まれている (旧 `^\\d{4,5}$` guard が落としていた回帰)。"""
    branched = {r["code"] for r in _records() if "-" in r["code"]}
    assert branched == EXPECTED_BRANCHED, f"枝番コード集合が不一致: {sorted(branched)}"


def test_branched_titles_not_truncated() -> None:
    """枝番ページの title に枝番片 '-2'/'-3' が残らない (No.NNNN-N の剥がし漏れ回帰)。"""
    by_code = {r["code"]: r for r in _records()}
    for code in EXPECTED_BRANCHED:
        title = by_code[code]["title"]
        assert not title.startswith("-"), f"{code} の title が枝番片で始まる: {title!r}"
        assert title.strip(), f"{code} の title が空"


def test_link_totals_locked() -> None:
    """リンク総数 (related_articles/directives/qa/unlinked) がロック値と一致。"""
    recs = _records()
    assert sum(len(r["related_articles"]) for r in recs) == EXPECTED_ARTICLES
    assert sum(len(r["related_directives"]) for r in recs) == EXPECTED_DIRECTIVES
    assert sum(len(r["related_qa"]) for r in recs) == EXPECTED_QA
    assert sum(len(r["unlinked_refs"]) for r in recs) == EXPECTED_UNLINKED


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


def test_body_scope_expansion() -> None:
    """本文スコープ拡張 (Phase 2): 計算方法/具体例 の画像を持つページが本文にそれを含む。

    Why: 旧許可リスト {概要,対象税目} は計算方法/具体例節を本文ごと落としていた。5608/5650/
    5763 は計算方法節の計算表画像を持つため、拡張後スコープで画像が本文に現れることで
    節が取り込まれた証跡とする。body 最大長も拡張後の値に固定する。
    """
    by_code = {r["code"]: r for r in _records()}
    for code in ("5608", "5650", "5763"):
        assert _images(by_code[code]["body"]), f"{code} の計算方法画像が本文に無い (スコープ未拡張)"
    lengths = [len(r["body"]) for r in _records()]
    assert min(lengths) == BODY_MIN, f"body 最小長: {min(lengths)}"
    assert max(lengths) == BODY_MAX, f"body 最大長: {max(lengths)}"


def test_no_nav_trailer_leak() -> None:
    """根拠法令等 以降の trailer (関連コード/関連リンク/QAリンク) が body に漏れない。

    Why: ブロックリストの終端 (terminated) が効かないと 関連コード のリンク列
    ('- 5210　...') が body に再流入する。related-code のリスト項目署名で回帰を pin。
    """
    leaked = [r["code"] for r in _records() if re.search(r"(?m)^- \d{4}　", r["body"])]
    assert leaked == [], f"trailer (関連コード) が body に漏れている: {leaked[:5]}"


def test_named_laws_not_false_linked() -> None:
    """related_articles の法略称が houjin 系のみ・article_id が law_abbrev で前置される。

    Why: LAW_PREFIX_MAP は裸 "法" を持たず 法法/法令/法規 の specific prefix のみゆえ、
    会社法等の named-law が houjin へ偽リンクしない。全 article_id が対応略称で始まる
    ことを機械検証 (偽リンク = 404 ゼロ)。
    """
    allowed = {"houjin-zei-hou", "houjin-zei-hou-shikkourei", "houjin-zei-hou-shikoukisoku"}
    bad = [
        (r["code"], a["law_abbrev"], a["article_id"])
        for r in _records()
        for a in r["related_articles"]
        if a["law_abbrev"] not in allowed or not a["article_id"].startswith(a["law_abbrev"])
    ]
    assert bad == [], f"偽リンク疑い: {bad[:5]}"


def test_all_source_urls_under_hojin() -> None:
    """全 source_url が NTA taxanswer/hojin パスを指す (URL 一次確認済)。"""
    for r in _records():
        assert f"/taxanswer/hojin/{r['code']}.htm" in r["source_url"], r["source_url"]


def test_soft404_codes_absent() -> None:
    """索引の削除済リンク (soft-404) 4 件が corpus に含まれない (完全性の記録)。"""
    codes = {r["code"] for r in _records()}
    for dead in ("5207", "5209", "5435", "5437"):
        assert dead not in codes, f"soft-404 コード {dead} が corpus に混入"


def test_license_and_attribution() -> None:
    """全レコードが NTA タックスアンサーのライセンス/帰属を持つ (PDL1.0 = CC BY 互換)。"""
    for r in _records():
        assert r["license"] == "cc-by-jp-nta", r["license"]
        assert r["attribution"] == "国税庁タックスアンサー", r["attribution"]


# ===========================================================
# byte 再現 + htm 数 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _HOJIN_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/hojin/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_cache_htm_count() -> None:
    """取得済 htm が 111 (soft-404 4 は保存されない・NTA 目次の増減検知)。"""
    htm = list(_HOJIN_CACHE.glob("*.htm"))
    assert len(htm) == EXPECTED_CACHE_HTM, f"htm 数が {EXPECTED_CACHE_HTM} でない: {len(htm)}"


@pytest.mark.skipif(
    not _HOJIN_CACHE.exists(),
    reason="NTA HTML cache (cache/taxanswer/hojin/, gitignored) 不在 -- push 前ローカルゲート",
)
def test_fixture_byte_reproducible_from_cache(tmp_path: Path) -> None:
    """parser が実キャッシュから fixture を byte 再現する (決定性 + 完全性)。"""
    mod = _import_parser()
    out_dir = tmp_path / "out"
    rc = mod.main(
        [
            "--cache-dir",
            str(_HOJIN_CACHE),
            "--tax-category",
            "hojin",
            "--law-abbrev",
            "hojin-taxanswer",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    produced = out_dir / "hojin-taxanswer.taxanswer.chunks.jsonl"
    assert produced.read_bytes() == _FIXTURE.read_bytes(), (
        "実キャッシュの出力が fixture と byte 不一致 "
        "(直すのはパーサ/キャッシュであって fixture ではない)"
    )

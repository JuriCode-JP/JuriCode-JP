"""test_hojin_precedents_store.py -- 法人税判例 store + 導出ロジックの機械検証 (CI-safe).

Why (判例25シード MVP・2026-07-04): 裁決 store (rulings.jsonl) の cited_refs から機械導出した
25判例を committed store (data/v0.2/case-law/hojin/precedents.jsonl) に永続化した。本 test は
ロック済 committed 成果物と導出関数の不変条件を検証する:
  - store 全行が PrecedentStoreEntry として IR valid・case_id 100% ユニーク (dup0)。
  - case_id prefix (scj/hcj/dcj) が裁判所種別と整合。
  - cited_by の裁決 case_id が rulings.jsonl に実在 (越境0)・被引用>1 が忠実保持。
  - 和暦 (元号略記含む) + 全角の日付境界、case_id への日付数字混入なし・連続ハイフンなしの回帰。
  - schema: precedent は url 省略で valid・ruling は url 必須 (if/then)。
data/v0.2 は gitignore 対象外ゆえ CI で実在する (hermetic・leaf HTML 非依存)。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

_STORE = _REPO_ROOT / "data" / "v0.2" / "case-law" / "hojin" / "precedents.jsonl"
_RULINGS = _REPO_ROOT / "data" / "v0.2" / "case-law" / "hojin" / "rulings.jsonl"
_SCHEMA = _REPO_ROOT / "schema" / "case-link.schema.json"
_BUILDER_PATH = _REPO_ROOT / "tools" / "parse" / "build-hojin-precedents.py"


def _load_builder():
    """ハイフン名モジュール build-hojin-precedents.py を importlib で読む (確立パターン)。"""
    spec = importlib.util.spec_from_file_location("build_hojin_precedents", _BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_store() -> list[dict]:
    if not _STORE.exists():
        pytest.skip(f"store not present: {_STORE}")
    rows = []
    for line in _STORE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _ruling_ids() -> set[str]:
    ids: set[str] = set()
    for line in _RULINGS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            ids.add(json.loads(line)["case_id"])
    return ids


# --------------------------------------------------------------------------- #
# committed store の不変条件
# --------------------------------------------------------------------------- #
def test_store_rows_validate_and_unique():
    """store 全行が PrecedentStoreEntry として valid・case_id ユニーク (dup0)。"""
    from juricode_shared import PrecedentStoreEntry

    rows = _load_store()
    assert len(rows) == 25, f"expected 25 precedents, got {len(rows)}"
    seen: set[str] = set()
    for r in rows:
        obj = PrecedentStoreEntry.model_validate(r)
        assert obj.case_type == "precedent"
        assert obj.case_id not in seen, f"duplicate case_id in store: {obj.case_id}"
        seen.add(obj.case_id)


def test_case_id_prefix_matches_court_level():
    """case_id prefix (scj/hcj/dcj) が court の裁判所種別と整合する。"""
    rows = _load_store()
    for r in rows:
        cid, court = r["case_id"], r["court"]
        if cid.startswith("scj-"):
            assert court == "最高裁判所", f"{cid}: scj but court={court}"
        elif cid.startswith("hcj-"):
            assert court.endswith("高等裁判所"), f"{cid}: hcj but court={court}"
        elif cid.startswith("dcj-"):
            assert court.endswith("地方裁判所"), f"{cid}: dcj but court={court}"
        else:
            pytest.fail(f"unexpected precedent prefix: {cid}")


def test_case_id_no_double_hyphen_and_no_date_leak():
    """case_id に連続ハイフンが無く、iso 日付の後ろに日付数字 (月/日) が混入しない。"""
    rows = _load_store()
    for r in rows:
        cid = r["case_id"]
        assert "--" not in cid, f"double hyphen in {cid}"
        # {prefix}-{YYYY}-{MM}-{DD}-{slug}-... の 4 セグメント目以降 (slug 以降) に
        # 掲載誌番号のみが載る。iso 日付は先頭 3 セグメントに限定される。
        tail = cid.split("-", 4)[4]  # slug + 巻号頁
        assert not tail[0].isdigit(), f"{cid}: slug segment starts with a digit ({tail})"


def test_cited_by_all_exist_in_rulings():
    """cited_by の裁決 case_id は全て rulings.jsonl に実在する (越境0)。"""
    ruling_ids = _ruling_ids()
    for r in _load_store():
        for cb in r.get("cited_by", []):
            assert cb in ruling_ids, f"{r['case_id']}: cited_by {cb} not in rulings store"


def test_multi_cited_precedents_preserved():
    """被引用>1 の判例が cited_by に複数エントリを忠実保持する (2 件)。"""
    rows = _load_store()
    multi = [r for r in rows if len(r.get("cited_by", [])) > 1]
    assert len(multi) == 2, f"expected 2 multi-cited precedents, got {len(multi)}"
    for r in multi:
        assert len(r["cited_by"]) == len(set(r["cited_by"])), f"{r['case_id']}: dup cited_by"


# --------------------------------------------------------------------------- #
# 導出関数の境界 (和暦 + 全角 + case_id 合成)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("最高裁平成5年11月25日第一小法廷判決（民集47巻9号5278頁）", "1993-11-25"),
        ("最高裁昭和39年10月15日第一小法廷判決（民集18巻8号1671頁）", "1964-10-15"),
        # 元号略記 (「平29年」) を正式名へ正規化して変換できる
        ("東京地裁平29年1月18日判決（税資267号順号12956）", "2017-01-18"),
        # 全角年数字 (「平成５年」) を正規化して変換できる
        ("最高裁平成５年11月25日第一小法廷判決（民集47巻9号5278頁）", "1993-11-25"),
    ],
)
def test_parse_precedent_decision_date(raw, expected):
    mod = _load_builder()
    assert mod.parse_precedent_decision_date(raw) == expected


def test_parse_precedent_decision_date_fail_loud():
    """日付が抽出できない文字列は握りつぶさず ValueError を投げる。"""
    mod = _load_builder()
    with pytest.raises(ValueError):
        mod.parse_precedent_decision_date("東京地裁判決（税資267号順号12956）")


@pytest.mark.parametrize(
    "prefix, iso, citation, expected",
    [
        ("scj", "1993-11-25", "民集47巻9号5278頁", "scj-1993-11-25-minshu-47-9-5278"),
        # 元号略記由来の全角号 (「８号」) を正規化してから巻号頁を拾う
        ("dcj", "1996-03-22", "税資２１５号960頁", "dcj-1996-03-22-zeishi-215-960"),
        # 「順号」は数字を持たないため巻号頁に影響しない
        ("hcj", "2004-03-12", "税資254号順号9593", "hcj-2004-03-12-zeishi-254-9593"),
    ],
)
def test_generate_precedent_case_id(prefix, iso, citation, expected):
    mod = _load_builder()
    assert mod.generate_precedent_case_id(prefix, iso, citation) == expected


@pytest.mark.parametrize(
    "raw, court, court_en, prefix",
    [
        (
            "最高裁平成5年11月25日第一小法廷判決（民集47巻9号5278頁）",
            "最高裁判所",
            "Supreme Court of Japan",
            "scj",
        ),
        (
            "東京高裁平成16年12月13日判決（税資254号順号9859）",
            "東京高等裁判所",
            "Tokyo High Court",
            "hcj",
        ),
        (
            "神戸地裁平成17年5月25日判決（税資255号順号10039）",
            "神戸地方裁判所",
            "Kobe District Court",
            "dcj",
        ),
    ],
)
def test_parse_court(raw, court, court_en, prefix):
    mod = _load_builder()
    assert mod.parse_court(raw) == (court, court_en, prefix)


def test_parse_court_unregistered_city_fail_loud():
    """_CITY_EN 未登録の市区は fail-loud (silent な日本語 court_en 混入を防ぐ)。"""
    mod = _load_builder()
    with pytest.raises(ValueError):
        mod.parse_court("那覇地裁平成20年1月31日判決（税資258号順号10880）")


# --------------------------------------------------------------------------- #
# 生成の決定論 (再実行で byte 同一)
# --------------------------------------------------------------------------- #
def test_generation_is_idempotent():
    """rulings.jsonl から再導出した結果が committed store と byte 一致する。"""
    mod = _load_builder()
    edges = mod.collect_judgment_refs(_RULINGS)
    entries = mod.build_entries(edges)
    regenerated = "".join(
        json.dumps(e.model_dump(mode="json"), ensure_ascii=False) + "\n" for e in entries
    )
    assert regenerated == _STORE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# schema: precedent url optional / ruling url required (if/then)
# --------------------------------------------------------------------------- #
def _base_record(case_type: str) -> dict:
    rec = {
        "case_id": ("scj" if case_type == "precedent" else "ntt") + "-1993-11-25-x-1",
        "case_type": case_type,
        "decision_date": "1993-11-25",
        "relevance": "medium",
        "source_license": "public-domain",
        "summary_source": "none",
    }
    if case_type == "precedent":
        rec.update(
            court="最高裁判所", court_en="Supreme Court of Japan", citation="民集47巻9号5278頁"
        )
    return rec


def test_schema_precedent_url_optional_ruling_required():
    """case-link schema: precedent は url 省略で valid・ruling は url 欠落で invalid。"""
    import jsonschema

    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))

    # precedent: url 省略で valid
    jsonschema.validate(_base_record("precedent"), schema)

    # ruling: url 欠落は invalid (if/then で required)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_record("ruling"), schema)

    # ruling: url 付与で valid
    ruling_ok = _base_record("ruling")
    ruling_ok["url"] = "https://www.kfs.go.jp/service/JP/example"
    jsonschema.validate(ruling_ok, schema)

"""Unit tests for the /chat machine verification layer (PoC P2, guards.py).

Pure-Python (no numpy / no network): the guard functions are副作用なしの純関数なので
CI がモックだけで走る。ここでは policy ガード G3-G6 と、core (G1/G2) + policy を合成する
run_all_guards を固定する。core (G1/G2/valid_citations_only/snap) の単体テストは
packages/juricode-verifier/tests が正本 (本ファイルからは合成経由でのみ検査)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import guards as G  # noqa: E402

# ---- G3: 断定禁止 (禁止表現辞書の各パターンを網羅・T4) ----

# 各辞書パターンにマッチする代表文字列 (名前は FORBIDDEN_ASSERTION_PATTERNS のキー)。
_G3_EXAMPLES: dict[str, str] = {
    "kanarazu": "この場合は必ず適用されます",
    "kakujitsu_ni": "確実に否認されます",
    "zettai_ni": "絶対に問題となります",
    "machigainaku": "間違いなく該当します",
    "mondai_arimasen": "この処理は問題ありません",
    "mondai_nai": "この処理は問題ない",
    "hinin_saremasen": "税務調査でも否認されません",
    "hinin_sarenai": "税務調査でも否認されない",
    "to_dangen": "該当すると断言できます",
    "hoshou_shimasu": "適用を保証します",
    "hyaku_percent": "100%適用されます",
}


def test_g3_dictionary_covers_every_pattern():
    # 各パターン名にテスト例があること (辞書追加時のカバレッジ漏れを防ぐ)。
    assert set(_G3_EXAMPLES) == set(G.FORBIDDEN_ASSERTION_PATTERNS)


def test_g3_each_forbidden_pattern_is_detected():
    for name, example in _G3_EXAMPLES.items():
        v = G.scan_forbidden_assertions(example)
        codes = {x.code for x in v}
        assert codes == {"G3"}, f"pattern {name!r} not detected in {example!r}"


def test_g3_clean_answer_has_no_violation():
    clean = "この規定に該当する可能性があります。根拠は引用の本文の通りです。"
    assert G.scan_forbidden_assertions(clean) == []


# ---- G4: 数値非生成 (T5) ----


def test_g4_detects_monetary_amounts():
    for s in ["合計1,000,000円になります", "税額は50万円です", "評価額は3億円と考えられます"]:
        v = G.scan_generated_numbers(s)
        assert [x.code for x in v] == ["G4"], f"money not detected in {s!r}"


def test_g4_does_not_flag_article_or_directive_numbers():
    # 条番号・通達番号・パーセントは金額でない (円 接尾辞なし) -> 違反ゼロ。
    for s in ["法人税基本通達9-2-9を参照", "刑法第36条", "税率は10パーセントです"]:
        assert G.scan_generated_numbers(s) == [], f"false positive on {s!r}"


# ---- G5: 時制ディスクレーマ (T6) ----


def test_g5_rejects_empty_disclaimer():
    assert [x.code for x in G.check_disclaimer("")] == ["G5"]
    assert [x.code for x in G.check_disclaimer(None)] == ["G5"]
    assert [x.code for x in G.check_disclaimer("   ")] == ["G5"]


def test_g5_accepts_nonempty_disclaimer():
    assert G.check_disclaimer("参照時点の法令に基づく情報です") == []


# ---- G6: 税理士法の橋渡し (T6) ----


def test_g6_rejects_missing_or_altered_bridge():
    assert [x.code for x in G.check_tax_law_bridge("")] == ["G6"]
    assert [x.code for x in G.check_tax_law_bridge("勝手に書き換えた文")] == ["G6"]


def test_g6_accepts_exact_template():
    assert G.check_tax_law_bridge(G.TAX_LAW_BRIDGE) == []


# ---- 集約 ----


def test_run_all_guards_clean_output_passes():
    texts = {"c1": "第一条 この法律は正当防衛について定める。"}
    v = G.run_all_guards(
        verdict="該当",
        answer="関連する規定があります。",
        citations=[{"chunk_id": "c1", "quote": "正当防衛について定める"}],
        disclaimer_tense="参照時点の法令に基づく情報です",
        notice=G.TAX_LAW_BRIDGE,
        allowed_chunk_ids={"c1"},
        chunk_texts=texts,
    )
    assert v == []


def test_run_all_guards_bad_verdict_flags_g3():
    v = G.run_all_guards(
        verdict="たぶん該当",
        answer="関連する規定があります。",
        citations=[],
        disclaimer_tense="参照時点の法令に基づく情報です",
        notice=G.TAX_LAW_BRIDGE,
        allowed_chunk_ids=set(),
        chunk_texts={},
    )
    assert any(x.code == "G3" for x in v)


def test_run_all_guards_composes_core_g1_g2():
    # core (juricode_verifier) の G1/G2 が合成経由で効いていることの結線検査。
    # (G1/G2 単体の網羅は packages/juricode-verifier/tests が正本。)
    texts = {"c1": "第一条 この法律は正当防衛について定める。"}
    v = G.run_all_guards(
        verdict="該当",
        answer="関連する規定があります。",
        citations=[
            {"chunk_id": "ghost", "quote": "x"},  # G1
            {"chunk_id": "c1", "quote": "原文にない語"},  # G2
        ],
        disclaimer_tense="参照時点の法令に基づく情報です",
        notice=G.TAX_LAW_BRIDGE,
        allowed_chunk_ids={"c1"},
        chunk_texts=texts,
    )
    codes = sorted(x.code for x in v)
    assert codes == ["G1", "G2", "G2"]  # ghost は body 無しで G2 にも二重計上

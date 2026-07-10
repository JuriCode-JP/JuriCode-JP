"""Tests for the RAG 忠実性 Layer1 pilot 純関数 (torch / Gemini 非依存, hermetic).

Coverage:
  - layer1_build_corpora.article_texts: B0=生 / A=メタ+canonicalize / 条連結 join (§A-4)
  - layer1_build_corpora._meta_prefix: 法令名/条/項 prefix (caption 無し)
  - layer1_run_pilot._query_text: raw / canon (canonicalize) / normalize (略称展開)
  - layer1_run_pilot._law_of: article_id -> 法令 prefix
  - layer1_stats._mcnemar_exact / _bootstrap_ci / compare: paired 統計 + §A-0 adopted filter

これらは実埋め込み / 実モデルを伴わない純ロジック。実 retrieval (Gemini) と reranker
(torch) は環境依存ゆえ CI 対象外 (結果 json / raw ログを committed 成果物として別途監査)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# tools/embed/ を import 可能に
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# juricode_shared / _canonicalize 解決 (retrieve import 経由)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "shared" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "parse"))

import importlib.util  # noqa: E402


def _load(modname, filename):
    path = Path(__file__).resolve().parents[1] / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    # dataclass の型解決は sys.modules 経由ゆえ exec 前に登録する必要がある
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


BC = _load("layer1_build_corpora", "layer1_build_corpora.py")
RP = _load("layer1_run_pilot", "layer1_run_pilot.py")
ST = _load("layer1_stats", "layer1_stats.py")


# ---------------- article_texts (§A-4 / A=構造化 B0=生) ----------------


def test_article_texts_b0_is_raw_a_is_meta_plus_canonical():
    paras = ((1, "本文一　テスト"), (2, "本文二"))  # 全角空白入り (canonicalize で半角化)
    t = BC.article_texts("民法", "90", paras)
    # B0-項 は生 (全角空白そのまま・メタ無し)
    assert t["b0_para"][0] == (1, "本文一　テスト")
    # A-項 = メタ prefix + canonicalize(生)
    assert t["a_para"][0][1].startswith("民法 第90条 第1項\n")
    assert "本文一 テスト" in t["a_para"][0][1]  # 全角空白 -> 半角
    assert "　" not in t["a_para"][0][1].split("\n", 1)[1]  # 本文側に全角空白なし


def test_article_texts_article_level_join_identical():
    paras = ((1, "A"), (2, "B"))
    t = BC.article_texts("刑法", "36", paras)
    # 条-level は項本文を "\n\n" で連結 (A/B0 同一 join)
    assert t["b0_art"] == "A\n\nB"
    assert t["a_art"].startswith("刑法 第36条\n")
    assert t["a_art"].endswith("A\n\nB")  # canonicalize は A/B 内容を非改変 (改行のみ)


def test_meta_prefix_no_caption():
    assert BC._meta_prefix("民法", "90", None) == "民法 第90条"
    assert BC._meta_prefix("民法", "90", 2) == "民法 第90条 第2項"
    assert BC._meta_prefix("刑法", "185-7", None) == "刑法 第185-7条"


def test_token_limit_constant():
    assert BC.TOKEN_LIMIT == 2048


# ---------------- _query_text (クエリ正規化軸) ----------------


def test_query_text_raw_passthrough():
    assert RP._query_text("給与所得とは", "raw", False) == "給与所得とは"


def test_query_text_canon_applies_canonicalize():
    # canonicalize: 全角空白 -> 半角
    assert RP._query_text("A　B", "canon", False) == "A B"


def test_query_text_normalize_expands_abbrev():
    out = RP._query_text("金商法とは", "raw", True)
    assert "金融商品取引法" in out  # 略称展開 (normalize_legal_query)


def test_law_of():
    assert RP._law_of("shakuchi-shakka-hou-art-13") == "shakuchi-shakka-hou"
    assert RP._law_of("kinsho-hou-art-185-7") == "kinsho-hou"


# ---------------- 統計 (McNemar / bootstrap / compare) ----------------


def test_mcnemar_exact_edge_cases():
    assert ST._mcnemar_exact(0, 0) == 1.0
    # 全 discordant が片側 (b=10,c=0) -> 2 * 0.5^10
    assert abs(ST._mcnemar_exact(10, 0) - 2 * (0.5**10)) < 1e-9
    # 対称 -> 1.0 (最大)
    assert ST._mcnemar_exact(5, 5) == 1.0


def test_bootstrap_ci_deterministic_and_bounded():
    lo, hi = ST._bootstrap_ci([1.0] * 30)
    assert lo == 1.0 and hi == 1.0  # 全て +1 -> CI は 1
    lo2, hi2 = ST._bootstrap_ci([1.0, 0.0, 1.0, 0.0] * 10)
    assert 0.0 <= lo2 <= hi2 <= 1.0
    # seed 固定 = 決定論
    assert ST._bootstrap_ci([1.0, -1.0, 1.0, 0.0]) == ST._bootstrap_ci([1.0, -1.0, 1.0, 0.0])


def test_compare_adopted_filter_and_recall(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()

    def write(tag, rows):
        with (raw / f"{tag}.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # A: q1 hit@1, q2 miss, q3 非採用 / B: q1 miss, q2 miss, q3 hit(非採用ゆえ無視)
    write(
        "A__raw__baseline",
        [
            {"id": "q1", "adopted": True, "first_match_rank": 1},
            {"id": "q2", "adopted": True, "first_match_rank": None},
            {"id": "q3", "adopted": False, "first_match_rank": None},
        ],
    )
    write(
        "B__raw__baseline",
        [
            {"id": "q1", "adopted": True, "first_match_rank": None},
            {"id": "q2", "adopted": True, "first_match_rank": None},
            {"id": "q3", "adopted": True, "first_match_rank": 1},
        ],
    )
    res = ST.compare(raw, "A__raw__baseline", "B__raw__baseline", 100, 100)
    # 非採用 q3 は A 側 adopted=False ゆえ除外 -> n_paired=2 (q1,q2)
    assert res["n_paired"] == 2
    assert res["recall_at_10_a"] == 0.5  # q1 hit
    assert res["recall_at_10_b"] == 0.0
    assert res["recall_at_10_delta"] == 0.5
    assert res["mcnemar_b_a_hit_b_miss"] == 1
    assert res["mcnemar_c_a_miss_b_hit"] == 0

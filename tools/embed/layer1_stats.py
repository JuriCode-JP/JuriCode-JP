#!/usr/bin/env python3
"""layer1_stats.py -- Layer1 pilot の raw ログから paired 統計を計算する.

raw ログ (per-query first_match_rank) を条件間で query id ペアリングし、以下を出す:
  - Recall@10 (0/1) の paired 差分 → McNemar (exact binomial) + bootstrap CI
  - MRR / Raw Rank (非ヒット penalty=総条文数) → Wilcoxon (hit-pair conditional 主)
  - 法令別内訳

Why: N が小さいパイロットでは p 値単独で断定しない (§E)。効果量 (ΔRecall・ΔMRR) を主報告し、
McNemar/Wilcoxon/bootstrap CI を補助として併記する。統計は raw ログ (実物) からのみ計算し、
集計 json は独立検算対象 (自己申告しない)。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parent.parent.parent


def _load_raw(raw_dir: Path, tag: str) -> dict[str, dict]:
    """tag = 'cond__qmode__ablation' の raw jsonl を {id: row} で返す."""
    path = raw_dir / f"{tag}.jsonl"
    out = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["id"]] = r
    return out


def _mcnemar_exact(b: int, c: int) -> float:
    """McNemar exact (two-sided binomial) p-value for discordant pairs (b, c)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # two-sided exact: 2 * sum_{i=0..k} C(n,i) 0.5^n, capped at 1
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5**n)
    return min(1.0, 2.0 * tail)


def _bootstrap_ci(diffs: list[float], iters: int = 10000, seed: int = 12345) -> tuple[float, float]:
    """percentile 95% CI of the mean of per-query diffs (paired bootstrap).

    seed 固定で決定論的。Math.random 非依存 (workflow 制約とは無関係の通常実行)。
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    arr = np.asarray(diffs, dtype=float)
    n = len(arr)
    if n == 0:
        return (float("nan"), float("nan"))
    means = arr[rng.integers(0, n, size=(iters, n))].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def _rank_or_penalty(rank, penalty: int) -> float:
    return float(rank) if rank is not None else float(penalty)


def compare(raw_dir: Path, tag_a: str, tag_b: str, penalty_a: int, penalty_b: int) -> dict:
    a = _load_raw(raw_dir, tag_a)
    b = _load_raw(raw_dir, tag_b)
    # §A-0: 両条件で採用された問のみをペアリング (非採用=gold corpus 非在/over-token 除外)。
    ids = [i for i in a if i in b and a[i].get("adopted", True) and b[i].get("adopted", True)]

    # paired hit@10
    hit_a = {i: (a[i]["first_match_rank"] is not None) for i in ids}
    hit_b = {i: (b[i]["first_match_rank"] is not None) for i in ids}
    # McNemar discordant
    b_only = sum(1 for i in ids if hit_a[i] and not hit_b[i])
    c_only = sum(1 for i in ids if not hit_a[i] and hit_b[i])
    p_mcnemar = _mcnemar_exact(b_only, c_only)

    recall_a = sum(hit_a.values()) / len(ids)
    recall_b = sum(hit_b.values()) / len(ids)
    recall_diffs = [(1.0 if hit_a[i] else 0.0) - (1.0 if hit_b[i] else 0.0) for i in ids]
    ci_recall = _bootstrap_ci(recall_diffs)

    # MRR
    def rr(row):
        r = row["first_match_rank"]
        return 1.0 / r if r else 0.0

    mrr_a = sum(rr(a[i]) for i in ids) / len(ids)
    mrr_b = sum(rr(b[i]) for i in ids) / len(ids)
    mrr_diffs = [rr(a[i]) - rr(b[i]) for i in ids]
    ci_mrr = _bootstrap_ci(mrr_diffs)

    # Raw Rank: conditional (both hit) Wilcoxon 主
    both_hit = [i for i in ids if hit_a[i] and hit_b[i]]
    wilcoxon_p = None
    try:
        from scipy.stats import wilcoxon

        if both_hit:
            ra = [a[i]["first_match_rank"] for i in both_hit]
            rb = [b[i]["first_match_rank"] for i in both_hit]
            if any(x != y for x, y in zip(ra, rb, strict=False)):
                wilcoxon_p = float(wilcoxon(ra, rb).pvalue)
    except Exception:
        wilcoxon_p = None

    return {
        "tag_a": tag_a,
        "tag_b": tag_b,
        "n_paired": len(ids),
        "recall_at_10_a": recall_a,
        "recall_at_10_b": recall_b,
        "recall_at_10_delta": recall_a - recall_b,
        "recall_delta_bootstrap_ci95": ci_recall,
        "mcnemar_b_a_hit_b_miss": b_only,
        "mcnemar_c_a_miss_b_hit": c_only,
        "mcnemar_exact_p": p_mcnemar,
        "mrr_a": mrr_a,
        "mrr_b": mrr_b,
        "mrr_delta": mrr_a - mrr_b,
        "mrr_delta_bootstrap_ci95": ci_mrr,
        "n_both_hit": len(both_hit),
        "wilcoxon_rank_conditional_p": wilcoxon_p,
    }


# 総条文数 (Raw Rank penalty 用) - corpus article 数
def _corpus_size(prefix: Path) -> int:
    meta = prefix.parent / (prefix.name + ".meta.jsonl")
    return sum(1 for line in meta.open(encoding="utf-8") if line.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--results-dir",
        type=Path,
        default=_REPO / "benchmarks" / "results" / "layer1-structured-vs-raw",
    )
    ap.add_argument("--corpus-dir", type=Path, default=_REPO / "build" / "layer1-rawtext")
    args = ap.parse_args()
    raw_dir = args.results_dir / "raw"

    sizes = {
        c: _corpus_size(args.corpus_dir / f"layer1-{c}-embedded")
        for c in ("A-para", "A-art", "B0-para", "B0-art")
    }

    # 主要 paired 比較 (全 qmode×ablation の組で)
    QMODES = ("raw", "canon")
    ABLATIONS = ("baseline", "normalize", "reranker", "both")
    PAIRS = [
        ("A-para", "B0-para", "structured_vs_raw_paragraph (PRIMARY)"),
        ("A-art", "B0-art", "structured_vs_raw_article"),
        ("A-para", "A-art", "granularity_structured (para_vs_art)"),
        ("B0-para", "B0-art", "granularity_raw (para_vs_art)"),
    ]
    results = []
    for ca, cb, label in PAIRS:
        for qmode in QMODES:
            for abl in ABLATIONS:
                tag_a = f"{ca}__{qmode}__{abl}"
                tag_b = f"{cb}__{qmode}__{abl}"
                if not (raw_dir / f"{tag_a}.jsonl").exists():
                    continue
                res = compare(raw_dir, tag_a, tag_b, sizes[ca], sizes[cb])
                res["comparison"] = label
                res["query_mode"] = qmode
                res["ablation"] = abl
                results.append(res)

    out = args.results_dir / "stats.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump({"corpus_sizes": sizes, "comparisons": results}, fh, ensure_ascii=False, indent=2)

    # print primary
    print("=== PRIMARY: A-para vs B0-para (structured effect @ paragraph) ===")
    for r in results:
        if r["comparison"].startswith("structured_vs_raw_paragraph"):
            print(
                f"  {r['query_mode']:5s}/{r['ablation']:9s} "
                f"ΔR@10={r['recall_at_10_delta']:+.3f} CI{tuple(round(x, 3) for x in r['recall_delta_bootstrap_ci95'])} "
                f"ΔMRR={r['mrr_delta']:+.3f} McN_p={r['mcnemar_exact_p']:.3f} "
                f"Wilcox_p={r['wilcoxon_rank_conditional_p']}"
            )
    print(f"\nstats -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

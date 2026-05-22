#!/usr/bin/env python3
"""run-ablation.py — 4 設定 (baseline / +normalize / +reranker / +both) を一気実行.

設定:
    1. baseline           : Gemini dense 単独
    2. normalize-query    : + 法令略称展開・漢数字版追加
    3. reranker           : + Cross-encoder (bge-reranker-v2-m3) で top-30 を re-rank
    4. normalize+reranker : 両方適用

使い方:
    python tools/embed/run-ablation.py \
        --embedded build/juricode-bq-11760-embedded \
        --bm25-corpus build/juricode-bq-11760.jsonl \
        --eval-set <files...> \
        --output benchmarks/results/2026-05-21-ablation.json

注: --bm25-corpus は reranker 用の corpus jsonl としても流用される (text フィールド読込).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_one(
    label,
    embedded,
    eval_set,
    top_k,
    normalize,
    hybrid,
    bm25_corpus,
    rrf_k,
    reranker=False,
    reranker_corpus=None,
    reranker_model="BAAI/bge-reranker-v2-m3",
    reranker_candidates=30,
):
    """retrieve.py を 1 設定で実行し、metrics を抽出."""
    cmd = [
        sys.executable,
        "tools/embed/retrieve.py",
        "--embedded",
        str(embedded),
        "--eval-set",
        *(str(p) for p in eval_set),
        "--top-k",
        str(top_k),
    ]
    if normalize:
        cmd.append("--normalize-query")
    if hybrid:
        cmd.append("--hybrid-bm25")
        cmd.extend(["--bm25-corpus", str(bm25_corpus)])
        cmd.extend(["--rrf-k", str(rrf_k)])
    if reranker:
        cmd.append("--reranker")
        rc = reranker_corpus or bm25_corpus
        if rc:
            cmd.extend(["--reranker-corpus", str(rc)])
        cmd.extend(["--reranker-model", reranker_model])
        cmd.extend(["--reranker-candidates", str(reranker_candidates)])

    print(f"\n=== [{label}] running ===", file=sys.stderr)
    print(f"  cmd: {' '.join(cmd)}", file=sys.stderr)

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print(log, file=sys.stderr)

    m_r1 = re.search(r"Recall@1\s*:\s*(\d+)/(\d+)\s*=\s*([\d.]+)%", log)
    m_r3 = re.search(r"Recall@3\s*:\s*(\d+)/(\d+)\s*=\s*([\d.]+)%", log)
    m_r10 = re.search(r"Recall@10\s*:\s*(\d+)/(\d+)\s*=\s*([\d.]+)%", log)
    m_mrr = re.search(r"MRR\s*:\s*([\d.]+)", log)
    m_n = re.search(r"N \(queries\)\s*:\s*(\d+)", log)

    if not (m_r1 and m_r3 and m_r10 and m_mrr and m_n):
        return {"label": label, "error": "metrics not parsed", "log_tail": log[-2000:]}

    return {
        "label": label,
        "settings": {
            "normalize_query": normalize,
            "hybrid_bm25": hybrid,
            "reranker": reranker,
            "rrf_k": rrf_k if hybrid else None,
            "reranker_model": reranker_model if reranker else None,
            "reranker_candidates": reranker_candidates if reranker else None,
        },
        "n_queries": int(m_n.group(1)),
        "recall_at_1": float(m_r1.group(3)) / 100,
        "recall_at_3": float(m_r3.group(3)) / 100,
        "recall_at_10": float(m_r10.group(3)) / 100,
        "mrr": float(m_mrr.group(1)),
        "recall_at_1_count": int(m_r1.group(1)),
        "recall_at_3_count": int(m_r3.group(1)),
        "recall_at_10_count": int(m_r10.group(1)),
    }


def main():
    ap = argparse.ArgumentParser(description="Ablation runner for retrieve.py.")
    ap.add_argument("--embedded", type=Path, required=True)
    ap.add_argument("--eval-set", type=Path, nargs="+", required=True)
    ap.add_argument(
        "--bm25-corpus",
        type=Path,
        required=True,
        help="BM25/reranker 用 corpus jsonl (text を読み込む)",
    )
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--rrf-k", type=int, default=60)
    ap.add_argument(
        "--reranker-corpus",
        type=Path,
        default=None,
        help="Reranker 用 corpus (デフォルトは --bm25-corpus を流用)",
    )
    ap.add_argument(
        "--reranker-model",
        type=str,
        default="BAAI/bge-reranker-v2-m3",
        help="Cross-encoder model ID",
    )
    ap.add_argument(
        "--reranker-candidates", type=int, default=30, help="reranker に渡す dense top-N の N"
    )
    ap.add_argument("--output", type=Path, default=Path("benchmarks/results/ablation.json"))
    args = ap.parse_args()

    settings = [
        # (label, normalize, hybrid, reranker)
        ("baseline", False, False, False),
        ("normalize-query", True, False, False),
        ("reranker", False, False, True),
        ("normalize+reranker", True, False, True),
    ]

    results = []
    for label, normalize, hybrid, reranker in settings:
        result = run_one(
            label,
            args.embedded,
            args.eval_set,
            args.top_k,
            normalize,
            hybrid,
            args.bm25_corpus,
            args.rrf_k,
            reranker=reranker,
            reranker_corpus=args.reranker_corpus,
            reranker_model=args.reranker_model,
            reranker_candidates=args.reranker_candidates,
        )
        results.append(result)

    # Pretty print summary table
    print("\n" + "=" * 90, file=sys.stderr)
    print(
        f"  {'Setting':22} {'N':>4} {'R@1':>8} {'R@3':>8} {'R@10':>8} {'MRR':>8}", file=sys.stderr
    )
    print("=" * 90, file=sys.stderr)
    baseline = results[0]
    for r in results:
        if "error" in r:
            print(f"  {r['label']:22} ERROR: {r['error']}", file=sys.stderr)
            continue
        n = r["n_queries"]
        r1 = r["recall_at_1"]
        r3 = r["recall_at_3"]
        r10 = r["recall_at_10"]
        mrr = r["mrr"]
        if r["label"] == "baseline":
            delta = ""
        else:
            dr1 = r1 - baseline["recall_at_1"]
            delta = f"  (Δ@1={dr1:+.1%})"
        print(
            f"  {r['label']:22} {n:>4} {r1:>7.1%} {r3:>7.1%} {r10:>7.1%} {mrr:>7.3f}{delta}",
            file=sys.stderr,
        )
    print("=" * 90, file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": f"ablation-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "eval_set_paths": [str(p) for p in args.eval_set],
        "embedded": str(args.embedded),
        "bm25_corpus": str(args.bm25_corpus),
        "reranker_model": args.reranker_model,
        "reranker_candidates": args.reranker_candidates,
        "results": results,
    }
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

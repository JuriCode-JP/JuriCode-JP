#!/usr/bin/env python3
"""A3-M: layer contamination gate (measure-only). v7 vs v8 honbun recall + new-layer hit.

Why:
    v8 index merges new corpora (sochi-hou honbun, sochi tsutatsu, re-chunking) on top
    of the v7 index. This harness MEASURES (does not lock a threshold) whether v8 degrades
    retrieval of honbun (law-body) gold relative to v7, using a corpus-gold filter so the
    comparison is fair (only gold present in BOTH corpora is scored). It reuses retrieve.py's
    exact retrieval math (dense cosine + BM25 char-ngram RRF hybrid) and only adds the
    filter / per-law breakdown / reverse-contamination sampling that the A3-M DoD requires.

    measure -> STOP -> the A-3 pass line is locked from the observed numbers.

Outputs (all under build/v8-a3-results/, gitignored):
    v7.txt, v8.txt        human-readable per-index summaries
    compare.json          machine record: v7 vs v8 recall@k, per-law, adopted N,
                          new-layer hit rate, reverse-contamination samples

Run:
    python tools/embed/a3_contamination_eval.py
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # runtime False -> numpy is not imported (the module still loads without it);
    import numpy as np  # names the annotation type for static analysis (ruff F821)

# retrieve.py lives in the same directory; reuse its committed retrieval machinery so the
# math is identical to the production tool (no re-implementation drift).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrieve as R

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "build" / "v8-a3-results"

V7_PREFIX = REPO / "build" / "embeddings" / "v0.2-aug-v7-gemini"
V8_PREFIX = REPO / "build" / "embeddings" / "v0.2-aug-v8-gemini"
V7_CORPUS = REPO / "build" / "corpus-v0.2.jsonl"
V8_CORPUS = REPO / "build" / "corpus-v8-embed.jsonl"

TOP_K = 20  # need width >= 20 so recall@20 is real (not degenerate to recall@10)
CANDIDATE_POOL = 60  # mirrors retrieve.py: max(top_k*3, 30) for top_k=20
RRF_K = 60

# Main eval sets (honbun gold) tagged by law group for the per-law breakdown.
MAIN_EVAL = [
    ("tax", REPO / "data" / "eval-set" / "tax.jsonl"),
    ("tax", REPO / "data" / "eval-set" / "tax-honbun-local" / "g1-local.jsonl"),
    ("kinsho", REPO / "data" / "eval-set" / "lawqa-jp" / "commercial-kinsho.jsonl"),
    ("pharma", REPO / "data" / "eval-set" / "lawqa-jp" / "pharma.jsonl"),
    ("real-estate", REPO / "data" / "eval-set" / "lawqa-jp" / "real-estate.jsonl"),
]
# New-layer eval sets (v8-only entities: tsutatsu directives / taxanswer QA).
NEWLAYER_EVAL = [
    ("tsutatsu", REPO / "data" / "eval-set" / "tax-tsutatsu.jsonl"),
    ("taxanswer", REPO / "data" / "eval-set" / "tax-taxanswer.jsonl"),
]

K_CUTS = [1, 3, 5, 10, 20]


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _expected_newlayer(q: dict) -> set[str]:
    """Match key for a new-layer query (mirrors retrieve.py._expected_ids fallbacks)."""
    ids: set[str] = set(q.get("expected_article_ids") or [])
    did = q.get("expected_directive_id")
    if did:
        ids.add(did)
    qa = q.get("expected_qa_code")
    if qa:
        ids.add(f"hojin-taxanswer-{qa}")
    return ids


def _present_ids(records: list[dict]) -> tuple[set[str], set[str]]:
    aids = {r["article_id"] for r in records if r.get("article_id")}
    cids = {r["chunk_id"] for r in records if r.get("chunk_id")}
    return aids, cids


def _match_keys(records: list[dict]) -> list[str]:
    """Per-record match key: article_id, else chunk_id (mirrors aggregate_metrics fallback)."""
    out = []
    for r in records:
        aid = r.get("article_id")
        out.append(aid if aid is not None else (r.get("chunk_id") or ""))
    return out


def _recall_row(top_ids: list[str], expected: set[str]) -> dict:
    rank = None
    for i, k in enumerate(top_ids, start=1):
        if R.match_gold(k, expected):
            rank = i
            break
    return {c: (1 if (rank is not None and rank <= c) else 0) for c in K_CUTS} | {"rank": rank}


def _aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    agg = {f"recall_{c}": 0 for c in K_CUTS}
    for row in rows:
        for c in K_CUTS:
            agg[f"recall_{c}"] += row[c]
    out = {"n": n}
    for c in K_CUTS:
        hit = agg[f"recall_{c}"]
        out[f"recall_{c}"] = {"hit": hit, "pct": (hit / n) if n else 0.0}
    return out


def _dense_top(query_matrix, matrix) -> np.ndarray:
    _sims, dense_top = R._cosine_topk(query_matrix, matrix, CANDIDATE_POOL)
    return dense_top


def _hybrid_top(questions, dense_top, corpus_path: Path, result_k: int = TOP_K) -> np.ndarray:
    index_info, tfidf_matrix, _ = R.build_tfidf_index(corpus_path)
    _bm25_sims, bm25_top = R.bm25_topk_per_query(
        questions, index_info, tfidf_matrix, CANDIDATE_POOL
    )
    return R.rrf_combine_per_query(dense_top[:, :CANDIDATE_POOL], bm25_top, result_k, k_rrf=RRF_K)


def _rows_for(top_idx, match_keys, expected_per_query) -> list[dict]:
    rows = []
    for qi, expected in enumerate(expected_per_query):
        top_ids = []
        for idx in top_idx[qi][:TOP_K]:
            i = int(idx)
            top_ids.append(match_keys[i] if i >= 0 else "")
        rows.append(_recall_row(top_ids, expected))
    return rows


def _encode_queries_cached(questions: list[str], state: dict) -> np.ndarray:
    """Encode once via Gemini RETRIEVAL_QUERY; cache to npy keyed by the question list."""
    import numpy as np  # lazy import

    cache_npy = OUT / "query_emb.npy"
    cache_q = OUT / "query_list.json"
    if cache_npy.exists() and cache_q.exists():
        cached = json.loads(cache_q.read_text(encoding="utf-8"))
        if cached == questions:
            print(
                f"  [encode] reuse cache {cache_npy.name} ({len(questions)} queries)",
                file=sys.stderr,
            )
            return np.load(cache_npy)
    print(f"  [encode] Gemini RETRIEVAL_QUERY x {len(questions)} ...", file=sys.stderr)
    mat = R._encode_queries(questions, state)
    np.save(cache_npy, mat)
    cache_q.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
    return mat


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="A3-M contamination gate (measure-only).")
    ap.add_argument(
        "--v8-prefix",
        default=str(V8_PREFIX),
        help="embedding prefix for the v8 index under test (default: original v8)",
    )
    ap.add_argument(
        "--out-name",
        default="compare.json",
        help="compare json filename under build/v8-a3-results/ (e.g. compare_v8b.json)",
    )
    ap.add_argument(
        "--v8-label",
        default="v8",
        help="label for the v8 index in the txt summary (e.g. v8b)",
    )
    ap.add_argument(
        "--dedup",
        action="store_true",
        help="apply production article_id dedup (R.dedup_by_article) before top-K",
    )
    ap.add_argument(
        "--dedup-raw",
        action="store_true",
        help="dedup on raw article_id (None-collapsed) instead of the chunk_id fallback; "
        "reproduces the build/_a3_probe.py key rule (diagnostic parity check only)",
    )
    args = ap.parse_args()
    dedup = args.dedup
    v8_prefix = Path(args.v8_prefix)
    v8_label = args.v8_label

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).isoformat()

    # ---- load eval sets ----
    main_qs: list[dict] = []
    for group, path in MAIN_EVAL:
        for q in _load_jsonl(path):
            q["_law_group"] = group
            main_qs.append(q)
    new_qs: dict[str, list[dict]] = {}
    for group, path in NEWLAYER_EVAL:
        new_qs[group] = _load_jsonl(path)

    all_questions = [q["question"] for q in main_qs] + [
        q["question"] for g in new_qs for q in new_qs[g]
    ]

    # ---- load v8 first to get present-id sets + layer map (needed for the corpus-gold filter) ----
    print(f"Loading v8 artefacts ({v8_prefix.name}) ...", file=sys.stderr)
    v8_matrix, v8_records, v8_state = R._load_artefacts(v8_prefix)
    v8_aids, v8_cids = _present_ids(v8_records)
    v8_keys = _match_keys(v8_records)
    v8_art = [r.get("article_id") for r in v8_records]  # raw article_id (probe-parity key)
    # layer/corpus_group aligned to v8 records (row order verified == corpus order)
    v8_layers = []
    v8_groups = []
    with V8_CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            v8_layers.append(r.get("layer"))
            v8_groups.append(r.get("corpus_group"))
    assert len(v8_layers) == len(v8_records), "corpus/meta row count mismatch"

    print("Loading v7 artefacts ...", file=sys.stderr)
    v7_matrix, v7_records, _v7_state = R._load_artefacts(V7_PREFIX)
    v7_aids, _v7_cids = _present_ids(v7_records)
    v7_keys = _match_keys(v7_records)
    v7_art = [r.get("article_id") for r in v7_records]  # raw article_id (probe-parity key)

    both_aids = v7_aids & v8_aids

    # ---- corpus-gold filter on the main eval (honbun gold present in BOTH corpora) ----
    adopted: list[dict] = []
    excluded: list[dict] = []
    for q in main_qs:
        gold = set(q.get("expected_article_ids") or [])
        honbun = gold & both_aids
        if honbun:
            q["_gold"] = honbun
            adopted.append(q)
        else:
            excluded.append(
                {
                    "id": q.get("id"),
                    "law": q["_law_group"],
                    "gold": sorted(gold),
                    "reason": "no gold present in both v7 and v8 corpus",
                }
            )

    # ---- encode all queries once (reused for v7 and v8; same model) ----
    q_emb_all = _encode_queries_cached(all_questions, v8_state)
    main_emb = q_emb_all[: len(main_qs)]
    # index map from adopted -> position in main_qs
    main_pos = {id(q): i for i, q in enumerate(main_qs)}
    adopted_idx = [main_pos[id(q)] for q in adopted]
    adopted_emb = main_emb[adopted_idx]
    adopted_questions = [q["question"] for q in adopted]
    adopted_gold = [q["_gold"] for q in adopted]
    adopted_group = [q["_law_group"] for q in adopted]

    result = {
        "generated_utc": stamp,
        "config": {
            "top_k": TOP_K,
            "candidate_pool": CANDIDATE_POOL,
            "rrf_k": RRF_K,
            "embedding_model": v8_state.get("model"),
            "v8_index": v8_prefix.name,
            "dedup": dedup,
            "reproduce": [
                "python tools/embed/a3_contamination_eval.py",
                "# dense: cosine top-60 pool; hybrid: BM25 char2-3gram RRF(k=60); top_k=20",
            ],
        },
        "corpus_gold_filter": {
            "v7_article_ids": len(v7_aids),
            "v8_article_ids": len(v8_aids),
            "article_ids_in_both": len(both_aids),
            "v8_only_article_ids": len(v8_aids - v7_aids),
            "main_eval_total": len(main_qs),
            "adopted_N": len(adopted),
            "excluded_N": len(excluded),
            "excluded": excluded,
            "note": "v8 article_ids superset of v7 (+sochi-hou); v7 already contained "
            "tsutatsu/taxanswer/enforcement chunks, so this gate measures the v8 "
            "rebuild (sochi honbun add + re-chunking) vs v7, not a pure honbun-vs-mixed split.",
        },
        "main_eval": {},
        "new_layer": {},
        "reverse_contamination_samples": [],
    }

    # ---- retrieve + score both indices on the adopted main eval ----
    def score_index(name, matrix, keys, corpus_path, dedup_keys):
        dense_top = _dense_top(adopted_emb, matrix)
        if dedup:
            # production dedup path: R.dedup_by_article on the wide pool.
            # dedup_keys = fallback ids (chunk_id) by default, raw article_id with --dedup-raw.
            dense_final = R.dedup_by_article(dense_top, dedup_keys, TOP_K)
            hyb_wide = _hybrid_top(
                adopted_questions, dense_top, corpus_path, result_k=CANDIDATE_POOL
            )
            hyb_top = R.dedup_by_article(hyb_wide, dedup_keys, TOP_K)
        else:
            dense_final = dense_top
            hyb_top = _hybrid_top(adopted_questions, dense_top, corpus_path)
        dense_rows = _rows_for(dense_final, keys, adopted_gold)
        hyb_rows = _rows_for(hyb_top, keys, adopted_gold)
        out = {
            "dense": {"overall": _aggregate(dense_rows), "by_law": {}},
            "hybrid": {"overall": _aggregate(hyb_rows), "by_law": {}},
        }
        for law in sorted(set(adopted_group)):
            sel = [i for i, g in enumerate(adopted_group) if g == law]
            out["dense"]["by_law"][law] = _aggregate([dense_rows[i] for i in sel])
            out["hybrid"]["by_law"][law] = _aggregate([hyb_rows[i] for i in sel])
        return out, dense_top, hyb_top

    v7_dedup_keys = v7_art if args.dedup_raw else v7_keys
    v8_dedup_keys = v8_art if args.dedup_raw else v8_keys
    print("Scoring v7 (main eval) ...", file=sys.stderr)
    v7_score, _v7d, _v7h = score_index("v7", v7_matrix, v7_keys, V7_CORPUS, v7_dedup_keys)
    del v7_matrix
    print("Scoring v8 (main eval) ...", file=sys.stderr)
    v8_score, _v8_dense_top, v8_hyb_top = score_index(
        "v8", v8_matrix, v8_keys, V8_CORPUS, v8_dedup_keys
    )

    def _delta(a, b):
        return {
            mode: {
                "overall": {
                    f"recall_{c}": round(
                        b[mode]["overall"][f"recall_{c}"]["pct"]
                        - a[mode]["overall"][f"recall_{c}"]["pct"],
                        4,
                    )
                    for c in K_CUTS
                }
            }
            for mode in ("dense", "hybrid")
        }

    result["main_eval"] = {
        "adopted_N": len(adopted),
        "v7": v7_score,
        "v8": v8_score,
        "delta_v8_minus_v7": _delta(v7_score, v8_score),
    }

    # ---- new-layer hit (v8 only) ----
    ptr = len(main_qs)
    for group, _path in NEWLAYER_EVAL:
        qs = new_qs[group]
        emb = q_emb_all[ptr : ptr + len(qs)]
        ptr += len(qs)
        adopted_n, excl = [], []
        for j, q in enumerate(qs):
            exp = _expected_newlayer(q)
            present = {e for e in exp if e in v8_cids}
            if present:
                adopted_n.append((j, present))
            else:
                excl.append(
                    {"id": q.get("id"), "gold": sorted(exp), "reason": "gold absent from v8 corpus"}
                )
        if adopted_n:
            sel_idx = [j for j, _ in adopted_n]
            sel_emb = emb[sel_idx]
            sel_q = [qs[j]["question"] for j in sel_idx]
            sel_gold = [p for _, p in adopted_n]
            d_top = _dense_top(sel_emb, v8_matrix)
            if dedup:
                d_final = R.dedup_by_article(d_top, v8_dedup_keys, TOP_K)
                h_top = R.dedup_by_article(
                    _hybrid_top(sel_q, d_top, V8_CORPUS, result_k=CANDIDATE_POOL),
                    v8_dedup_keys,
                    TOP_K,
                )
            else:
                d_final = d_top
                h_top = _hybrid_top(sel_q, d_top, V8_CORPUS)
            d_rows = _rows_for(d_final, v8_keys, sel_gold)
            h_rows = _rows_for(h_top, v8_keys, sel_gold)
            nl = {"dense": _aggregate(d_rows), "hybrid": _aggregate(h_rows)}
        else:
            nl = {"dense": _aggregate([]), "hybrid": _aggregate([])}
        result["new_layer"][group] = {
            "total": len(qs),
            "adopted_N": len(adopted_n),
            "excluded_gold_absent": excl,
            "v8": nl,
        }

    # ---- reverse contamination: new-layer chunks intruding into honbun top-5 (v8 hybrid) ----
    NONHONBUN = {"tsutatsu", "taxanswer", "ruling"}
    samples = []
    for qi in range(len(adopted)):
        top5 = []
        intruded = False
        for idx in v8_hyb_top[qi][:5]:
            i = int(idx)
            if i < 0:
                continue
            lay = v8_layers[i]
            is_gold = v8_keys[i] in adopted_gold[qi]
            if lay in NONHONBUN:
                intruded = True
            top5.append(
                {
                    "chunk_id": v8_keys[i],
                    "layer": lay,
                    "corpus_group": v8_groups[i],
                    "is_gold": is_gold,
                }
            )
        if intruded:
            samples.append({"id": adopted[qi].get("id"), "law": adopted_group[qi], "top5": top5})
    result["reverse_contamination_samples"] = samples[:20]
    result["reverse_contamination_count"] = len(samples)

    # ---- write outputs ----
    (OUT / args.out_name).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_txt(OUT / "v7.txt", "v7", v7_score, adopted, excluded, both_aids, v7_aids, v8_aids)
    _write_txt(
        OUT / f"{v8_label}.txt",
        v8_label,
        v8_score,
        adopted,
        excluded,
        both_aids,
        v7_aids,
        v8_aids,
        new_layer=result["new_layer"],
        revcon=len(samples),
    )

    print(f"\n=== A3-M done. {args.out_name} + v7.txt + {v8_label}.txt in build/v8-a3-results/ ===")
    _print_summary(result)
    return 0


def _fmt_overall(score, mode):
    o = score[mode]["overall"]
    return "  ".join(
        f"R@{c}={o[f'recall_{c}']['hit']}/{o['n']}({o[f'recall_{c}']['pct']:.1%})" for c in K_CUTS
    )


def _write_txt(path, name, score, adopted, excluded, both, v7a, v8a, new_layer=None, revcon=None):
    lines = [
        f"=== {name} A3-M summary ===",
        f"adopted N (main, corpus-gold filtered): {len(adopted)}   excluded: {len(excluded)}",
        f"article_ids: v7={len(v7a)} v8={len(v8a)} both={len(both)} v8_only={len(v8a - v7a)}",
        "",
        f"[dense ] {_fmt_overall(score, 'dense')}",
        f"[hybrid] {_fmt_overall(score, 'hybrid')}",
        "",
        "per-law (hybrid):",
    ]
    for law, agg in score["hybrid"]["by_law"].items():
        lines.append(
            f"  {law:14s} N={agg['n']:3d}  "
            + "  ".join(f"R@{c}={agg[f'recall_{c}']['pct']:.1%}" for c in K_CUTS)
        )
    if new_layer is not None:
        lines += ["", "new-layer hit (v8 only):"]
        for g, d in new_layer.items():
            v = d["v8"]["hybrid"]
            lines.append(
                f"  {g:10s} adopted={d['adopted_N']}/{d['total']}  "
                + "  ".join(f"R@{c}={v[f'recall_{c}']['pct']:.1%}" for c in K_CUTS)
            )
        lines.append(f"reverse-contamination queries (non-honbun in top-5): {revcon}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_summary(result):
    m = result["main_eval"]
    print(f"adopted N = {m['adopted_N']}")
    for mode in ("dense", "hybrid"):
        print(f"[{mode}] v7 vs v8 overall:")
        print(f"   v7: {_fmt_overall(m['v7'], mode)}")
        print(f"   v8: {_fmt_overall(m['v8'], mode)}")
        d = m["delta_v8_minus_v7"][mode]["overall"]
        print("   delta(v8-v7): " + "  ".join(f"R@{c}={d[f'recall_{c}']:+.1%}" for c in K_CUTS))
    for g, d in result["new_layer"].items():
        v = d["v8"]["hybrid"]
        print(
            f"new-layer {g}: adopted {d['adopted_N']}/{d['total']}  "
            + "  ".join(f"R@{c}={v[f'recall_{c}']['pct']:.1%}" for c in K_CUTS)
        )
    print(f"reverse-contamination queries: {result['reverse_contamination_count']}")


if __name__ == "__main__":
    raise SystemExit(main())

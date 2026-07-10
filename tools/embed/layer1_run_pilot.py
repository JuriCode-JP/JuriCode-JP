#!/usr/bin/env python3
"""layer1_run_pilot.py -- RAG 忠実性 Layer1 pilot の retrieval 実行 + raw ログ出力.

4 条件 (A-項/A-条/B0-項/B0-条) × 2 クエリmode (生/canonicalize) × 4 ablation
(baseline/+normalize/+reranker/+both) = 32 run を実行し、per-query raw ログ (dedup 前後)
と集計 json を隔離ディレクトリに出力する。

Why (設計):
  - **retrieve.py を再利用** (新規 retrieval ロジック禁止): dense (_cosine_topk),
    dedup (dedup_by_article), クエリ正規化 (normalize_legal_query), 埋め込みロード
    (_load_artefacts), クエリ encode (_encode_queries) をそのまま import。reranker は
    scores を raw ログに残すため CrossEncoder を薄く回す (rerank_with_cross_encoder と同機構)。
  - **クエリ encode をキャッシュ**: クエリ埋め込みは corpus 非依存 (同一 gemini モデル)。
    (qmode, normalize) の 4 variant を各 1 回だけ Gemini encode し 4 条件で再利用
    (32×136 でなく 4×136 の API 呼び出し)。
  - **検索順序 (§5 固定)**: dense wide-fetch M(>=100) → [chunk rerank on wide] →
    dedup_by_article → cut-K → Recall@K。全条件同一順序。
  - **共犯バグ封じ (§D)**: raw ログに engine 認識の article_id を chunk_id と併記し、
    Cowork が corpus 正本から独立クロスチェックできるようにする。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parent.parent.parent
_EMBED_DIR = _THIS.parent
_PARSE_DIR = _REPO / "tools" / "parse"
for p in (str(_EMBED_DIR), str(_PARSE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import retrieve as R  # noqa: E402  (tools/embed on path)
from _canonicalize import canonicalize  # noqa: E402  (tools/parse on path)

CONDITIONS = ("A-para", "A-art", "B0-para", "B0-art")
QUERY_MODES = ("raw", "canon")
ABLATIONS = ("baseline", "normalize", "reranker", "both")

TOP_K = 10
WIDE_M = 200  # dense wide-fetch (>=100, >=K×最大項/条 for dedup to yield K unique articles)
RERANK_CAND = 100  # rerank する dense 上位候補数 (>=100)
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def _load_eval(paths: list[Path]) -> list[dict]:
    out = []
    for p in paths:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def _corpus_article_set(corpus_prefix: Path) -> set[str]:
    ids = set()
    meta = corpus_prefix.parent / (corpus_prefix.name + ".meta.jsonl")
    with meta.open(encoding="utf-8") as fh:
        for line in fh:
            o = json.loads(line)
            if o.get("article_id"):
                ids.add(o["article_id"])
    return ids


def _query_text(raw_q: str, qmode: str, normalize: bool) -> str:
    q = canonicalize(raw_q) if qmode == "canon" else raw_q
    if normalize:
        q = R.normalize_legal_query(q)
    return q


def _law_of(article_id: str) -> str:
    return article_id.split("-art-")[0] if "-art-" in article_id else "?"


def _rerank_with_scores(queries, cand_idx_per_query, corpus_texts, model):
    """CrossEncoder で wide 候補を再スコア。(ranked_idx, score) を返す (raw ログ用).

    rerank_with_cross_encoder と同機構だが score を保持する (監査ログに score 併記が必要)。
    """
    reranked = []
    for qi, q in enumerate(queries):
        pairs, valid = [], []
        for idx in cand_idx_per_query[qi]:
            idx = int(idx)
            if idx < 0:
                continue
            pairs.append([q, corpus_texts[idx] if idx < len(corpus_texts) else ""])
            valid.append(idx)
        if not pairs:
            reranked.append([])
            continue
        scores = model.predict(pairs, batch_size=32, show_progress_bar=False)
        order = sorted(zip(scores, valid, strict=False), key=lambda x: -x[0])
        reranked.append([(int(c), float(s)) for s, c in order])
    return reranked


def run(
    out_dir: Path,
    eval_lawqa: list[Path],
    eval_tax: list[Path],
    ablations: tuple[str, ...] = ABLATIONS,
    query_modes: tuple[str, ...] = QUERY_MODES,
) -> int:
    import numpy as np

    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    corpus_dir = _REPO / "build" / "layer1-rawtext"

    queries = _load_eval(eval_lawqa) + _load_eval(eval_tax)
    raw_questions = [q["question"] for q in queries]
    print(f"eval queries loaded: {len(queries)}", file=sys.stderr)

    # --- クエリ埋め込みを 4 variant 分だけ生成 (corpus 非依存) ---
    # state は全 corpus 共通 (gemini/gemini-embedding-001)。1 つ読んで provider state を得る。
    probe_prefix = corpus_dir / "layer1-A-art-embedded"
    _, _, state = R._load_artefacts(probe_prefix)

    need_norm = {False} | ({True} if any(a in ("normalize", "both") for a in ablations) else set())
    qcache: dict[tuple[str, bool], np.ndarray] = {}
    for qmode in query_modes:
        for normalize in sorted(need_norm):
            texts = [_query_text(q, qmode, normalize) for q in raw_questions]
            print(f"  encoding queries variant ({qmode}, normalize={normalize})", file=sys.stderr)
            qcache[(qmode, normalize)] = R._encode_queries(texts, state)

    # reranker model (lazy: 初回 reranker ablation で load)
    cross_model = None

    aggregate = []
    for cond in CONDITIONS:
        prefix = corpus_dir / f"layer1-{cond}-embedded"
        matrix, records, _ = R._load_artefacts(prefix)
        article_ids = [r.get("article_id") for r in records]
        # corpus text (rerank 用) を同順で読む
        corpus_texts = []
        src = corpus_dir / f"layer1-{cond}.jsonl"
        with src.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    corpus_texts.append(json.loads(line).get("text", ""))
        corpus_arts = {a for a in article_ids if a}
        # gold は corpus 実在分に限定 (§A-0) - 条-level は <=2048 subset ゆえ条件別に変わる
        expected = [set(q.get("expected_article_ids") or []) & corpus_arts for q in queries]

        for qmode in query_modes:
            for ablation in ablations:
                normalize = ablation in ("normalize", "both")
                use_rerank = ablation in ("reranker", "both")
                qmat = qcache[(qmode, normalize)]
                sims, dense_top = R._cosine_topk(qmat, matrix, WIDE_M)

                # 検索順序: dense wide → [rerank] → dedup → cut-K
                if use_rerank:
                    if cross_model is None:
                        from sentence_transformers import CrossEncoder

                        print(f"  loading reranker {RERANK_MODEL} ...", file=sys.stderr)
                        cross_model = CrossEncoder(RERANK_MODEL, max_length=512)
                    cand = dense_top[:, :RERANK_CAND]
                    qtexts = [_query_text(q, qmode, normalize) for q in raw_questions]
                    reranked = _rerank_with_scores(qtexts, cand, corpus_texts, cross_model)
                    # reranked[qi] = [(idx, score), ...] ranked; build wide idx order
                    wide_order = [[i for i, _ in row] for row in reranked]
                    score_of = [{i: s for i, s in row} for row in reranked]
                else:
                    wide_order = [
                        [int(i) for i in dense_top[qi] if int(i) >= 0] for qi in range(len(queries))
                    ]
                    score_of = [
                        {int(i): float(sims[qi, int(i)]) for i in dense_top[qi] if int(i) >= 0}
                        for qi in range(len(queries))
                    ]

                # dedup_by_article on the (possibly reranked) wide order → cut-K
                ranks = []
                per_law_hit = {}
                per_law_tot = {}
                r1 = r3 = r10 = 0
                mrr_sum = 0.0
                n_adopted = 0
                raw_rows = []
                for qi, q in enumerate(queries):
                    # §A-0: gold が corpus 実在しない問は非採用 (N から除外・raw ログには残す)。
                    # 条-level 条件では <=2048 subset ゆえ over-token 条 gold は到達不能=非採用。
                    adopted = bool(expected[qi])
                    seen = set()
                    post = []
                    for idx in wide_order[qi]:
                        aid = article_ids[idx]
                        if aid in seen:
                            continue
                        seen.add(aid)
                        post.append(idx)
                        if len(post) >= TOP_K:
                            break
                    ranked_ids = [article_ids[i] for i in post]
                    rank = R._rank_of_first_match(ranked_ids, expected[qi])
                    ranks.append(rank)
                    if adopted:
                        n_adopted += 1
                        if rank is not None:
                            if rank <= 1:
                                r1 += 1
                            if rank <= 3:
                                r3 += 1
                            if rank <= 10:
                                r10 += 1
                            mrr_sum += 1.0 / rank
                        law = _law_of(sorted(expected[qi])[0])
                        per_law_tot[law] = per_law_tot.get(law, 0) + 1
                        if rank is not None and rank <= 10:
                            per_law_hit[law] = per_law_hit.get(law, 0) + 1
                    # raw log: pre-dedup wide 上位20 + post-dedup top-K
                    pre = [
                        {
                            "rank": j + 1,
                            "chunk_id": records[idx].get("chunk_id"),
                            "article_id": article_ids[idx],
                            "score": round(score_of[qi].get(idx, 0.0), 6),
                        }
                        for j, idx in enumerate(wide_order[qi][:20])
                    ]
                    postlog = [
                        {
                            "rank": j + 1,
                            "chunk_id": records[idx].get("chunk_id"),
                            "article_id": article_ids[idx],
                            "score": round(score_of[qi].get(idx, 0.0), 6),
                        }
                        for j, idx in enumerate(post)
                    ]
                    raw_rows.append(
                        {
                            "id": q["id"],
                            "query_raw": q["question"],
                            "adopted": adopted,
                            "gold_in_corpus": sorted(expected[qi]),
                            "gold_declared": sorted(q.get("expected_article_ids") or []),
                            "first_match_rank": rank,
                            "ranked_prededup": pre,
                            "ranked_postdedup": postlog,
                        }
                    )

                n = n_adopted
                tag = f"{cond}__{qmode}__{ablation}"
                rawfile = raw_dir / f"{tag}.jsonl"
                with rawfile.open("w", encoding="utf-8") as fh:
                    for row in raw_rows:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

                agg = {
                    "condition": cond,
                    "query_mode": qmode,
                    "ablation": ablation,
                    "N": n,
                    "N_loaded": len(queries),
                    "recall_at_1": r1 / n,
                    "recall_at_3": r3 / n,
                    "recall_at_10": r10 / n,
                    "mrr": mrr_sum / n,
                    "recall_at_1_count": r1,
                    "recall_at_3_count": r3,
                    "recall_at_10_count": r10,
                    "per_law": {
                        law: {"hit@10": per_law_hit.get(law, 0), "n": per_law_tot[law]}
                        for law in sorted(per_law_tot)
                    },
                    "M": WIDE_M,
                    "K": TOP_K,
                    "rerank_candidates": RERANK_CAND if use_rerank else None,
                    "raw_log": str(rawfile.relative_to(_REPO)),
                }
                aggregate.append(agg)
                print(
                    f"  {tag:34s} N={n} R@1={r1 / n:.1%} R@3={r3 / n:.1%} R@10={r10 / n:.1%} "
                    f"MRR={mrr_sum / n:.3f}",
                    file=sys.stderr,
                )

    agg_path = out_dir / "aggregate.json"
    with agg_path.open("w", encoding="utf-8") as fh:
        json.dump(
            {"top_k": TOP_K, "wide_m": WIDE_M, "n_runs": len(aggregate), "runs": aggregate},
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\naggregate -> {agg_path}  ({len(aggregate)} runs)", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO / "benchmarks" / "results" / "layer1-structured-vs-raw",
    )
    ap.add_argument(
        "--lawqa",
        type=Path,
        nargs="+",
        default=sorted((_REPO / "data" / "eval-set" / "lawqa-jp").glob("*.jsonl")),
    )
    ap.add_argument(
        "--tax",
        type=Path,
        nargs="+",
        default=[
            _REPO / "data" / "eval-set" / "tax-honbun-local" / "g1-local.jsonl",
            _REPO / "data" / "eval-set" / "tax.jsonl",
        ],
    )
    ap.add_argument("--ablations", nargs="+", default=list(ABLATIONS), choices=list(ABLATIONS))
    ap.add_argument(
        "--query-modes", nargs="+", default=list(QUERY_MODES), choices=list(QUERY_MODES)
    )
    args = ap.parse_args()
    return run(
        args.out_dir,
        list(args.lawqa),
        list(args.tax),
        ablations=tuple(args.ablations),
        query_modes=tuple(args.query_modes),
    )


if __name__ == "__main__":
    sys.exit(main())

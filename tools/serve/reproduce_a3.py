#!/usr/bin/env python3
"""T6: reproduce the locked A-3 numbers THROUGH the retrieval service (local, not CI).

Why:
    The A-3 pass line (v8b dense+dedup honbun R@10=84/97, R@20=87/97; new-layer tsutatsu
    R@20=15/15, taxanswer R@20=17/17) was locked from tools/embed/a3_contamination_eval.py.
    This harness proves the resident service reproduces those exact numbers using the SAME
    retrieval core (RetrievalService.retrieve == retrieve.py dense + dedup_by_article) on the
    SAME index and the SAME corpus-gold filter (N=97). If it does not reproduce, STOP and print
    the cause -- do NOT tune to hit the target.

    Encoding is deterministic (gemini-embedding-001 RETRIEVAL_QUERY), so a batched encode
    (RetrievalService uses the identical retrieve._encode_queries call) yields the same vectors
    as the per-request HTTP path. A live HTTP sample confirms the wiring and measures full-path
    latency (encode + retrieve).

Outputs (build/v8-a3-results/, gitignored):
    service-a3-repro.json  -- machine record of T6 + fold ON/OFF + perf.

Run:
    python tools/serve/reproduce_a3.py                # asserts T6, writes report
    python tools/serve/reproduce_a3.py --http-sample 8  # + N live HTTP round-trips
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parents[1]
for _p in (REPO / "tools" / "embed", REPO / "tools" / "shared" / "src", SCRIPT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import a3_contamination_eval as A  # noqa: E402  (reuse eval sets + filter helpers)
import retrieval_server as S  # noqa: E402
import retrieve as R  # noqa: E402
from juricode_shared.safe_write import safe_write_text  # noqa: E402

OUT = REPO / "build" / "v8-a3-results"
V8B_PREFIX = REPO / "build" / "embeddings" / "v0.2-aug-v8b-gemini"
CORPUS = REPO / "build" / "corpus-v8-embed.jsonl"

# Locked targets (build/v8-a3-results/compare_v8b_dedup.json, dense+dedup, fold OFF).
TARGET = {"N": 97, "R@10": 84, "R@20": 87}
NEWLAYER_TARGET = {"tsutatsu": {"N": 15, "R@20": 15}, "taxanswer": {"N": 17, "R@20": 17}}


def _rss_mb() -> float | None:
    """Best-effort resident set size (MB) on Windows; None if unavailable."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD),
                ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PMC()
        counters.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wt.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:  # best-effort telemetry only; never block the run on RSS readout
        return None
    return None


def _hit_key(h: dict) -> str:
    """Match key mirrors A-3 _match_keys: article_id else chunk_id."""
    return h["article_id"] or h["chunk_id"]


def _recall(svc: S.RetrievalService, embs, golds, fold: bool) -> dict:
    """Retrieve each query via the service core (dense+dedup, top_k=20) and score R@k."""
    hits_at = {c: 0 for c in A.K_CUTS}
    ranks = []
    lat_ms = []
    for i in range(len(golds)):
        vec = embs[i : i + 1]
        t0 = time.perf_counter()
        hits, _ = svc.retrieve(vec, top_k=20, target_layers=None, dedup=True, fold=fold)
        lat_ms.append((time.perf_counter() - t0) * 1000.0)
        keys = [_hit_key(h) for h in hits]
        rank = next((j for j, k in enumerate(keys, 1) if k in golds[i]), None)
        ranks.append(rank)
        for c in A.K_CUTS:
            if rank is not None and rank <= c:
                hits_at[c] += 1
    n = len(golds)
    return {
        "n": n,
        "recall": {f"R@{c}": hits_at[c] for c in A.K_CUTS},
        "retrieve_latency_ms": _pctl(lat_ms),
    }


def _pctl(xs: list[float]) -> dict:
    if not xs:
        return {"p50": None, "p95": None, "max": None}
    s = sorted(xs)
    return {
        "p50": round(s[len(s) // 2], 2),
        "p95": round(s[min(len(s) - 1, int(len(s) * 0.95))], 2),
        "max": round(s[-1], 2),
    }


def _build_adopted(svc: S.RetrievalService):
    """Reproduce A-3's corpus-gold filter: honbun gold present in BOTH v7 and v8 corpora."""
    v8_aids = {a for a in svc.article_ids if a}
    _m, v7_recs, _s = R._load_artefacts(A.V7_PREFIX)
    v7_aids = {r.get("article_id") for r in v7_recs if r.get("article_id")}
    del _m
    both = v7_aids & v8_aids

    main_qs: list[dict] = []
    for group, path in A.MAIN_EVAL:
        for q in A._load_jsonl(path):
            q["_law_group"] = group
            main_qs.append(q)
    adopted = []
    for q in main_qs:
        gold = set(q.get("expected_article_ids") or []) & both
        if gold:
            q["_gold"] = gold
            adopted.append(q)
    return adopted


def _newlayer(svc: S.RetrievalService, embs_cache: dict) -> dict:
    v8_cids = set(svc.chunk_ids)
    out = {}
    for group, path in A.NEWLAYER_EVAL:
        qs = A._load_jsonl(path)
        sel, golds = [], []
        for q in qs:
            exp = A._expected_newlayer(q)
            present = {e for e in exp if e in v8_cids}
            if present:
                sel.append(q["question"])
                golds.append(present)
        embs = R._encode_queries(sel, svc.state) if sel else np.zeros((0, svc.dim), np.float32)
        out[group] = {
            "total": len(qs),
            "fold_off": _recall(svc, embs, golds, fold=False),
            "fold_on": _recall(svc, embs, golds, fold=True),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="T6 A-3 reproduction through the service.")
    ap.add_argument("--http-sample", type=int, default=0, help="live HTTP round-trips for latency")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    print(f"[startup] building service on {V8B_PREFIX.name} ...", file=sys.stderr)
    svc = S.RetrievalService(V8B_PREFIX, CORPUS, default_fold=False)
    startup_s = time.perf_counter() - t_start
    print(f"[startup] done in {startup_s:.1f}s, RSS={_rss_mb()} MB", file=sys.stderr)

    # ---- honbun N=97 (T6) ----
    adopted = _build_adopted(svc)
    questions = [q["question"] for q in adopted]
    golds = [q["_gold"] for q in adopted]
    print(f"[honbun] encoding {len(questions)} adopted queries ...", file=sys.stderr)
    embs = R._encode_queries(questions, svc.state)
    honbun_off = _recall(svc, embs, golds, fold=False)
    honbun_on = _recall(svc, embs, golds, fold=True)

    # ---- new-layer ----
    print("[new-layer] scoring tsutatsu / taxanswer ...", file=sys.stderr)
    newlayer = _newlayer(svc, {})

    # ---- full-path latency (encode + retrieve) via live HTTP sample ----
    http_latency = None
    if args.http_sample > 0:
        http_latency = _http_sample(svc, questions[: args.http_sample])

    rss = _rss_mb()
    report = {
        "index": V8B_PREFIX.name,
        "startup_seconds": round(startup_s, 2),
        "rss_mb": round(rss, 1) if rss else None,
        "matrix_bytes": int(svc._norm_matrix.nbytes),
        "honbun": {
            "N": honbun_off["n"],
            "fold_off": honbun_off["recall"],
            "fold_on": honbun_on["recall"],
            "retrieve_latency_ms": honbun_off["retrieve_latency_ms"],
        },
        "new_layer": newlayer,
        "http_full_path_latency_ms": http_latency,
        "target": TARGET,
    }
    safe_write_text(
        OUT / "service-a3-repro.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )

    # ---- verdict ----
    off = honbun_off["recall"]
    ok = (
        off["R@10"] == TARGET["R@10"]
        and off["R@20"] == TARGET["R@20"]
        and honbun_off["n"] == TARGET["N"]
    )
    print("\n=== T6: A-3 reproduction through the service ===")
    print(f"  honbun N={honbun_off['n']} (target {TARGET['N']})")
    print(
        f"  fold OFF: R@10={off['R@10']} R@20={off['R@20']}  (target R@10={TARGET['R@10']} R@20={TARGET['R@20']})"
    )
    print(
        f"  fold ON : R@10={honbun_on['recall']['R@10']} R@20={honbun_on['recall']['R@20']}  (report only)"
    )
    for g, d in newlayer.items():
        t = NEWLAYER_TARGET.get(g, {})
        print(
            f"  new-layer {g}: N={d['fold_off']['n']} fold_off R@20={d['fold_off']['recall']['R@20']} "
            f"fold_on R@20={d['fold_on']['recall']['R@20']}  (target N={t.get('N')} R@20={t.get('R@20')})"
        )
    print(f"  retrieve latency (fold off): {honbun_off['retrieve_latency_ms']}")
    if http_latency:
        print(f"  full-path HTTP latency (encode+retrieve): {http_latency}")
    print(f"  startup={startup_s:.1f}s  RSS={rss} MB")
    print(f"\n  report -> {OUT / 'service-a3-repro.json'}")

    if not ok:
        print(
            "\n*** T6 FAILED: service does not reproduce the A-3 numbers. STOP (do not tune). ***"
        )
        return 1
    print("\n*** T6 PASS: service reproduces A-3 dense+dedup honbun R@10=84/97, R@20=87/97. ***")
    return 0


def _http_sample(svc: S.RetrievalService, questions: list[str]) -> dict:
    """Spin the real ThreadingHTTPServer and time N /retrieve round-trips (encode + retrieve)."""
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    S._SERVICE = svc
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    lat = []
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        for q in questions:
            t0 = time.perf_counter()
            conn.request("POST", "/retrieve", json.dumps({"query": q, "top_k": 20}))
            r = conn.getresponse()
            r.read()
            lat.append((time.perf_counter() - t0) * 1000.0)
        conn.close()
    finally:
        httpd.shutdown()
        S._SERVICE = None
    return _pctl(lat)


if __name__ == "__main__":
    raise SystemExit(main())

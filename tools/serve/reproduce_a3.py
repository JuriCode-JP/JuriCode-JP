#!/usr/bin/env python3
"""T6: reproduce the locked A-3 numbers THROUGH the retrieval service (local, not CI).

Why:
    This harness proves the resident service reproduces the locked A-3 pass line THROUGH
    the retrieval core (RetrievalService.retrieve == retrieve.py dense + dedup_by_article)
    on the same index and the same corpus-gold filter. The pass lines are per index and
    live in gates/pass-lines.json, anchored by a digest held outside this repo's write
    scope (tools/scripts/verify-gates-lock.py); they are deliberately NOT copied here,
    because a second copy of a number in a docstring is a source of truth nothing checks
    and it goes stale silently. If a run does not reproduce its pass line, STOP and print
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
V9_PREFIX = REPO / "build" / "embeddings" / "v0.2-aug-v9-gemini"
CORPUS_V8 = REPO / "build" / "corpus-v8-embed.jsonl"
CORPUS_V9 = REPO / "build" / "corpus-v11-embed.jsonl"

# Back-compat aliases (older call sites).
CORPUS = CORPUS_V8

# Pass lines are per index. A pass line measured on one index says nothing about
# another: the corpora differ in what they contain, so the population differs. The
# values are NOT a literal here anymore -- they live in gates/pass-lines.json, which
# is anchored by a digest held outside this repo's write scope (see
# tools/scripts/verify-gates-lock.py). Keeping them out of the code means "the gate
# passed" can no longer mean "it passed the line the same edit could have lowered".
# The reasoning for why the v9 numbers are lower than v8b's lives in that file's
# _comment field -- it is what stops someone from "fixing" the lower numbers.
PASS_LINES_PATH = REPO / "gates" / "pass-lines.json"


def _load_pass_lines() -> dict[str, dict]:
    """Load the locked pass lines from gates/pass-lines.json.

    Why: the pass line is a contract, not a build output. Reading it from a
    digest-anchored file (rather than a code literal) keeps whoever edits this
    module from silently moving the line they are being measured against.
    """
    with PASS_LINES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)["pass_lines"]


# The gate-contract files locked by tools/scripts/verify-gates-lock.py. This list
# must stay identical to that script's LOCKED_FILES: the stamped digest below is
# meant to equal what GATES_LOCK_SHA256 holds, and both bind the paths as well as
# the bytes. A test (test_verify_gates_lock.py) asserts the two agree, so if a later
# step adds a file to the lock and forgets to add it here, CI goes red instead of the
# harness quietly stamping a digest that no longer matches the anchor.
_LOCKED_GATE_FILES = ["gates/pass-lines.json", "gates/g0-classification.json"]


def _pass_lines_digest() -> str:
    """Combined SHA256 of the locked gate-contract files -- byte-identical to what
    tools/scripts/verify-gates-lock.py computes and what goes in GATES_LOCK_SHA256.

    Why: the stamp on the verdict line exists so a reader can confirm WHICH pass line
    a run passed against, by comparing the stamp to the CI variable directly. That
    only works if the stamp is the same value as the anchor -- the combined digest
    over all locked files (path-bound), not the fingerprint of one file. The logic is
    copied verbatim from verify-gates-lock.py:combined_digest (sorted list, LF
    normalization, path + NUL + bytes); a subtle divergence would stamp a digest that
    never matches, so the agreement is pinned by a test.
    """
    import hashlib

    h = hashlib.sha256()
    for rel in sorted(_LOCKED_GATE_FILES):
        norm = (REPO / rel).read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode("utf-8") + b"\0" + norm)
    return h.hexdigest()


TARGETS: dict[str, dict] = _load_pass_lines()


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
    """Score the full honbun ground-truth denominator (no cross-filter).

    Why:
        Every honbun question whose eval specifies a gold article is scored; a gold
        article absent from the index scores 0 (a miss), it is not dropped. The earlier
        cross-filter (gold present in BOTH an older v7 corpus AND this index) hid index
        gaps and branch-numbered questions from the denominator, so the pass line was
        provisional. Removing it makes the line measure the honest population: a fixed,
        full denominator that surfaces gaps instead of concealing them. `if gold` still
        drops questions carrying no honbun gold at all -- a different question type, not
        defect-hiding. (svc is kept in the signature for call-site stability; the id sets
        it supplied are no longer needed now that scoring is against the full ground truth.)
    """
    main_qs: list[dict] = []
    for group, path in A.MAIN_EVAL:
        for q in A._load_jsonl(path):
            q["_law_group"] = group
            main_qs.append(q)
    adopted = []
    for q in main_qs:
        gold = set(q.get("expected_article_ids") or [])
        if gold:
            q["_gold"] = gold
            adopted.append(q)
    return adopted


def _newlayer(svc: S.RetrievalService, embs_cache: dict) -> dict:
    """Score the full new-layer ground-truth denominator (no index filter).

    Why:
        Every new-layer question whose eval specifies a gold key is scored; a gold
        chunk absent from the index scores 0 (a miss), it is not dropped. The earlier
        self-filter (keep only golds present in this index's chunk ids) hid source gaps
        from the denominator, so the pass line was provisional. `if exp` still drops
        questions carrying no expected gold at all -- a different question type, not
        defect-hiding. (svc is kept in the signature for call-site stability.)
    """
    import numpy as np  # lazy import

    out = {}
    for group, path in A.NEWLAYER_EVAL:
        qs = A._load_jsonl(path)
        sel, golds = [], []
        for q in qs:
            exp = A._expected_newlayer(q)
            if exp:
                sel.append(q["question"])
                golds.append(set(exp))
        embs = R._encode_queries(sel, svc.state) if sel else np.zeros((0, svc.dim), np.float32)
        out[group] = {
            "total": len(qs),
            "fold_off": _recall(svc, embs, golds, fold=False),
            "fold_on": _recall(svc, embs, golds, fold=True),
        }
    return out


def _verdict(
    honbun_off: dict,
    newlayer: dict,
    target: dict,
    newlayer_target: dict,
) -> tuple[bool, list[str]]:
    """Decide T6 pass/fail from the measured honbun + new-layer numbers.

    Why:
        The verdict used to be an inline boolean that read honbun only, so a new-layer
        shortfall was printed next to its target and never reached the exit code -- a
        harder-to-spot version of "print a finding without letting it fail the run",
        because the target sits right beside the measured value and a reader assumes
        something compared them. Pulling the decision into a pure function (a) lets a
        shrinking new-layer group fail the run and (b) makes the decision testable
        without standing the service up. Every reason names the exact check that failed,
        because a gate that fails without saying why invites tuning until it passes.

    Compares fold_off only: fold_on is report-only -- the honbun verdict already ignores
    it and the locked numbers were measured on fold_off; gating on fold_on would change
    the contract silently. The new-layer group sets are compared BOTH ways first (a
    measured group with no recorded target is not a pass; a recorded target never
    measured is not a line met), which is the same exclusion shape the fidelity-gate
    classification cross-check removes. Because that set check runs first, the per-group
    indexing below is safe without defensive .get chains: _recall always returns "n" and
    every A.K_CUTS recall key (zero hits give 0, not a missing key).

    Returns (passed, reasons): passed is True only when reasons is empty.
    """
    reasons: list[str] = []
    off = honbun_off["recall"]
    if honbun_off["n"] != target["N"]:
        reasons.append(f"honbun N={honbun_off['n']} != target {target['N']}")
    if off["R@10"] != target["R@10"]:
        reasons.append(f"honbun R@10={off['R@10']} != target {target['R@10']}")
    if off["R@20"] != target["R@20"]:
        reasons.append(f"honbun R@20={off['R@20']} != target {target['R@20']}")

    measured = set(newlayer)
    recorded = set(newlayer_target)
    for g in sorted(measured - recorded):
        reasons.append(
            f"new-layer group {g!r} measured but has no recorded target (unknown is not a pass)"
        )
    for g in sorted(recorded - measured):
        reasons.append(f"new-layer group {g!r} has a recorded target but was not measured")

    for g in sorted(measured & recorded):
        d = newlayer[g]["fold_off"]
        t = newlayer_target[g]
        if d["n"] != t["N"]:
            reasons.append(f"new-layer {g} N={d['n']} != target {t['N']}")
        if d["recall"]["R@20"] != t["R@20"]:
            reasons.append(f"new-layer {g} R@20={d['recall']['R@20']} != target {t['R@20']}")

    return (not reasons, reasons)


def main() -> int:
    ap = argparse.ArgumentParser(description="T6 A-3 reproduction through the service.")
    ap.add_argument("--http-sample", type=int, default=0, help="live HTTP round-trips for latency")
    ap.add_argument("--index", type=Path, default=V9_PREFIX, help="索引 prefix (既定 v9)")
    ap.add_argument("--corpus", type=Path, default=CORPUS_V9, help="索引の入力 corpus (既定 v11)")
    args = ap.parse_args()

    # 合格線は索引ごと。未知の索引に「それらしい既定値」を当てると、別の母集団の値と
    # 比べて緑/赤を出すことになる。知らない索引なら知らないと言って止まる。
    if args.index.name not in TARGETS:
        print(
            f"STOP: no pass line is recorded for index {args.index.name!r}. "
            f"Known: {sorted(TARGETS)}. Measure it first, then record it in TARGETS.",
            file=sys.stderr,
        )
        return 1
    target = TARGETS[args.index.name]["honbun"]
    newlayer_target = TARGETS[args.index.name]["newlayer"]

    OUT.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    print(f"[startup] building service on {args.index.name} ...", file=sys.stderr)
    svc = S.RetrievalService(args.index, args.corpus, default_fold=False)
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
        "index": args.index.name,
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
        "target": target,
        "target_note": TARGETS[args.index.name]["note"],
    }
    safe_write_text(
        OUT / "service-a3-repro.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )

    # ---- verdict ----
    off = honbun_off["recall"]
    ok, reasons = _verdict(honbun_off, newlayer, target, newlayer_target)
    print("\n=== T6: A-3 reproduction through the service ===")
    print(f"  index: {args.index.name}")
    print(f"  honbun N={honbun_off['n']} (target {target['N']})")
    print(
        f"  fold OFF: R@10={off['R@10']} R@20={off['R@20']}  (target R@10={target['R@10']} R@20={target['R@20']})"
    )
    print(
        f"  fold ON : R@10={honbun_on['recall']['R@10']} R@20={honbun_on['recall']['R@20']}  (report only)"
    )
    for g, d in newlayer.items():
        t = newlayer_target.get(g, {})
        print(
            f"  new-layer {g}: N={d['fold_off']['n']} fold_off R@20={d['fold_off']['recall']['R@20']} "
            f"fold_on R@20={d['fold_on']['recall']['R@20']}  (target N={t.get('N')} R@20={t.get('R@20')})"
        )
    print(f"  retrieve latency (fold off): {honbun_off['retrieve_latency_ms']}")
    if http_latency:
        print(f"  full-path HTTP latency (encode+retrieve): {http_latency}")
    print(f"  startup={startup_s:.1f}s  RSS={rss} MB")
    print(f"\n  report -> {OUT / 'service-a3-repro.json'}")

    digest = _pass_lines_digest()
    if not ok:
        detail = "".join(f"\n    - {r}" for r in reasons)
        print(
            f"\n*** T6 FAILED: service does not reproduce the A-3 numbers. STOP (do not tune). ***"
            f"\n  failed checks:{detail}"
            f"\n  pass line checked against gates/pass-lines.json gates_lock_sha256={digest}"
        )
        return 1
    # 合格線は索引ごとに違う。ここに数値をハードコードすると、別の索引で通したときに
    # **緑のログが嘘をつく** (実際 2026-07-15 に、78/85 で通ったのに 84/87 と表示した)。
    # digest を刻むことで、どの版の合格線に対して通ったかがログから分かる。
    print(
        f"\n*** T6 PASS: {args.index.name} reproduces its pass line "
        f"(honbun R@10={target['R@10']}/{target['N']}, R@20={target['R@20']}/{target['N']}). ***"
        f"\n  pass line checked against gates/pass-lines.json gates_lock_sha256={digest}"
    )
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

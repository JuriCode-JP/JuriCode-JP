#!/usr/bin/env python3
"""B4: measure the /chat orchestration end-to-end with real Gemini (local, not CI).

Why: PoC P2 の合否は「サービス経由で、出典つき・断定なし・数値なしの回答だけが通るか」を
実データで測ることでしか分からない。本 harness は実 v8b 索引を常駐ロードした P1 retrieval を
localhost HTTP で起動し、chat_server.run_chat を実 Gemini 2.5 Flash で 1 回回して、
guards の違反件数・grounded 率・再生成/情報不足率・レイテンシ内訳 (埋め込み往復 vs 生成)・
トークンを実測する。合格線・評価語は一切書かない (数値のみ)。

出力 (build/p2-b4-results/, gitignored):
    b4-results.json  -- 集計 + 各問の逐次記録 (監査用)。

Run (P1 は本 harness が内部起動する。索引ロードに数十秒):
    GEMINI_API_KEY=... python tools/serve/b4_eval.py
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parents[1]
for _p in (SCRIPT_DIR, REPO / "tools" / "shared" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import chat_server as C  # noqa: E402
import guards as G  # noqa: E402
import retrieval_server as RS  # noqa: E402
from juricode_shared.safe_write import safe_write_text  # noqa: E402

V8B_PREFIX = REPO / "build" / "embeddings" / "v0.2-aug-v8b-gemini"
CORPUS = REPO / "build" / "corpus-v8-embed.jsonl"

V9_PREFIX = REPO / "build" / "embeddings" / "v0.2-aug-v9-gemini"
CORPUS_V9 = REPO / "build" / "corpus-v11-embed.jsonl"

# 既定は v9 (現行 baseline)。--index v8b を渡せば旧 baseline が再現できる状態は保つ。
_INDEX = V9_PREFIX
_CORPUS = CORPUS_V9

# 合格線は索引ごと。ある索引で測った線は、別の索引について何も言わない (母集団が違う)。
#   v8b -- 号・細別が corpus に無く、枝番条 (132-2 等) は索引に存在すらしなかった頃の索引。
#   v9  -- 号・細別が第一級。G0-a/b/c/d/e すべて違反ゼロ。数値は v8b より低い。
#          それでもこちらを線にする。線は「ズレの検出」のためにあり、見栄えのためではない。
BASELINES: dict[str, dict] = {
    "v0.2-aug-v8b-gemini": {
        "grounded_correct": 47,
        "n_questions": 59,
        "violations": {"G1": 0, "G2": 1, "G3": 0, "G4": 4, "G5": 0, "G6": 0},
        "snapped_quote_mismatch": 0,
        "note": "measured before item-level chunks existed",
    },
    "v0.2-aug-v9-gemini": {
        "grounded_correct": 45,
        "n_questions": 59,
        "violations": {"G1": 0, "G2": 1, "G3": 0, "G4": 5, "G5": 0, "G6": 0},
        "snapped_quote_mismatch": 0,
        "note": "measured 2026-07-15 on corpus-v11 (item-level chunks present)",
    },
}
OUT = REPO / "build" / "p2-b4-results"
EVAL = REPO / "data" / "eval-set"

STATUTE_FAMILY = frozenset({"statute", "enforcement"})

# gemini-3.1-flash-lite 単価 ($/1M tokens、2026-07-13 maintainer 指定) を仮定値として置く。
# NOTE: 単価は前提であり実測事実ではない (要現行価格照合)。$ はトークン x この単価。
RATE_INPUT_PER_M = 0.25
RATE_OUTPUT_PER_M = 1.50


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_eval_set() -> list[dict]:
    """5 つの既存 eval を統合し、各問に期待 layer 集合と gold 判定関数を付ける (>=50 問)."""
    items: list[dict] = []

    for q in _load_jsonl(EVAL / "tax-tsutatsu.jsonl"):
        gold = q.get("expected_directive_id")
        items.append(
            {
                "id": q["id"],
                "source": "tsutatsu",
                "question": q["question"],
                "expected_layers": {"tsutatsu"},
                "gold_kind": "directive_id",
                "gold": gold,
            }
        )
    for q in _load_jsonl(EVAL / "tax-taxanswer.jsonl"):
        gold = q.get("expected_qa_code")
        items.append(
            {
                "id": q["id"],
                "source": "taxanswer",
                "question": q["question"],
                "expected_layers": {"taxanswer"},
                "gold_kind": "qa_code",
                "gold": str(gold) if gold is not None else None,
            }
        )
    for name in ("tax.jsonl", "tax-table.jsonl"):
        for q in _load_jsonl(EVAL / name):
            items.append(
                {
                    "id": q["id"],
                    "source": name.replace(".jsonl", ""),
                    "question": q["question"],
                    "expected_layers": set(STATUTE_FAMILY),
                    "gold_kind": "article_ids",
                    "gold": list(q.get("expected_article_ids") or []),
                }
            )
    for q in _load_jsonl(EVAL / "tax-honbun-local" / "g1-local.jsonl"):
        items.append(
            {
                "id": q["id"],
                "source": "g1-local",
                "question": q["question"],
                "expected_layers": set(STATUTE_FAMILY),
                "gold_kind": "article_ids",
                "gold": list(q.get("expected_article_ids") or []),
            }
        )
    return items


def gold_hit_chunk_ids(item: dict, hits: list[dict]) -> set[str]:
    """検索 hits のうち、その問の gold に一致する chunk_id 集合を返す (grounded 判定の基礎)."""
    kind, gold = item["gold_kind"], item["gold"]
    out: set[str] = set()
    for h in hits:
        cid = h.get("chunk_id")
        if kind == "directive_id" and gold and h.get("directive_id") == gold:
            out.add(cid)
        elif kind == "qa_code" and gold and f"-taxanswer-{gold}" in (cid or ""):
            out.add(cid)
        elif kind == "article_ids" and h.get("article_id") in set(gold or []):
            out.add(cid)
    return out


class TimingRetrieval:
    """HttpRetrievalClient をラップし retrieve/chunks の所要時間を記録する (計測専用)."""

    def __init__(self, inner: C.HttpRetrievalClient):
        self._inner = inner
        self.retrieve_ms: list[float] = []
        self.chunks_ms: list[float] = []

    def retrieve(self, question, top_k, target_layers):
        t0 = time.perf_counter()
        r = self._inner.retrieve(question, top_k, target_layers)
        self.retrieve_ms.append((time.perf_counter() - t0) * 1000.0)
        return r

    def chunks(self, chunk_ids):
        t0 = time.perf_counter()
        r = self._inner.chunks(chunk_ids)
        self.chunks_ms.append((time.perf_counter() - t0) * 1000.0)
        return r


class TimingProvider:
    """GeminiProvider をラップし生成の所要時間とトークンを積算する (計測専用)."""

    name = "gemini-timed"

    def __init__(self, inner: C.GeminiProvider):
        self._inner = inner
        self.gen_ms: list[float] = []
        self.prompt_toks = 0
        self.output_toks = 0

    def generate(self, system_prompt, context, question):
        t0 = time.perf_counter()
        out = self._inner.generate(system_prompt, context, question)
        self.gen_ms.append((time.perf_counter() - t0) * 1000.0)
        u = getattr(self._inner, "last_usage", None)
        if u is not None:
            self.prompt_toks += getattr(u, "prompt_token_count", 0) or 0
            self.output_toks += getattr(u, "candidates_token_count", 0) or 0
        return out


def _pctl(xs: list[float]) -> dict:
    if not xs:
        return {"p50": None, "p95": None, "max": None, "n": 0}
    s = sorted(xs)
    return {
        "p50": round(s[len(s) // 2], 1),
        "p95": round(s[min(len(s) - 1, int(len(s) * 0.95))], 1),
        "max": round(s[-1], 1),
        "n": len(s),
    }


def classify_g2(attempts: list[list[dict]]) -> dict:
    """G2 違反 (全 attempt) を内訳に分類 (G2 v2).

    - anchor_not_locatable : anchor が原文に位置特定できず (言い換え・幻覚・別チャンク)。
    - snapped_quote_mismatch: サーバー切り出しが原文に無い (= 実装バグ。構造上 0 のはず)。
    - no_body               : chunk_id が渡した hits に無い (G1 と二重)。
    """
    out = {"anchor_not_locatable": 0, "snapped_quote_mismatch": 0, "no_body": 0}
    for attempt in attempts:
        for v in attempt:
            if v.get("code") != "G2":
                continue
            d = v.get("detail", "")
            if "anchor not locatable" in d:
                out["anchor_not_locatable"] += 1
            elif "snapped_quote_mismatch" in d:
                out["snapped_quote_mismatch"] += 1
            else:
                out["no_body"] += 1
    return out


def start_p1(fold: bool) -> tuple[ThreadingHTTPServer, int]:
    """実 v8b 索引を常駐ロードした P1 retrieval を localhost HTTP で起動 (in-process thread)."""
    print(f"[startup] loading index {_INDEX.name} (fold={fold}) ...", file=sys.stderr)
    t0 = time.perf_counter()
    RS._SERVICE = RS.RetrievalService(_INDEX, _CORPUS, default_fold=fold)
    print(f"[startup] index loaded in {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RS.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> int:
    ap = argparse.ArgumentParser(description="B4 real-Gemini measurement (local).")
    ap.add_argument("--model", default="gemini-3.1-flash-lite")
    ap.add_argument("--top-k", type=int, default=C.DEFAULT_TOP_K)
    ap.add_argument("--limit", type=int, default=0, help="最初の N 問だけ (0=全問)")
    ap.add_argument(
        "--mock",
        action="store_true",
        help="モック provider で配線のみ検証 (実 Gemini を呼ばない・トークン/生成品質は無効)",
    )
    ap.add_argument(
        "--out-name",
        default=None,
        help="出力 JSON のファイル名 (省略時は従来どおり b4-results-g2v2.json / -mock.json)。"
        "別モデル再測時に既存結果を上書きしないために指定する",
    )
    ap.add_argument("--index", type=Path, default=None, help="索引 prefix (既定 v9)")
    ap.add_argument("--corpus", type=Path, default=None, help="索引の入力 corpus (既定 v11)")
    args = ap.parse_args()

    global _INDEX, _CORPUS
    if args.index:
        _INDEX = args.index
    if args.corpus:
        _CORPUS = args.corpus

    OUT.mkdir(parents=True, exist_ok=True)
    eval_items = build_eval_set()
    if args.limit:
        eval_items = eval_items[: args.limit]
    n = len(eval_items)
    print(f"[b4] {n} questions", file=sys.stderr)

    httpd, port = start_p1(fold=True)  # fold default ON (locked decision 2026-07-12)
    retrieval = TimingRetrieval(C.HttpRetrievalClient(f"http://127.0.0.1:{port}"))
    if args.mock:
        print("[b4] MOCK provider: wiring check only (no real Gemini)", file=sys.stderr)
        provider = TimingProvider(C.MockProvider())  # type: ignore[arg-type]
    else:
        provider = TimingProvider(C.GeminiProvider(model=args.model))

    records: list[dict] = []
    errors: list[dict] = []
    code_counts = {c: 0 for c in ("G1", "G2", "G3", "G4", "G5", "G6")}
    g2_notloc = g2_snapmismatch = g2_nobody = 0
    n_regenerated = n_fell_back = n_grounded = n_insufficient = n_retrieval_gold = 0
    total_ms: list[float] = []

    try:
        for i, item in enumerate(eval_items, 1):
            r_before = len(retrieval.retrieve_ms)
            g_before = len(provider.gen_ms)
            tok_p, tok_o = provider.prompt_toks, provider.output_toks
            sink: dict = {}
            t0 = time.perf_counter()
            try:
                resp = C.run_chat(
                    item["question"], args.top_k, retrieval, provider, debug_sink=sink
                )
            except Exception as e:  # per-question failure: record and continue
                errors.append({"id": item["id"], "error": repr(e)})
                print(f"[b4] {i}/{n} {item['id']} ERROR {e!r}", file=sys.stderr)
                continue
            q_total_ms = (time.perf_counter() - t0) * 1000.0
            total_ms.append(q_total_ms)

            hits = sink.get("hits", [])
            gold_cids = gold_hit_chunk_ids(item, hits)
            retrieval_gold = bool(gold_cids)
            cited = {c.chunk_id for c in resp.citations}
            grounded = resp.verdict != G.VERDICT_INSUFFICIENT and bool(cited & gold_cids)

            for attempt in resp.guard_report.attempts:
                for v in attempt:
                    code_counts[v["code"]] = code_counts.get(v["code"], 0) + 1
            g2 = classify_g2(resp.guard_report.attempts)
            g2_notloc += g2["anchor_not_locatable"]
            g2_snapmismatch += g2["snapped_quote_mismatch"]
            g2_nobody += g2["no_body"]

            n_regenerated += int(resp.guard_report.regenerated)
            n_fell_back += int(resp.guard_report.fell_back)
            n_grounded += int(grounded)
            n_insufficient += int(resp.verdict == G.VERDICT_INSUFFICIENT)
            n_retrieval_gold += int(retrieval_gold)

            records.append(
                {
                    "id": item["id"],
                    "source": item["source"],
                    "verdict": resp.verdict,
                    "target_layers": resp.meta.target_layers,
                    "n_hits": resp.meta.n_hits,
                    "regenerated": resp.guard_report.regenerated,
                    "fell_back": resp.guard_report.fell_back,
                    "retrieval_gold_present": retrieval_gold,
                    "grounded_correct": grounded,
                    "citation_layers": [c.layer for c in resp.citations],
                    "violations": resp.guard_report.attempts,
                    "g2_breakdown": g2,
                    "retrieve_ms": round(retrieval.retrieve_ms[r_before], 1),
                    "generate_ms": [round(x, 1) for x in provider.gen_ms[g_before:]],
                    "prompt_tokens": provider.prompt_toks - tok_p,
                    "output_tokens": provider.output_toks - tok_o,
                }
            )
            print(
                f"[b4] {i}/{n} {item['id']} verdict={resp.verdict} "
                f"grounded={grounded} regen={resp.guard_report.regenerated} "
                f"fell_back={resp.guard_report.fell_back}",
                file=sys.stderr,
            )
    finally:
        httpd.shutdown()

    n_done = len(records)
    in_cost = provider.prompt_toks / 1_000_000 * RATE_INPUT_PER_M
    out_cost = provider.output_toks / 1_000_000 * RATE_OUTPUT_PER_M
    summary = {
        "model": args.model,
        "index": _INDEX.name,
        "fold_default": True,
        "n_questions": n,
        "n_completed": n_done,
        "n_errors": len(errors),
        "grounded_correct": f"{n_grounded}/{n_done}",
        "retrieval_gold_present": f"{n_retrieval_gold}/{n_done}",
        "regenerated_rate": f"{n_regenerated}/{n_done}",
        "fell_back_rate": f"{n_fell_back}/{n_done}",
        "insufficient_rate": f"{n_insufficient}/{n_done}",
        "violation_counts": code_counts,
        "g2_breakdown": {
            "anchor_not_locatable": g2_notloc,
            "snapped_quote_mismatch": g2_snapmismatch,
            "no_body": g2_nobody,
        },
        "latency_ms": {
            "retrieve": _pctl(retrieval.retrieve_ms),
            "chunks": _pctl(retrieval.chunks_ms),
            "generate_per_call": _pctl(provider.gen_ms),
            "total_per_question": _pctl(total_ms),
        },
        "tokens": {
            "prompt_total": provider.prompt_toks,
            "output_total": provider.output_toks,
            "prompt_per_question": round(provider.prompt_toks / n_done, 1) if n_done else None,
            "output_per_question": round(provider.output_toks / n_done, 1) if n_done else None,
        },
        "cost_usd": {
            "rate_assumption_per_1M": {"input": RATE_INPUT_PER_M, "output": RATE_OUTPUT_PER_M},
            "note": "rate is an assumption to verify; tokens are measured",
            "input_total": round(in_cost, 4),
            "output_total": round(out_cost, 4),
            "total": round(in_cost + out_cost, 4),
            "per_question": round((in_cost + out_cost) / n_done, 5) if n_done else None,
        },
        "errors": errors,
    }
    report = {"summary": summary, "records": records}
    out_name = args.out_name or ("b4-results-mock.json" if args.mock else "b4-results-g2v2.json")
    out_path = OUT / out_name
    safe_write_text(out_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print("\n=== B4 summary (numbers only) ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n  report -> {out_path}")
    if g2_snapmismatch:
        print(
            f"\n*** STOP: snapped_quote_mismatch={g2_snapmismatch} (implementation bug). ***",
            file=sys.stderr,
        )
        return 1

    # ---- 合格線との照合 (mock は生成を伴わないので対象外) ----------------------
    if args.mock:
        return 0
    base = BASELINES.get(_INDEX.name)
    if base is None:
        print(
            f"\n*** STOP: no baseline recorded for index {_INDEX.name!r}. "
            f"Known: {sorted(BASELINES)}. Measure it, then record it in BASELINES. ***",
            file=sys.stderr,
        )
        return 1
    drift = []
    if n_grounded != base["grounded_correct"] or n_done != base["n_questions"]:
        drift.append(
            f"grounded {n_grounded}/{n_done} != baseline "
            f"{base['grounded_correct']}/{base['n_questions']}"
        )
    for code, want in base["violations"].items():
        if code_counts[code] != want:
            drift.append(f"{code} {code_counts[code]} != baseline {want}")
    print(f"\n=== baseline: {_INDEX.name} ({base['note']}) ===")
    if drift:
        print("*** B4 DRIFT (do not tune -- find the cause): ***", file=sys.stderr)
        for d in drift:
            print(f"    {d}", file=sys.stderr)
        return 1
    print("*** B4 PASS: reproduces the recorded baseline for this index. ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

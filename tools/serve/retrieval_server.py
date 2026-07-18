#!/usr/bin/env python3
"""JuriCode-JP resident retrieval service (PoC P1).

常駐で v8b 埋め込み索引をロードし、localhost HTTP で「出典つき検索結果」を返す
最小サービス。生成 (LLM) は行わない (P2 以降)。

設計の柱:
    - 再実装しない: dense 検索 / dedup / クエリ埋め込みは tools/embed/retrieve.py の
      既存関数 (RetrievalPipeline / dedup_by_article / _encode_queries) を import して
      再利用する。レシピのズレ (過去の事故クラス) を構造的に避ける。
    - 既定値 = A-3 測定条件に固定 (mode=dense / dedup=ON / task_type=RETRIEVAL_QUERY /
      normalize=OFF)。/healthz に既定値を出して測定条件との差分を目視できるようにする。
    - layer / corpus_group / directive_id / text は索引 meta には無いため、索引を build した
      行アライン corpus (build/corpus-v8-embed.jsonl) から供給する。起動時に
      npy 行数 == meta 行数 == corpus 行数、dim == 3072、chunk_id ユニーク、meta/corpus の
      chunk_id 行一致を fail-loud で検査する (不整合なら起動失敗、黙って動かさない)。

セキュリティ:
    --host 既定 = 127.0.0.1。0.0.0.0 等 loopback 以外は --allow-external 明示時のみ許可し
    起動時に警告を出す (search-ui と同じ鉄の規律)。

使い方:
    cd JuriCode-JP
    python tools/serve/retrieval_server.py \\
        --index build/embeddings/v0.2-aug-v8b-gemini \\
        --host 127.0.0.1 --port 8899

API (最小 3 本): GET /healthz / POST /retrieve / POST /chunks。詳細は各ハンドラの docstring。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parents[1]
MAX_BODY_BYTES = 256 * 1024  # 256KB: query / id-list text only (DOS guard)
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

# The retrieval core (index load, dense top-k, article dedup, and the numpy-free helpers)
# now lives in the juricode-retrieval package as the single source of truth. Insert its src
# on sys.path the way guards.py resolves juricode-verifier, then re-import so
# retrieval_server.X keeps working for every caller (HTTP layer, b4_eval, reproduce_a3) and
# runs the identical class object. _EMBED_DIR is left on the path for future eval reuse.
_EMBED_DIR = REPO / "tools" / "embed"
if str(_EMBED_DIR) not in sys.path:
    sys.path.insert(0, str(_EMBED_DIR))
_SHARED_SRC = REPO / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))
_RETRIEVAL_SRC = REPO / "packages" / "juricode-retrieval" / "src"
if str(_RETRIEVAL_SRC) not in sys.path:
    sys.path.insert(0, str(_RETRIEVAL_SRC))

from juricode_retrieval import (  # noqa: E402, F401  (re-export: keep retrieval_server.X)
    EXPECTED_DIM,
    RetrievalService,
    _load_corpus,
    build_dedup_keys,
    filter_row_by_layers,
    fold_taxanswer_chunk_id,
)

# =====================================================
# Pydantic request / response models (extra=forbid, frozen=True)
# =====================================================


class RetrieveRequest(BaseModel):
    """POST /retrieve の request。未知フィールドは 400 (extra='forbid')."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    target_layers: list[str] | None = None
    mode: str = "dense"
    dedup: bool = True
    # None -> サーバ既定 (--taxanswer-fold の値) を使う。明示 true/false で per-request 上書き。
    taxanswer_fold: bool | None = None


class Hit(BaseModel):
    """/retrieve の 1 ヒット。本文 (text) は返さない (Lazy: /chunks で取得)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    article_id: str | None
    directive_id: str | None
    layer: str | None
    corpus_group: str | None
    law_name_ja: str | None
    article_number: str | None
    score: float
    rank: int


class RetrieveMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: str
    elapsed_ms: float
    n_candidates: int
    defaults_applied: dict


class RetrieveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: list[Hit]
    meta: RetrieveMeta


class ChunksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_ids: list[str] = Field(min_length=1, max_length=200)


class ChunkOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    article_id: str | None
    directive_id: str | None
    layer: str | None
    corpus_group: str | None
    law_name_ja: str | None
    article_number: str | None
    text: str
    text_raw: str | None


class ChunksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunks: list[ChunkOut]
    missing: list[str]


# =====================================================
# HTTP handler
# =====================================================

_SERVICE: RetrievalService | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "JuriCodeRetrieval/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def _send_json(self, code: int, payload: dict, close: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> tuple[dict | None, int | None]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None, 400
        if length < 0:
            return None, 400
        if length > MAX_BODY_BYTES:
            return None, 413  # do NOT read the body (OOM guard)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, 400
        return (obj, None) if isinstance(obj, dict) else (None, 400)

    def do_GET(self):
        if self.path == "/healthz":
            svc = _SERVICE
            assert svc is not None
            self._send_json(
                200,
                {
                    "status": "ok",
                    "index": svc.index_prefix.name,
                    "n_records": svc.n_records,
                    "dim": svc.dim,
                    "defaults": svc.defaults(),
                },
            )
            return
        self._send_json(404, {"error": f"not found: {self.path}"})

    def do_POST(self):
        body, err = self._read_json_body()
        if err is not None:
            msg = "payload too large" if err == 413 else "invalid request body"
            self._send_json(err, {"error": msg}, close=(err == 413))
            return
        assert body is not None
        if self.path == "/retrieve":
            self._handle_retrieve(body)
            return
        if self.path == "/chunks":
            self._handle_chunks(body)
            return
        self._send_json(404, {"error": f"not found: {self.path}"})

    def _handle_retrieve(self, body: dict) -> None:
        svc = _SERVICE
        assert svc is not None
        try:
            req = RetrieveRequest(**body)
        except ValidationError as e:
            self._send_json(400, {"error": "bad_request", "detail": e.errors()})
            return
        if req.mode != "dense":
            # hybrid/BM25 は V0.4 再設計まで未サポート (PoC は dense のみ、既存経路を触らない)。
            self._send_json(
                400,
                {"error": "bad_request", "detail": f"mode {req.mode!r} not supported (dense only)"},
            )
            return
        fold = svc.default_fold if req.taxanswer_fold is None else req.taxanswer_fold
        t0 = time.perf_counter()
        try:
            query_vec = svc.encode(req.query)
            hits, n_candidates = svc.retrieve(
                query_vec, req.top_k, req.target_layers, req.dedup, fold
            )
        except Exception as e:  # surface upstream failure as 500, keep the handler thread alive
            self._send_json(500, {"error": "retrieval_failed", "detail": str(e)})
            return
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        resp = RetrieveResponse(
            hits=[Hit(**h) for h in hits],
            meta=RetrieveMeta(
                index=svc.index_prefix.name,
                elapsed_ms=round(elapsed_ms, 2),
                n_candidates=n_candidates,
                defaults_applied={
                    "mode": req.mode,
                    "dedup": req.dedup,
                    "taxanswer_subchunk_fold": fold,
                    "target_layers": req.target_layers,
                },
            ),
        )
        self._send_json(200, resp.model_dump())

    def _handle_chunks(self, body: dict) -> None:
        svc = _SERVICE
        assert svc is not None
        try:
            req = ChunksRequest(**body)
        except ValidationError as e:
            self._send_json(400, {"error": "bad_request", "detail": e.errors()})
            return
        chunks, missing = svc.chunks(req.chunk_ids)
        resp = ChunksResponse(chunks=[ChunkOut(**c) for c in chunks], missing=missing)
        self._send_json(200, resp.model_dump())


# =====================================================
# CLI
# =====================================================


def _check_host(host: str, allow_external: bool) -> bool:
    """Return is_external. Raise ValueError on non-loopback bind without --allow-external.

    Why: query text を扱うサービスを誤って 0.0.0.0 等で外部公開する事故を構造的に防ぐ
    (search-ui と同じ鉄の規律)。
    """
    is_external = host not in _LOOPBACK
    if is_external and not allow_external:
        raise ValueError(
            f"refusing to bind non-loopback host {host!r} without --allow-external "
            "(retrieval service receives query text; keep local-only)"
        )
    return is_external


def build_service(args) -> RetrievalService:
    """引数から RetrievalService を構築 (テストから再利用可能に分離)."""
    return RetrievalService(
        index_prefix=args.index,
        corpus_path=args.corpus,
        default_fold=not args.no_taxanswer_fold,
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # 索引・corpus に既定値を持たせない (L-INDEX)。
    # Why: 既定があると、呼び出し側が指定を忘れたときに **黙って別の索引で答える**。
    # 索引が変われば返る条文が変わる。どの索引で答えたのかは、サービスが暗黙に決めて
    # よいことではない。指定が無ければ起動時に落とす。
    # (どの索引で答えたかは、全レスポンスの meta.index にも出している。)
    ap.add_argument(
        "--index",
        type=Path,
        required=True,
        help="embedding 索引プレフィックス (.npy/.meta.jsonl/.vec.pkl)。既定値なし",
    )
    ap.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="行アライン corpus (layer/corpus_group/directive_id/text の供給元)。既定値なし",
    )
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument(
        "--allow-external",
        action="store_true",
        help="loopback 以外への bind を許可 (query text を受けるため既定で禁止)",
    )
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument(
        "--no-taxanswer-fold",
        action="store_true",
        help="taxanswer sub-chunk (-subN) の dedup 畳み込みを無効化 (既定は畳み込み ON = PoC)",
    )
    args = ap.parse_args()

    try:
        external = _check_host(args.host, args.allow_external)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    if external:
        print(
            "[security] WARNING: --allow-external set; service is exposed to non-loopback "
            "interfaces. Do NOT run on untrusted networks (query text is received).",
            file=sys.stderr,
        )

    global _SERVICE
    print(f"[startup] loading index from {args.index}.* ...", file=sys.stderr)
    try:
        _SERVICE = build_service(args)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"ERROR: {e}")
    print(
        f"[startup] {_SERVICE.n_records:,} records, dim={_SERVICE.dim}, "
        f"provider={_SERVICE.state.get('provider')} model={_SERVICE.state.get('model')}, "
        f"taxanswer_fold={_SERVICE.default_fold}",
        file=sys.stderr,
    )
    print(
        "[security] LOCAL-ONLY by default (127.0.0.1). Use --allow-external only on trusted "
        "networks (this service receives raw query text).",
        file=sys.stderr,
    )

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[ready] http://{args.host}:{args.port}/  (Ctrl-C to stop)", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[shutdown]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

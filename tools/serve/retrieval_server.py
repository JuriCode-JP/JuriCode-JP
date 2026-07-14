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
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parents[1]
MAX_BODY_BYTES = 256 * 1024  # 256KB: query / id-list text only (DOS guard)
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
EXPECTED_DIM = 3072  # gemini-embedding-001
_SUBCHUNK_RE = re.compile(r"-sub\d+$")  # taxanswer sub-chunk suffix (FU-553 PoC fold)

# retrieve.py lives in tools/embed/; reuse its committed retrieval machinery so the math is
# identical to the production CLI (no re-implementation drift).
_EMBED_DIR = REPO / "tools" / "embed"
if str(_EMBED_DIR) not in sys.path:
    sys.path.insert(0, str(_EMBED_DIR))
_SHARED_SRC = REPO / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))


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
# Pure helpers (numpy-free; unit-testable everywhere)
# =====================================================


def fold_taxanswer_chunk_id(chunk_id: str, layer: str | None) -> str:
    """taxanswer sub-chunk の chunk_id から '-subN' を落とした doc key を返す (FU-553 PoC).

    Why: taxanswer は article_id も directive_id も持たない -> 既定の dedup キーは chunk_id に
    fallback し、同一タックスアンサーの sub-chunk (例 '...-2011-sub2') が top-K の複数枠を
    占有し得る。layer=='taxanswer' の sub-chunk のみ接尾辞を畳んで doc 単位に dedup する。
    非 taxanswer や sub 無しはそのまま (honbun の '-art-1-p1' 等を誤って畳まない)。
    """
    if layer == "taxanswer" and _SUBCHUNK_RE.search(chunk_id):
        return _SUBCHUNK_RE.sub("", chunk_id)
    return chunk_id


def build_dedup_keys(
    base_keys: list[str], chunk_ids: list[str], layers: list[str | None], fold: bool
) -> list[str]:
    """dedup キー列を返す。fold=False なら base_keys をそのまま (A-3 測定条件と同一)。

    Why: base_keys = article_id else chunk_id (RetrievalPipeline._dedup_keys と同一規則で、
    索引 meta に directive_id が無いため A-3 の _match_keys と一致)。fold=True のときだけ
    taxanswer sub-chunk を doc key に畳む。これにより「畳み込み OFF = A-3 再現」「ON = PoC 改善」を
    同一コードで切替でき、サイレント乖離を防ぐ。
    """
    if not fold:
        return list(base_keys)
    out: list[str] = []
    for bk, cid, lay in zip(base_keys, chunk_ids, layers, strict=True):
        # taxanswer は base_key が chunk_id (article_id 無し) なので、その chunk_id を畳む。
        out.append(fold_taxanswer_chunk_id(cid, lay) if lay == "taxanswer" else bk)
    return out


def filter_row_by_layers(
    idx_row: list[int], layers: list[str | None], target_layers: list[str] | None
) -> list[int]:
    """候補 index 列を target_layers で事前フィルタ (順序保持)。null なら全層 (無変更)。

    Why (§3.5): target_layers は boost ではなく filter。呼び出し側が明示指定した layer のみを
    候補プールに残し、その後に dedup + top-K を適用する。自動 boost (A3-F) は実装しない。
    """
    if not target_layers:
        return list(idx_row)
    allowed = set(target_layers)
    return [i for i in idx_row if i >= 0 and layers[i] in allowed]


# =====================================================
# RetrievalService (numpy-backed; loaded once at startup)
# =====================================================


class RetrievalService:
    """v8b 索引と行アライン corpus を常駐ロードし、dense+dedup 検索を提供する (1 責務).

    Why lazy import: numpy は宣言依存でなく retrieve.py 同様 method 内 import。--help / schema
    テストは numpy 無し環境でも通す (cold start / CI 非依存の規律)。
    """

    def __init__(self, index_prefix: Path, corpus_path: Path, default_fold: bool):
        import numpy as np  # lazy import
        import retrieve as R  # tools/embed/retrieve.py

        self._R = R
        self.index_prefix = index_prefix
        self.corpus_path = corpus_path
        self.default_fold = default_fold

        matrix, records, state = R._load_artefacts(index_prefix)
        self.state = state
        self.records = records
        n = len(records)

        # ---- fail-loud integrity checks (§3.4): 黙って動かさない ----
        if matrix.shape[0] != n:
            raise ValueError(f"npy rows ({matrix.shape[0]}) != meta rows ({n})")
        if matrix.shape[1] != EXPECTED_DIM:
            raise ValueError(f"dim ({matrix.shape[1]}) != expected {EXPECTED_DIM}")
        meta_chunk_ids = [r.get("chunk_id") for r in records]
        if len(set(meta_chunk_ids)) != n:
            raise ValueError(f"chunk_id not unique in meta ({len(set(meta_chunk_ids))} of {n})")

        # ---- row-aligned corpus supplies layer / corpus_group / directive_id / text ----
        # (これらは索引 meta に無い。A-3 harness と同じ行アライン corpus から供給する。)
        corpus_rows = _load_corpus(corpus_path)
        if len(corpus_rows) != n:
            raise ValueError(f"corpus rows ({len(corpus_rows)}) != meta rows ({n})")
        corpus_chunk_ids = [r.get("chunk_id") for r in corpus_rows]
        if corpus_chunk_ids != meta_chunk_ids:
            first = next((i for i in range(n) if corpus_chunk_ids[i] != meta_chunk_ids[i]), -1)
            raise ValueError(f"corpus/meta chunk_id row misalignment (first at row {first})")

        self.chunk_ids = meta_chunk_ids
        self.layers: list[str | None] = [r.get("layer") for r in corpus_rows]
        self.corpus_groups: list[str | None] = [r.get("corpus_group") for r in corpus_rows]
        self.directive_ids: list[str | None] = [r.get("directive_id") for r in corpus_rows]
        self.law_name_ja: list[str | None] = [r.get("law_name_ja") for r in records]
        self.article_ids: list[str | None] = [r.get("article_id") for r in records]
        self.article_number: list[str | None] = [r.get("article_number") for r in records]
        self._texts: list[str] = [r.get("text") or "" for r in corpus_rows]
        self._texts_raw: list[str | None] = [r.get("text_raw") for r in corpus_rows]
        self._chunk_pos = {c: i for i, c in enumerate(self.chunk_ids)}

        # RetrievalPipeline は META records で構築する。meta に directive_id が無いため
        # pipeline._dedup_keys = article_id else chunk_id となり A-3 の _match_keys と一致する
        # (T6 再現の要)。dedup 実体は R.dedup_by_article を再利用。
        self._pipeline = R.RetrievalPipeline(state, records)
        self._base_keys = self._pipeline._dedup_keys

        # fold precompute (§3.6 P2): dedup キー列を fold OFF/ON 両方で起動時に構築し、
        # リクエスト毎の build_dedup_keys 再構築 (+16ms) を解消する。挙動不変 (同関数の
        # 出力を起動時にキャッシュするだけ)。retrieve() は fold 値でこの 2 本から選ぶ。
        self._keys_fold_off: list[str] = list(self._base_keys)
        self._keys_fold_on: list[str] = build_dedup_keys(
            self._base_keys, self.chunk_ids, self.layers, fold=True
        )

        # 事前正規化 (常駐サービスの標準形。server.py と同じ)。_cosine_topk と同一の正規化式で
        # corpus を 1 回だけ正規化し、クエリ時は正規化クエリとの内積 + argsort に落とす。
        # 結果は _cosine_topk と数学的に同一 (T6 が S 相当の等価ゲートとして保証する)。
        cn = np.linalg.norm(matrix, axis=1, keepdims=True)
        cn[cn == 0] = 1.0
        self._norm_matrix = (matrix / cn).astype(np.float32)
        del matrix
        self.n_records = n
        self.dim = EXPECTED_DIM

    # ---- encode ----
    def encode(self, query: str):
        """1 クエリを埋め込みに変換 (1, dim)。retrieve._encode_queries を再利用 (A-3 と同一経路)."""
        return self._R._encode_queries([query], self.state)

    # ---- retrieval ----
    def dense_pool(self, query_vec, pool: int):
        """事前正規化 corpus に対する dense top-`pool` の (sims_row, idx_row) を返す。

        _cosine_topk と同一 (query 正規化 -> 内積 -> argsort(-sims))。corpus 正規化のみ
        起動時に前倒し済み。
        """
        import numpy as np  # lazy import

        qn = np.linalg.norm(query_vec, axis=1, keepdims=True)
        qn[qn == 0] = 1.0
        qnorm = (query_vec / qn).astype(np.float32)
        sims = (qnorm @ self._norm_matrix.T)[0]  # (N,)
        idx_row = np.argsort(-sims)[:pool]
        return sims, idx_row

    def retrieve(
        self,
        query_vec,
        top_k: int,
        target_layers: list[str] | None,
        dedup: bool,
        fold: bool,
    ) -> tuple[list[dict], int]:
        """dense -> (target_layers filter) -> (dedup) -> top-K。hit dict のリストと候補数を返す."""
        import numpy as np  # lazy import

        # candidate pool: A-3 は CANDIDATE_POOL=60 (top_k=20)。dedup で unique-K を賄える幅を確保。
        # >=60 なら top-K unique は dense 上位から決まり pool 幅に不感 (T6 が確認)。
        pool = max(top_k * 3, 60)
        sims, idx_row = self.dense_pool(query_vec, pool)
        idx_list = [int(i) for i in idx_row]
        n_candidates = len(idx_list)

        idx_list = filter_row_by_layers(idx_list, self.layers, target_layers)

        if dedup:
            # 起動時 precompute 済みのキー列を選ぶ (build_dedup_keys の出力と同一・挙動不変)。
            keys = self._keys_fold_on if fold else self._keys_fold_off
            deduped = self._R.dedup_by_article(np.array([idx_list], dtype=np.int64), keys, top_k)
            final = [int(i) for i in deduped[0] if int(i) >= 0]
        else:
            final = idx_list[:top_k]

        hits: list[dict] = []
        for rank, i in enumerate(final, start=1):
            hits.append(
                {
                    "chunk_id": self.chunk_ids[i],
                    "article_id": self.article_ids[i],
                    "directive_id": self.directive_ids[i],
                    "layer": self.layers[i],
                    "corpus_group": self.corpus_groups[i],
                    "law_name_ja": self.law_name_ja[i],
                    "article_number": self.article_number[i],
                    "score": float(sims[i]),
                    "rank": rank,
                }
            )
        return hits, n_candidates

    def chunks(self, chunk_ids: list[str]) -> tuple[list[dict], list[str]]:
        """chunk_id -> 本文つき chunk dict。見つからない id は missing に返す (Lazy 本文取得)."""
        out: list[dict] = []
        missing: list[str] = []
        for cid in chunk_ids:
            i = self._chunk_pos.get(cid)
            if i is None:
                missing.append(cid)
                continue
            out.append(
                {
                    "chunk_id": self.chunk_ids[i],
                    "article_id": self.article_ids[i],
                    "directive_id": self.directive_ids[i],
                    "layer": self.layers[i],
                    "corpus_group": self.corpus_groups[i],
                    "law_name_ja": self.law_name_ja[i],
                    "article_number": self.article_number[i],
                    "text": self._texts[i],
                    "text_raw": self._texts_raw[i],
                }
            )
        return out, missing

    def defaults(self) -> dict:
        """/healthz が出す既定値 (測定条件との差分を目視できるようにする)."""
        return {
            "mode": "dense",
            "dedup": True,
            "task_type": "RETRIEVAL_QUERY",
            "normalize": False,
            "taxanswer_subchunk_fold": self.default_fold,
        }


def _load_corpus(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


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

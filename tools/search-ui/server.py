#!/usr/bin/env python3
"""JuriCode-JP 検索 UI プロトタイプ -- ローカル HTTP サーバ.

ゼロ依存の Python stdlib http.server で動作 (Gemini provider のときだけ
google-genai が必要).

使い方:
    cd JuriCode-JP
    # 事前に tools/embed/embed.py で artefacts を生成しておくこと
    python tools/search-ui/server.py \\
        --embedded build/juricode-bq-embedded \\
        --port 8765

    # ブラウザで http://localhost:8765/ を開く

オプション:
    --embedded PATH    artefacts のプレフィックス (.npy/.meta.jsonl/.vec.pkl)
    --port PORT        listen ポート (default 8765)
    --host HOST        bind アドレス (default 127.0.0.1)
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
INDEX_HTML = SCRIPT_DIR / "index.html"

# Globals populated at startup
_MATRIX: np.ndarray | None = None
_RECORDS: list[dict] | None = None
_STATE: dict | None = None
_NORM_MATRIX: np.ndarray | None = None  # pre-normalized for fast cosine


def _load_artefacts(prefix: Path) -> tuple[np.ndarray, list[dict], dict]:
    # NOTE: with_suffix() は "v0.2-gemini-17967" のようなドット含み名で
    # ".2-gemini-17967" を suffix と解釈して壊す。文字列連結で回避。
    # embed.py:295 / retrieve.py:418 と同じパターン (FU-404).
    npy_path = prefix.parent / (prefix.name + ".npy")
    meta_path = prefix.parent / (prefix.name + ".meta.jsonl")
    vec_path = prefix.parent / (prefix.name + ".vec.pkl")
    missing = [str(p) for p in (npy_path, meta_path, vec_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing artefact(s): {missing}")

    matrix = np.load(npy_path)
    records: list[dict] = []
    with meta_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    with vec_path.open("rb") as fh:
        state = pickle.load(fh)
    return matrix, records, state


def _normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def _encode_query(question: str) -> np.ndarray:
    """1 件のクエリを embedding に変換 (1, dim) の ndarray."""
    state = _STATE
    assert state is not None
    provider = state.get("provider")

    if provider == "tfidf":
        v = state["vectorizer"]
        return v.transform([question]).astype(np.float32).toarray()

    if provider == "openai":
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(model=state["model"], input=[question])
        return np.asarray([resp.data[0].embedding], dtype=np.float32)

    if provider == "gemini":
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")
        client = genai.Client(api_key=api_key)
        resp = client.models.embed_content(
            model=state["model"],
            contents=[question],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        return np.asarray([resp.embeddings[0].values], dtype=np.float32)

    raise RuntimeError(f"Unsupported provider: {provider!r}")


def _topk(question: str, k: int = 10) -> list[dict]:
    assert _MATRIX is not None and _RECORDS is not None and _NORM_MATRIX is not None
    q_mat = _encode_query(question)
    q_norm = _normalize(q_mat)  # (1, dim)
    sims = (q_norm @ _NORM_MATRIX.T)[0]  # (N,)
    top_idx = np.argsort(-sims)[:k]
    results = []
    for rank, i in enumerate(top_idx, 1):
        rec = _RECORDS[i]
        results.append(
            {
                "rank": rank,
                "score": float(sims[i]),
                "article_id": rec.get("article_id"),
                "law_name_ja": rec.get("law_name_ja"),
                "law_id": rec.get("law_id"),
                "article_number": rec.get("article_number"),
                "phase_category": rec.get("phase_category"),
                "hen_name_ja": rec.get("hen_name_ja"),
                "shou_name_ja": rec.get("shou_name_ja"),
                "chunk_id": rec.get("chunk_id"),
                "source_url": (
                    f"https://laws.e-gov.go.jp/law/{rec.get('law_id')}"
                    if rec.get("law_id")
                    else None
                ),
            }
        )
    return results


class Handler(BaseHTTPRequestHandler):
    server_version = "JuriCodeSearchUI/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def _send_json(self, code: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError as e:
            self._send_json(500, {"error": f"cannot read {path.name}: {e}"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/api/info":
            assert _STATE is not None and _MATRIX is not None and _RECORDS is not None
            self._send_json(
                200,
                {
                    "provider": _STATE.get("provider"),
                    "model": _STATE.get("model"),
                    "dim": int(_MATRIX.shape[1]),
                    "corpus_size": len(_RECORDS),
                },
            )
            return
        if parsed.path == "/api/search":
            qs = parse_qs(parsed.query)
            q = (qs.get("q") or [""])[0].strip()
            try:
                k = int((qs.get("k") or ["10"])[0])
            except ValueError:
                k = 10
            k = max(1, min(50, k))
            if not q:
                self._send_json(400, {"error": "missing q"})
                return
            try:
                results = _topk(q, k)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, {"query": q, "k": k, "results": results})
            return
        self._send_json(404, {"error": f"not found: {parsed.path}"})


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--embedded",
        type=Path,
        required=True,
        help="embedding artefacts のプレフィックス (例: build/juricode-bq-embedded)",
    )
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    global _MATRIX, _RECORDS, _STATE, _NORM_MATRIX
    print(f"[startup] loading artefacts from {args.embedded}.*", file=sys.stderr)
    try:
        _MATRIX, _RECORDS, _STATE = _load_artefacts(args.embedded)
    except FileNotFoundError as e:
        sys.exit(f"ERROR: {e}")
    _NORM_MATRIX = _normalize(_MATRIX)
    print(
        f"[startup] {len(_RECORDS):,} records, dim={_MATRIX.shape[1]}, "
        f"provider={_STATE.get('provider')} model={_STATE.get('model')}",
        file=sys.stderr,
    )

    if not INDEX_HTML.exists():
        print(f"WARN: {INDEX_HTML} not found -- UI will be unavailable", file=sys.stderr)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"[ready] open {url} in your browser  (Ctrl-C to stop)", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[shutdown]", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""JuriCode-JP 検索 UI プロトタイプ -- ローカル HTTP サーバ.

ゼロ依存の Python stdlib http.server で動作 (Gemini provider のときだけ
google-genai が必要). 質問ログ 4 原材料 (質問文 / feedback / click / dwell) を
SQLite (juricode_shared.qlog) に記録する POST API を備える.

使い方:
    cd JuriCode-JP
    # 事前に tools/embed/embed.py で artefacts を生成しておくこと
    python tools/search-ui/server.py \\
        --embedded build/juricode-bq-embedded \\
        --corpus-version v0.2 \\
        --port 8765

    # ブラウザで http://localhost:8765/ を開く

オプション:
    --embedded PATH        artefacts のプレフィックス (.npy/.meta.jsonl/.vec.pkl)
    --corpus-version VER   ログに記録する corpus 版 (必須)
    --log-db PATH          質問ログ SQLite (default build/search-ui-logs.db)
    --port PORT            listen ポート (default 8765)
    --host HOST            bind アドレス (default 127.0.0.1)

セキュリティ (重要):
    質問文は匿名化前の raw でログ記録される (PII フィルタは後続フェーズ). 注意書き
    バナーと PII フィルタが本番投入されるまで, 127.0.0.1 ローカル限定で起動し外部公開
    しないこと.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sqlite3
import sys
import uuid
from datetime import datetime

# Python 3.11+ exports `datetime.UTC`. Cowork sandbox uses 3.10 which lacks it.
# CI runs 3.11/3.12 where the direct import works. Backport keeps both happy.
try:
    from datetime import UTC
except ImportError:  # pragma: no cover (3.10 sandbox only)
    from datetime import timezone as _tz

    UTC = _tz.utc  # noqa: UP017  (3.10 fallback; ruff can not see the try branch above)
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    import numpy as np  # type hints only; runtime import inside functions

SCRIPT_DIR = Path(__file__).resolve().parent
INDEX_HTML = SCRIPT_DIR / "index.html"
MAX_BODY_BYTES = 256 * 1024  # 256KB: question/comment text only (DOS guard)
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})  # FU-414: safe bind hosts

# Make juricode_shared importable (same sys.path pattern as other runtime tools)
_SHARED_SRC = SCRIPT_DIR.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared.anonymize import anonymize_text, detect_pii  # noqa: E402
from juricode_shared.qlog import store  # noqa: E402
from juricode_shared.qlog.schema import (  # noqa: E402
    ClickEntry,
    FeedbackEntry,
    QuestionLog,
    ResultEntry,
)
from pydantic import ValidationError  # noqa: E402  (must follow sys.path tweak)

# Globals populated at startup
_MATRIX: np.ndarray | None = None
_RECORDS: list[dict] | None = None
_STATE: dict | None = None
_NORM_MATRIX: np.ndarray | None = None  # pre-normalized for fast cosine
_LOG_DB: Path | None = None
_CORPUS_VERSION: str | None = None


def _load_artefacts(prefix: Path) -> tuple[np.ndarray, list[dict], dict]:
    import numpy as np  # lazy import (FU-506)

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
    import numpy as np  # lazy import (FU-506)

    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def _encode_query(question: str) -> np.ndarray:
    """1 件のクエリを embedding に変換 (1, dim) の ndarray."""
    import numpy as np  # lazy import (FU-506)

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
    import numpy as np  # lazy import (FU-506)

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

    def _send_json(self, code: int, payload: dict | list, close: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if close:
            # CONN: half-close so an unread request body cannot desync keep-alive.
            self.send_header("Connection", "close")
            self.close_connection = True
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

    def _read_json_body(self) -> tuple[dict | None, int | None]:
        """Return (body, None) on success, or (None, http_code) on failure.

        Why: Content-Length の int 化失敗 / 上限超過 / JSON 不正 / 非 dict をここで吸収し
        handler スレッドを例外で壊さない. 上限超は read せず 413 (OOM/ハング回避).
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None, 400
        if length < 0:
            return None, 400
        if length > MAX_BODY_BYTES:
            return None, 413  # do NOT read the body
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, 400
        return (obj, None) if isinstance(obj, dict) else (None, 400)

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
        if parsed.path == "/api/health":
            try:
                count = store.count_questions(_LOG_DB) if _LOG_DB is not None else 0
            except sqlite3.Error as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, {"ok": True, "log_db": str(_LOG_DB), "count": count})
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

    def do_POST(self):
        parsed = urlparse(self.path)
        body, err = self._read_json_body()
        if err is not None:
            msg = "payload too large" if err == 413 else "invalid request body"
            self._send_json(err, {"error": msg}, close=(err == 413))
            return
        assert body is not None
        if parsed.path == "/api/question":
            self._handle_question(body)
            return
        if parsed.path == "/api/feedback":
            self._handle_feedback(body)
            return
        if parsed.path == "/api/click":
            self._handle_click(body)
            return
        self._send_json(404, {"error": f"not found: {parsed.path}"})

    def _handle_question(self, body: dict) -> None:
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            self._send_json(400, {"error": "bad_request", "detail": "question required"})
            return
        body_k = body.get("k", 10)
        if not isinstance(body_k, int) or isinstance(body_k, bool):
            self._send_json(400, {"error": "bad_request", "detail": "k must be an integer"})
            return
        actual_k = max(1, min(50, body_k))  # 0/-1 -> 1 (same clamp as /api/search)
        try:
            topk = _topk(question, actual_k)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        assert _STATE is not None
        qid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        # Tier 1 PII gating (Phase D): on detection, do NOT store raw; keep only the
        # anonymized version + the matched pattern names (V2-3). Search still runs.
        detected, patterns = detect_pii(question)
        try:
            qlog = QuestionLog(
                id=qid,
                session_id=body.get("session_id"),
                asked_at=now,
                question_text=None if detected else question,
                question_text_anonymized=anonymize_text(question) if detected else None,
                pii_detected=1 if detected else 0,
                pii_pattern_matched=",".join(patterns) if detected else None,
                k=actual_k,
                embedder=_STATE.get("provider") or "unknown",
                corpus_version=_CORPUS_VERSION or "unknown",
            )
            results = [
                ResultEntry(rank=r["rank"], article_id=r["article_id"], score=r["score"])
                for r in topk
            ]
        except ValidationError as e:
            self._send_json(400, {"error": "bad_request", "detail": str(e)})
            return
        if not self._record(store.record_question_with_results, _LOG_DB, qlog, results):
            return
        self._send_json(
            200, {"question_id": qid, "k": actual_k, "results": topk, "pii_detected": detected}
        )

    def _handle_feedback(self, body: dict) -> None:
        try:
            fb = FeedbackEntry(
                id=str(uuid.uuid4()),
                question_id=body.get("question_id"),
                given_at=datetime.now(UTC).isoformat(),
                signal=body.get("signal"),
                comment=body.get("comment"),
            )
        except ValidationError as e:
            self._send_json(400, {"error": "bad_request", "detail": str(e)})
            return
        if not self._record(store.record_feedback, _LOG_DB, fb):
            return
        self._send_json(200, {"ok": True, "feedback_id": fb.id})

    def _handle_click(self, body: dict) -> None:
        dwell = body.get("dwell_seconds")
        if dwell is not None and (
            isinstance(dwell, bool)
            or not isinstance(dwell, (int, float))
            or not math.isfinite(dwell)
        ):
            self._send_json(
                400, {"error": "bad_request", "detail": "dwell_seconds must be a finite number"}
            )
            return
        try:
            click = ClickEntry(
                id=str(uuid.uuid4()),
                question_id=body.get("question_id"),
                clicked_at=datetime.now(UTC).isoformat(),
                rank=body.get("rank"),
                article_id=body.get("article_id"),
                dwell_seconds=dwell,
            )
        except ValidationError as e:
            self._send_json(400, {"error": "bad_request", "detail": str(e)})
            return
        if not self._record(store.record_click, _LOG_DB, click):
            return
        self._send_json(200, {"ok": True, "click_id": click.id})

    def _record(self, fn, *args) -> bool:
        """Run a store.record_* call, mapping DB errors to HTTP. Returns True on success.

        Why: FK 違反 (未知 question_id) は client error (400)、'database is locked' は
        一時障害 (503 + stderr warning + retry promote) として一元処理する.
        """
        try:
            fn(*args)
            return True
        except sqlite3.IntegrityError as e:
            self._send_json(400, {"error": "bad_request", "detail": f"constraint: {e}"})
            return False
        except sqlite3.OperationalError as e:
            sys.stderr.write(f"[qlog] OperationalError: {e}\n")
            self._send_json(503, {"error": "log store busy, please retry"})
            return False


def _check_host(host: str, allow_external: bool) -> bool:
    """Return is_external. Raise ValueError on a non-loopback bind without --allow-external.

    Why (FU-414 / R5): raw query を記録する UI を誤って 0.0.0.0 / :: 等で外部公開し漏洩
    する事故を構造的に防ぐ. loopback 以外への bind は --allow-external を必須にする.
    """
    is_external = host not in _LOOPBACK
    if is_external and not allow_external:
        raise ValueError(
            f"refusing to bind non-loopback host {host!r} without --allow-external "
            "(search-ui records query text; see CLAUDE.md local-only rule)"
        )
    return is_external


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
    ap.add_argument(
        "--corpus-version",
        type=str,
        required=True,
        help="質問ログに記録する corpus 版 (例: v0.2)",
    )
    ap.add_argument(
        "--log-db",
        type=Path,
        default=SCRIPT_DIR.parent.parent / "build" / "search-ui-logs.db",
        help="質問ログ SQLite のパス (default build/search-ui-logs.db)",
    )
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument(
        "--allow-external",
        action="store_true",
        help="loopback 以外の host への bind を許可 (query text を記録するため既定で禁止)",
    )
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    # Fail-fast: validate the bind host before the heavy artefact load (R5 / FU-414).
    try:
        external = _check_host(args.host, args.allow_external)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    if external:
        print(
            "[security] WARNING: --allow-external set; UI is exposed to non-loopback "
            "interfaces. Do NOT run on untrusted networks (query text is recorded).",
            file=sys.stderr,
        )

    global _MATRIX, _RECORDS, _STATE, _NORM_MATRIX, _LOG_DB, _CORPUS_VERSION
    print(f"[startup] loading artefacts from {args.embedded}.*", file=sys.stderr)
    try:
        _MATRIX, _RECORDS, _STATE = _load_artefacts(args.embedded)
    except FileNotFoundError as e:
        sys.exit(f"ERROR: {e}")
    _NORM_MATRIX = _normalize(_MATRIX)
    _LOG_DB = args.log_db
    _CORPUS_VERSION = args.corpus_version
    store.init_db(_LOG_DB)
    print(
        f"[startup] {len(_RECORDS):,} records, dim={_MATRIX.shape[1]}, "
        f"provider={_STATE.get('provider')} model={_STATE.get('model')}",
        file=sys.stderr,
    )
    print(
        f"[startup] question log -> {_LOG_DB} (corpus_version={_CORPUS_VERSION})", file=sys.stderr
    )
    print(
        "[security] LOCAL-ONLY by default (127.0.0.1). Question text is PII-filtered "
        "before storage (raw dropped on detection). Use --allow-external only on trusted networks.",
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

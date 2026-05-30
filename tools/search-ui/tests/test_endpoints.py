"""Smoke / integration tests for search-ui POST API (Phase B).

Why this test exists:
    Pins the question-log POST endpoints end-to-end without numpy/artefacts
    (via a monkeypatched _topk that returns full-shape result dicts). Covers
    happy paths, input guards (JSON / k type / dwell finiteness), FK errors,
    the k-clamp consistency (questions.k == len(results)), the 413 body cap,
    and the same do_GET regression. Server lifecycle uses a yield fixture with
    guaranteed teardown so an assertion failure cannot leak a port/thread.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

# make tools/search-ui importable
_SEARCH_UI = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

if str(_SEARCH_UI) not in sys.path:
    sys.path.insert(0, str(_SEARCH_UI))

import server  # noqa: E402


def _mock_topk(question: str, k: int = 10) -> list[dict]:
    """Return k full-shape result dicts (same keys as the real _topk)."""
    return [
        {
            "rank": i,
            "score": 1.0 / i,
            "article_id": f"keihou-art-{i}",
            "law_name_ja": "刑法",
            "law_id": "129AC0000000045",
            "article_number": str(i),
            "phase_category": "phase1-police",
            "hen_name_ja": None,
            "shou_name_ja": None,
            "chunk_id": f"c{i}",
            "source_url": "https://laws.e-gov.go.jp/law/x",
        }
        for i in range(1, k + 1)
    ]


@pytest.fixture()
def srv(tmp_path: Path, monkeypatch):
    db = tmp_path / "logs.db"
    server.store.init_db(db)
    monkeypatch.setattr(server, "_LOG_DB", db)
    monkeypatch.setattr(server, "_CORPUS_VERSION", "v0.2")
    monkeypatch.setattr(server, "_STATE", {"provider": "tfidf", "model": "test"})
    monkeypatch.setattr(server, "_topk", _mock_topk)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{port}", db
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=5)


def _request(method: str, url: str, payload=None, raw: bytes | None = None):
    """Return (status, body). Captures HTTPError so failures carry the server message."""
    data = (
        raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    )
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text


def _ask(base: str, question: str = "正当防衛とは", k=None):
    payload = {"question": question, "session_id": str(uuid.uuid4())}
    if k is not None:
        payload["k"] = k
    return _request("POST", base + "/api/question", payload)


def test_e1_question(srv) -> None:
    base, db = srv
    code, body = _ask(base)
    assert code == 200, body
    uuid.UUID(body["question_id"])  # valid UUID
    assert len(body["results"]) == 10
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 10
    con.close()


def test_e2_feedback(srv) -> None:
    base, db = srv
    qid = _ask(base)[1]["question_id"]
    for sig in ("good", "bad"):
        code, body = _request("POST", base + "/api/feedback", {"question_id": qid, "signal": sig})
        assert code == 200, body
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 2
    con.close()


def test_e3_click_raw_null(srv) -> None:
    base, db = srv
    qid = _ask(base)[1]["question_id"]
    code, body = _request(
        "POST",
        base + "/api/click",
        {"question_id": qid, "rank": 1, "article_id": "a", "dwell_seconds": 30.0},
    )
    assert code == 200, body
    con = sqlite3.connect(db)
    assert con.execute("SELECT dwell_seconds, dwell_seconds_raw FROM clicks").fetchone() == (
        30.0,
        None,
    )
    con.close()


def test_e4_click_capped(srv) -> None:
    base, db = srv
    qid = _ask(base)[1]["question_id"]
    _request(
        "POST",
        base + "/api/click",
        {"question_id": qid, "rank": 1, "article_id": "a", "dwell_seconds": 500.0},
    )
    con = sqlite3.connect(db)
    assert con.execute("SELECT dwell_seconds, dwell_seconds_raw FROM clicks").fetchone() == (
        300.0,
        500.0,
    )
    con.close()


def test_e5_health(srv) -> None:
    base, _ = srv
    _ask(base)
    code, body = _request("GET", base + "/api/health")
    assert code == 200, body
    assert body["ok"] is True
    assert body["count"] == 1


def test_e6_bad_json(srv) -> None:
    base, _ = srv
    code, _body = _request("POST", base + "/api/question", raw=b"not-json{{")
    assert code == 400


def test_e7_missing_question(srv) -> None:
    base, _ = srv
    code, _body = _request("POST", base + "/api/question", {"session_id": str(uuid.uuid4())})
    assert code == 400


def test_e8_unknown_question_id_feedback(srv) -> None:
    base, _ = srv
    code, _body = _request(
        "POST", base + "/api/feedback", {"question_id": str(uuid.uuid4()), "signal": "good"}
    )
    assert code == 400  # FK violation


def test_e9_non_finite_dwell(srv) -> None:
    base, _ = srv
    qid = _ask(base)[1]["question_id"]
    code, _body = _request(
        "POST",
        base + "/api/click",
        {"question_id": qid, "rank": 1, "article_id": "a", "dwell_seconds": float("inf")},
    )
    assert code == 400


def test_e10_bad_signal(srv) -> None:
    base, _ = srv
    qid = _ask(base)[1]["question_id"]
    code, _body = _request("POST", base + "/api/feedback", {"question_id": qid, "signal": "maybe"})
    assert code == 400


def test_e11_search_regression(srv) -> None:
    base, _ = srv
    code, body = _request("GET", base + "/api/search?q=" + urllib.request.quote("正当防衛"))
    assert code == 200, body
    assert body["results"]


def test_e12_oversized_413(srv) -> None:
    base, _ = srv
    host, port = base.split("//")[1].split(":")
    s = socket.create_connection((host, int(port)), timeout=5)
    # Send headers only (no body) with an oversized Content-Length -> server must 413 without reading.
    req = (
        f"POST /api/click HTTP/1.1\r\nHost: {host}\r\n"
        f"Content-Type: application/json\r\nContent-Length: {300 * 1024}\r\n\r\n"
    )
    s.sendall(req.encode())
    resp = s.recv(4096).decode("latin-1")
    s.close()
    assert "413" in resp.split("\r\n")[0], resp


def test_e13_k_clamp_consistency(srv) -> None:
    base, db = srv
    code, body = _ask(base, k=100)
    assert code == 200, body
    assert body["k"] == 50
    assert len(body["results"]) == 50
    con = sqlite3.connect(db)
    assert con.execute("SELECT k FROM questions").fetchone()[0] == 50
    assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 50
    con.close()


def test_e14_click_without_dwell(srv) -> None:
    base, db = srv
    qid = _ask(base)[1]["question_id"]
    code, body = _request(
        "POST", base + "/api/click", {"question_id": qid, "rank": 2, "article_id": "a"}
    )
    assert code == 200, body
    con = sqlite3.connect(db)
    assert con.execute("SELECT dwell_seconds, dwell_seconds_raw FROM clicks").fetchone() == (
        None,
        None,
    )
    con.close()

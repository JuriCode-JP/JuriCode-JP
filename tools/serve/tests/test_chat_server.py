"""Unit tests for the /chat orchestration (PoC P2, chat_server.py).

Deterministic + numpy-free + network-free: retrieval と LLM をフェイク注入し、guards の
強制 (違反 -> 再生成 1 回 -> 情報不足フォールバック) と target_layers 決定論ルールを固定する。
CI はここだけで通る (実 Gemini は呼ばない)。--help / live HTTP で配線も担保 (T8)。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat_server as C  # noqa: E402
import guards as G  # noqa: E402

# =====================================================
# フェイク (retrieval / provider)
# =====================================================


class FakeRetrieval:
    """固定の hits/chunks を返す retrieval client (P1 を起動しない)."""

    def __init__(self, hits, chunks):
        self._hits = hits
        self._chunks = {c["chunk_id"]: c for c in chunks}
        self.last_target_layers = "UNSET"

    def retrieve(self, question, top_k, target_layers):
        self.last_target_layers = target_layers
        return self._hits

    def chunks(self, chunk_ids):
        return [self._chunks[c] for c in chunk_ids if c in self._chunks]


def _fake_with_one_chunk(body="第一条 この法律は正当防衛について定める。"):
    hits = [{"chunk_id": "c1", "layer": "statute", "score": 0.9, "rank": 1}]
    chunks = [
        {
            "chunk_id": "c1",
            "layer": "statute",
            "law_name_ja": "刑法",
            "article_number": "36",
            "text": body,
        }
    ]
    return FakeRetrieval(hits, chunks), body


class ScriptedProvider:
    """attempt ごとに指定の出力を返す provider (再生成挙動を決定論でテストするため)."""

    name = "scripted"

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0

    def generate(self, system_prompt, context, question):
        out = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return out


# =====================================================
# T1: schema
# =====================================================


def test_chat_request_rejects_unknown_field():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        C.ChatRequest(question="x", bogus=1)


def test_chat_request_defaults():
    req = C.ChatRequest(question="x")
    assert req.top_k == C.DEFAULT_TOP_K
    assert req.target_layers is None


def test_llm_output_rejects_bad_verdict():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        C.ChatLLMOutput(verdict="たぶん", answer="a", disclaimer_tense="d")


def test_llm_output_rejects_unknown_field():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        C.ChatLLMOutput(verdict="該当", answer="a", disclaimer_tense="d", bogus=1)


# =====================================================
# T7: target_layers 決定論ルール
# =====================================================


def test_decide_target_layers_rules():
    assert C.decide_target_layers("この法人税基本通達は何番か") == ["tsutatsu"]
    assert C.decide_target_layers("タックスアンサーで役員の範囲は?") == ["taxanswer"]
    assert C.decide_target_layers("No.5200 の内容は?") == ["taxanswer"]
    assert C.decide_target_layers("刑法第36条の正当防衛とは?") == ["statute", "enforcement"]
    # マッチ無し -> None (全層)
    assert C.decide_target_layers("役員給与の取り扱いは?") is None
    # 複数マッチ -> 和集合 (順序は表の評価順)
    got = C.decide_target_layers("通達と第9条の関係は?")
    assert set(got) == {"tsutatsu", "statute", "enforcement"}


def test_request_layers_override_bypasses_rule():
    fake, _ = _fake_with_one_chunk()
    prov = C.MockProvider()
    C.run_chat("この通達は?", 10, fake, prov, request_layers=["taxanswer"])
    assert fake.last_target_layers == ["taxanswer"]  # ルール(tsutatsu)ではなく明示指定


# =====================================================
# happy path (mock provider は grounded 回答を返す)
# =====================================================


def test_run_chat_mock_happy_path_passes_all_guards():
    fake, body = _fake_with_one_chunk()
    resp = C.run_chat("正当防衛とは?", 10, fake, C.MockProvider())
    assert resp.verdict in G.VALID_VERDICTS
    assert resp.guard_report.fell_back is False
    assert resp.guard_report.regenerated is False
    assert resp.tax_practitioner_notice == G.TAX_LAW_BRIDGE
    # citation は渡した本文の逐語部分文字列
    assert resp.citations and resp.citations[0].quote in body
    assert resp.guard_report.attempts[0] == []  # 初回で違反なし


# =====================================================
# T2: G1 偽出典 -> 拒否 -> 再生成 -> 情報不足
# =====================================================


def _bad_g1_output():
    return {
        "verdict": "該当",
        "answer": "関連があります。",
        "citations": [{"chunk_id": "ghost", "quote": "x"}],  # 渡していない chunk_id
        "disclaimer_tense": "参照時点の情報です",
        "insufficient_reason": None,
    }


def test_g1_fabricated_citation_falls_back_to_insufficient():
    fake, _ = _fake_with_one_chunk()
    prov = ScriptedProvider([_bad_g1_output(), _bad_g1_output()])  # 両 attempt とも違反
    resp = C.run_chat("q", 10, fake, prov)
    assert resp.verdict == G.VERDICT_INSUFFICIENT
    assert resp.guard_report.regenerated is True
    assert resp.guard_report.fell_back is True
    assert prov.calls == 2  # 再生成は 1 回だけ
    # 違反ログに G1 が両 attempt 記録される (握りつぶさない)
    assert any(x["code"] == "G1" for x in resp.guard_report.attempts[0])
    assert any(x["code"] == "G1" for x in resp.guard_report.attempts[1])
    # フォールバックは偽出典を落とす
    assert all(c.chunk_id != "ghost" for c in resp.citations)


# =====================================================
# T3: G2 非逐語引用 -> 拒否
# =====================================================


def test_g2_non_verbatim_quote_falls_back():
    fake, _ = _fake_with_one_chunk()
    bad = {
        "verdict": "該当",
        "answer": "関連があります。",
        "citations": [{"chunk_id": "c1", "quote": "本文に無い要約テキスト"}],
        "disclaimer_tense": "参照時点の情報です",
        "insufficient_reason": None,
    }
    prov = ScriptedProvider([bad, bad])
    resp = C.run_chat("q", 10, fake, prov)
    assert resp.verdict == G.VERDICT_INSUFFICIENT
    assert any(x["code"] == "G2" for x in resp.guard_report.attempts[0])


# =====================================================
# 再生成で回復するケース (1回目違反 -> 2回目 clean)
# =====================================================


def test_regeneration_recovers_without_fallback():
    fake, body = _fake_with_one_chunk()
    good = {
        "verdict": "該当",
        "answer": "関連する規定があります。",
        "citations": [{"chunk_id": "c1", "quote": body[:10]}],
        "disclaimer_tense": "参照時点の情報です",
        "insufficient_reason": None,
    }
    prov = ScriptedProvider([_bad_g1_output(), good])
    resp = C.run_chat("q", 10, fake, prov)
    assert resp.verdict == "該当"
    assert resp.guard_report.regenerated is True
    assert resp.guard_report.fell_back is False
    assert resp.guard_report.attempts[1] == []  # 2回目は違反なし


# =====================================================
# G4/G5 の強制 (断定的な金額生成 + 注記欠落 -> フォールバック)
# =====================================================


def test_g4_g5_violations_fall_back():
    fake, body = _fake_with_one_chunk()
    bad = {
        "verdict": "該当",
        "answer": "必ず50万円が否認されます。",  # G3(必ず,否認され) + G4(50万円)
        "citations": [{"chunk_id": "c1", "quote": body[:10]}],
        "disclaimer_tense": "",  # G5
        "insufficient_reason": None,
    }
    prov = ScriptedProvider([bad, bad])
    resp = C.run_chat("q", 10, fake, prov)
    codes = {x["code"] for x in resp.guard_report.attempts[0]}
    assert {"G3", "G4", "G5"} <= codes
    assert resp.verdict == G.VERDICT_INSUFFICIENT


# =====================================================
# T8: --help / live HTTP (mock provider・API キー不要)
# =====================================================


def test_help_runs_without_heavy_deps():
    server = Path(__file__).resolve().parents[1] / "chat_server.py"
    proc = subprocess.run(
        [sys.executable, str(server), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "--mock" in proc.stdout
    assert "--retrieval-url" in proc.stdout


def test_http_chat_roundtrip_with_mock():
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    fake, body = _fake_with_one_chunk()
    C._RETRIEVAL = fake
    C._PROVIDER = C.MockProvider()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), C.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        # /healthz
        conn.request("GET", "/healthz")
        r = conn.getresponse()
        health = json.loads(r.read())
        assert health["status"] == "ok"
        assert health["guards"] == ["G1", "G2", "G3", "G4", "G5", "G6"]

        # unknown field -> 400
        conn.request("POST", "/chat", json.dumps({"question": "q", "nope": 1}))
        r = conn.getresponse()
        assert r.status == 400
        r.read()

        # /chat ok -> grounded + notice + 3-value verdict
        conn.request("POST", "/chat", json.dumps({"question": "正当防衛とは?"}))
        r = conn.getresponse()
        assert r.status == 200
        payload = json.loads(r.read())
        assert payload["verdict"] in list(G.VALID_VERDICTS)
        assert payload["tax_practitioner_notice"] == G.TAX_LAW_BRIDGE
        assert payload["citations"][0]["quote"] in body
        assert payload["meta"]["provider"] == "mock"
        conn.close()
    finally:
        httpd.shutdown()
        C._RETRIEVAL = None
        C._PROVIDER = None

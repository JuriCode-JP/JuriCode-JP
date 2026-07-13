#!/usr/bin/env python3
"""JuriCode-JP /chat orchestration service (PoC P2).

P1 retrieval サービス (retrieval_server.py) の上に /chat を載せ、Gemini 2.5 Flash の
構造化出力を guards.py の機械検証層で強制検査して、出典つき・3値・断定なしの回答だけを
通す。生成 (LLM) は本サービス、検索は P1 を HTTP で叩く (retrieve.py を import しない)。

流れ (PoC P2 §3.1):
    question -> /chat
      1. target_layers 決定 (決定論ルール。LLM に決めさせない)
      2. POST /retrieve -> hits (chunk_id + layer + score + 出典メタ)
      3. POST /chunks   -> 本文 (上位 K 件のみ・Lazy)
      4. LLM (Gemini 2.5 Flash・response_schema で構造化出力)
      5. guards.py で機械検証 -> 違反なら再生成 1 回 -> なお違反なら verdict=情報不足

規律:
    - 検索は HTTP 経由 (P1 の検索挙動を変えない)。
    - 数値 (税額・金額) は生成しない (P4 の zeimu_core のみ)。guards G4 が機械検出。
    - API キーは環境変数。コード・commit・ログに出さない。CI はモック provider で走る。
    - 税理士法の橋渡し文は server がテンプレ挿入 (LLM 任意生成にしない)。

使い方:
    # モック (API キー不要・決定論):
    python tools/serve/chat_server.py --mock --port 8900
    # 実 LLM (P1 を別プロセスで起動しておく):
    python tools/serve/chat_server.py --retrieval-url http://127.0.0.1:8899 \\
        --model gemini-2.5-flash --port 8900
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
_SHARED_SRC = REPO / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

import guards as G  # noqa: E402  (numpy-free at import time)

MAX_BODY_BYTES = 256 * 1024  # query text only (DOS guard)
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_CONTEXT_K = 5  # /chunks に本文を取りに行く上位ヒット数 (LLM に渡す出典数)
DEFAULT_TOP_K = 10

#: フォールバック時の安全な answer (禁止表現・金額を含まない・情報不足である旨のみ)。
INSUFFICIENT_ANSWER = (
    "ご質問について、渡した出典の範囲では確度をもって回答できる根拠を十分に確認できませんでした。"
    "質問を具体化いただくか、対象の法令名・条番号・通達番号を指定してください。"
)
#: フォールバック時の時制注記 (G5 を満たす既定文)。
DEFAULT_DISCLAIMER = (
    "本回答は参照時点の法令・通達等に基づく情報です。改正により内容が変わる可能性があります。"
)


# =====================================================
# target_layers 決定論ルール (§3.4・LLM に決めさせない)
# =====================================================

#: (正規表現, 付与する layer 群)。上から評価し、マッチした layer の和集合を filter にする。
#: 何もマッチしなければ None (= 全層)。自動 boost は入れない (filter のみ)。
TARGET_LAYER_RULES: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"通達"), ("tsutatsu",)),
    (re.compile(r"タックスアンサー"), ("taxanswer",)),
    (re.compile(r"[Nn][Oo]\.?\s*[0-9０-９]{3,4}"), ("taxanswer",)),
    (re.compile(r"第\s*[0-9０-９〇一二三四五六七八九十百千]+\s*条"), ("statute", "enforcement")),
]


def decide_target_layers(question: str) -> list[str] | None:
    """質問文から target_layers を決定 (決定論・表駆動)。マッチ無しなら None (全層).

    Why: どの層を検索するかを LLM に決めさせると非決定・幻覚の温床になる。正規表現の
    表で固定し、テストで期待値をロックする (§3.4)。複数マッチは和集合 (filter を広げる
    方向なので gold を落とさない)。
    """
    matched: list[str] = []
    for pat, layers in TARGET_LAYER_RULES:
        if pat.search(question):
            for lay in layers:
                if lay not in matched:
                    matched.append(lay)
    return matched or None


# =====================================================
# Pydantic models
# =====================================================


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=50)
    # 呼び出し側が明示指定したいときのみ。None なら決定論ルールに委ねる。
    target_layers: list[str] | None = None


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    layer: str | None = None
    law_name_ja: str | None = None
    article_number: str | None = None
    quote: str


class ChatLLMOutput(BaseModel):
    """LLM が返す構造化出力 (response_schema)。tax_practitioner_notice は含めない
    (橋渡し文は server がテンプレ挿入するため LLM に生成させない)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["該当", "非該当", "情報不足"]
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    disclaimer_tense: str
    insufficient_reason: str | None = None


class GuardReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempts: list[list[dict]]  # attempt ごとの違反リスト ([{code, detail}, ...])
    fell_back: bool  # 情報不足へフォールバックしたか
    regenerated: bool  # 再生成を行ったか


class ChatMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_layers: list[str] | None
    n_hits: int
    n_context: int
    elapsed_ms: float
    provider: str


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["該当", "非該当", "情報不足"]
    answer: str
    citations: list[Citation]
    disclaimer_tense: str
    insufficient_reason: str | None
    tax_practitioner_notice: str  # server 挿入の定型文 (G6)
    guard_report: GuardReport
    meta: ChatMeta


# =====================================================
# Providers (LLM 抽象)
# =====================================================


class Provider(Protocol):
    name: str

    def generate(self, system_prompt: str, context: list[dict], question: str) -> dict:
        """context (渡した本文) と question から ChatLLMOutput 相当の dict を返す."""
        ...


SYSTEM_PROMPT = (
    "あなたは日本の税務・法令の調査補助です。渡された出典本文の範囲だけで回答します。\n"
    "厳守事項:\n"
    "1. 出典は渡された chunk のみ引用する。存在しない出典を作らない。\n"
    "2. citations[].quote は渡された本文からの逐語 (完全一致) の抜粋にする。要約や言い換えを quote に入れない。\n"
    "3. 断定・保証をしない (必ず/確実に/問題ありません 等を使わない)。可能性・根拠の提示に留める。\n"
    "4. 税額・金額 (円/万円/億円) を計算・生成しない。数値判断は行わない。\n"
    "5. verdict は 該当 / 非該当 / 情報不足 の 3 値のみ。根拠が不十分なら 情報不足。\n"
    "6. disclaimer_tense に、参照時点の法令に基づく旨の時制注記を必ず入れる。\n"
    "出力は指定の JSON スキーマに厳密に従う。"
)


class MockProvider:
    """決定論の fake provider (API キー・ネットワーク不要・CI 用).

    Why: CI はモックで走る (§3.5)。渡された context の先頭 chunk を逐語引用して
    ガードを通る grounded 回答を返す。context が空なら 情報不足 を返す。
    """

    name = "mock"

    def generate(self, system_prompt: str, context: list[dict], question: str) -> dict:
        if not context:
            return {
                "verdict": "情報不足",
                "answer": INSUFFICIENT_ANSWER,
                "citations": [],
                "disclaimer_tense": DEFAULT_DISCLAIMER,
                "insufficient_reason": "no context chunks were retrieved",
            }
        top = context[0]
        body = top.get("text") or ""
        quote = body[:40] if body else ""
        return {
            "verdict": "該当",
            "answer": (
                "渡された出典に関連する記述が見られます。詳細は引用の本文をご確認ください"
                "(以下は根拠箇所の抜粋です)。"
            ),
            "citations": [
                {
                    "chunk_id": top.get("chunk_id"),
                    "layer": top.get("layer"),
                    "law_name_ja": top.get("law_name_ja"),
                    "article_number": top.get("article_number"),
                    "quote": quote,
                }
            ],
            "disclaimer_tense": DEFAULT_DISCLAIMER,
            "insufficient_reason": None,
        }


class GeminiProvider:
    """Gemini 2.5 Flash による構造化出力 provider (本番用・lazy import).

    Why lazy import: google-genai は宣言依存でない (CI 非依存)。API キーは環境変数から
    取得し、コード・ログに出さない。response_schema で JSON 構造化出力を強制する。
    """

    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None):
        import os

        from google import genai  # lazy import

        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set for /chat generation")
        self._client = genai.Client(api_key=key)
        self._model = model
        # 直近呼び出しの usage_metadata (prompt/output token 数)。コスト計測用に公開する
        # (計時・積算は測定 harness 側で行い、本 provider は最新値を保持するだけ)。
        self.last_usage = None

    def generate(self, system_prompt: str, context: list[dict], question: str) -> dict:
        from google.genai import types  # lazy import

        passages = "\n\n".join(
            f"[chunk_id: {c.get('chunk_id')}] (layer={c.get('layer')}, "
            f"{c.get('law_name_ja')} {c.get('article_number') or ''})\n{c.get('text') or ''}"
            for c in context
        )
        prompt = f"# 質問\n{question}\n\n# 渡された出典 (この範囲でのみ回答)\n{passages}"
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=_gemini_response_schema(),
                temperature=0.0,
            ),
        )
        self.last_usage = getattr(resp, "usage_metadata", None)
        return json.loads(resp.text or "{}")


def _gemini_response_schema():
    """Gemini 構造化出力用の明示スキーマ (types.Schema)。

    Why: Pydantic モデル (extra='forbid') をそのまま response_schema に渡すと
    additionalProperties が付与され Gemini の OpenAPI サブセットが 400 で弾く。
    ChatLLMOutput / Citation と同じ形を、Gemini が受ける型で手組みする (フィールドは
    両者一致を保つこと)。返り JSON は json.loads 後に Citation(**c) 等で最終検証される。
    """
    from google.genai import types as T

    citation = T.Schema(
        type=T.Type.OBJECT,
        properties={
            "chunk_id": T.Schema(type=T.Type.STRING),
            "layer": T.Schema(type=T.Type.STRING, nullable=True),
            "law_name_ja": T.Schema(type=T.Type.STRING, nullable=True),
            "article_number": T.Schema(type=T.Type.STRING, nullable=True),
            "quote": T.Schema(type=T.Type.STRING),
        },
        required=["chunk_id", "quote"],
    )
    return T.Schema(
        type=T.Type.OBJECT,
        properties={
            "verdict": T.Schema(type=T.Type.STRING, enum=["該当", "非該当", "情報不足"]),
            "answer": T.Schema(type=T.Type.STRING),
            "citations": T.Schema(type=T.Type.ARRAY, items=citation),
            "disclaimer_tense": T.Schema(type=T.Type.STRING),
            "insufficient_reason": T.Schema(type=T.Type.STRING, nullable=True),
        },
        required=["verdict", "answer", "citations", "disclaimer_tense"],
    )


# =====================================================
# Retrieval client (P1 を HTTP で叩く。retrieve.py を import しない)
# =====================================================


class RetrievalClient(Protocol):
    def retrieve(
        self, question: str, top_k: int, target_layers: list[str] | None
    ) -> list[dict]: ...

    def chunks(self, chunk_ids: list[str]) -> list[dict]: ...


class HttpRetrievalClient:
    """P1 retrieval_server を localhost HTTP で叩く client (1 責務)."""

    def __init__(self, base_url: str, timeout: float = 120.0):
        from urllib.parse import urlparse

        u = urlparse(base_url)
        self._host = u.hostname or "127.0.0.1"
        self._port = u.port or 8899
        self._timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        import http.client

        conn = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            conn.request(
                "POST",
                path,
                json.dumps(payload),
                {"Content-Type": "application/json"},
            )
            r = conn.getresponse()
            raw = r.read()
            if r.status != 200:
                raise RuntimeError(f"retrieval {path} -> HTTP {r.status}: {raw[:200]!r}")
            return json.loads(raw)
        finally:
            conn.close()

    def retrieve(self, question: str, top_k: int, target_layers: list[str] | None) -> list[dict]:
        body = self._post(
            "/retrieve",
            {"query": question, "top_k": top_k, "target_layers": target_layers},
        )
        return body.get("hits", [])

    def chunks(self, chunk_ids: list[str]) -> list[dict]:
        if not chunk_ids:
            return []
        body = self._post("/chunks", {"chunk_ids": chunk_ids})
        return body.get("chunks", [])


# =====================================================
# Orchestration (guards の強制を含む)
# =====================================================


def _violations_as_dicts(vs: list[G.Violation]) -> list[dict]:
    return [{"code": v.code, "detail": v.detail} for v in vs]


def _build_fallback(
    prev: dict, violations: list[G.Violation], allowed: set[str], chunk_texts: dict[str, str]
) -> dict:
    """ガード違反が残ったときの情報不足フォールバック (安全側・自己検査つき)。

    Why: 黙って通さない (§3.3)。verdict=情報不足、answer は安全定型、citations は G1+G2 を
    通るものだけ残す。組立て後に自己検査し、フォールバック自体が違反なら bug として raise。
    """
    reason_codes = sorted({v.code for v in violations})
    out = {
        "verdict": G.VERDICT_INSUFFICIENT,
        "answer": INSUFFICIENT_ANSWER,
        "citations": G.valid_citations_only(prev.get("citations") or [], allowed, chunk_texts),
        "disclaimer_tense": prev.get("disclaimer_tense") or DEFAULT_DISCLAIMER,
        "insufficient_reason": f"guard violations remained after regeneration: {reason_codes}",
    }
    self_check = G.run_all_guards(
        out["verdict"],
        out["answer"],
        out["citations"],
        out["disclaimer_tense"],
        G.TAX_LAW_BRIDGE,
        allowed,
        chunk_texts,
    )
    if self_check:
        raise AssertionError(f"fallback response itself failed guards: {self_check}")
    return out


def run_chat(
    question: str,
    top_k: int,
    retrieval: RetrievalClient,
    provider: Provider,
    request_layers: list[str] | None = None,
    context_k: int = DEFAULT_CONTEXT_K,
    debug_sink: dict | None = None,
) -> ChatResponse:
    """/chat の中核。検索 -> 本文取得 -> 生成 -> ガード -> (再生成1回) -> フォールバック.

    Why 分離: HTTP ハンドラから切り離した純オーケストレーションにすることで、モックの
    retrieval/provider を注入して決定論テスト (T2-T8) が書ける。

    debug_sink: None 以外を渡すと内部データ (hits / chunk_texts / attempt ごとの生 LLM 出力) を
    書き込む (挙動不変・測定 harness の G2 内訳/grounded 判定用のみ)。None なら一切触らない。
    """
    t0 = time.perf_counter()
    layers = request_layers if request_layers is not None else decide_target_layers(question)
    hits = retrieval.retrieve(question, top_k, layers)
    top_ids = [h["chunk_id"] for h in hits[:context_k]]
    ctx_chunks = retrieval.chunks(top_ids)
    chunk_texts = {c["chunk_id"]: (c.get("text") or "") for c in ctx_chunks}
    allowed = set(chunk_texts)
    context = [
        {
            "chunk_id": c["chunk_id"],
            "layer": c.get("layer"),
            "law_name_ja": c.get("law_name_ja"),
            "article_number": c.get("article_number"),
            "text": c.get("text") or "",
        }
        for c in ctx_chunks
    ]

    def _guard(o: dict) -> list[G.Violation]:
        return G.run_all_guards(
            o.get("verdict"),
            o.get("answer") or "",
            o.get("citations") or [],
            o.get("disclaimer_tense"),
            G.TAX_LAW_BRIDGE,  # server が挿入する定型文で検査
            allowed,
            chunk_texts,
        )

    attempts: list[list[dict]] = []
    raw_outputs: list[dict] = []
    out = provider.generate(SYSTEM_PROMPT, context, question)
    raw_outputs.append(out)
    v1 = _guard(out)
    attempts.append(_violations_as_dicts(v1))
    regenerated = False
    fell_back = False

    if v1:
        regenerated = True
        # 再生成: 違反を明示して 1 回だけ作り直す (prompt の微修正で隠さない)。
        regen_system = SYSTEM_PROMPT + (
            "\n\n# 直前の出力は次の機械検証に違反した。違反を解消して作り直すこと "
            "(該当する根拠が無ければ 情報不足 とする):\n"
            + "\n".join(f"- {v.code}: {v.detail}" for v in v1)
        )
        out2 = provider.generate(regen_system, context, question)
        raw_outputs.append(out2)
        v2 = _guard(out2)
        attempts.append(_violations_as_dicts(v2))
        if v2:
            fell_back = True
            out = _build_fallback(out2, v2, allowed, chunk_texts)
        else:
            out = out2

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if debug_sink is not None:
        debug_sink["hits"] = hits
        debug_sink["chunk_texts"] = chunk_texts
        debug_sink["raw_outputs"] = raw_outputs
    return ChatResponse(
        verdict=out["verdict"],
        answer=out["answer"],
        citations=[Citation(**c) for c in (out.get("citations") or [])],
        disclaimer_tense=out["disclaimer_tense"],
        insufficient_reason=out.get("insufficient_reason"),
        tax_practitioner_notice=G.TAX_LAW_BRIDGE,  # 常に server 挿入 (G6)
        guard_report=GuardReport(attempts=attempts, fell_back=fell_back, regenerated=regenerated),
        meta=ChatMeta(
            target_layers=layers,
            n_hits=len(hits),
            n_context=len(context),
            elapsed_ms=round(elapsed_ms, 2),
            provider=getattr(provider, "name", "unknown"),
        ),
    )


# =====================================================
# HTTP handler
# =====================================================

_RETRIEVAL: RetrievalClient | None = None
_PROVIDER: Provider | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "JuriCodeChat/0.1"

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
            return None, 413
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, 400
        return (obj, None) if isinstance(obj, dict) else (None, 400)

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "provider": getattr(_PROVIDER, "name", "unknown"),
                    "guards": ["G1", "G2", "G3", "G4", "G5", "G6"],
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
        if self.path == "/chat":
            self._handle_chat(body)
            return
        self._send_json(404, {"error": f"not found: {self.path}"})

    def _handle_chat(self, body: dict) -> None:
        assert _RETRIEVAL is not None and _PROVIDER is not None
        try:
            req = ChatRequest(**body)
        except ValidationError as e:
            self._send_json(400, {"error": "bad_request", "detail": e.errors()})
            return
        try:
            resp = run_chat(
                req.question,
                req.top_k,
                _RETRIEVAL,
                _PROVIDER,
                request_layers=req.target_layers,
            )
        except Exception as e:  # surface upstream failure; keep handler thread alive
            self._send_json(500, {"error": "chat_failed", "detail": str(e)})
            return
        self._send_json(200, resp.model_dump())


# =====================================================
# CLI
# =====================================================


def _check_host(host: str, allow_external: bool) -> bool:
    is_external = host not in _LOOPBACK
    if is_external and not allow_external:
        raise ValueError(
            f"refusing to bind non-loopback host {host!r} without --allow-external "
            "(chat service receives query text; keep local-only)"
        )
    return is_external


def build_provider(args) -> Provider:
    if args.mock:
        return MockProvider()
    return GeminiProvider(model=args.model)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--retrieval-url",
        type=str,
        default="http://127.0.0.1:8899",
        help="P1 retrieval_server の base URL",
    )
    ap.add_argument("--model", type=str, default="gemini-2.5-flash", help="生成 LLM モデル名")
    ap.add_argument(
        "--mock",
        action="store_true",
        help="モック provider を使う (API キー不要・決定論・CI 用)",
    )
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument(
        "--allow-external",
        action="store_true",
        help="loopback 以外への bind を許可 (query text を受けるため既定で禁止)",
    )
    ap.add_argument("--port", type=int, default=8900)
    args = ap.parse_args()

    try:
        external = _check_host(args.host, args.allow_external)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    if external:
        print(
            "[security] WARNING: --allow-external set; chat service is exposed to non-loopback "
            "interfaces. Do NOT run on untrusted networks (query text is received).",
            file=sys.stderr,
        )

    global _RETRIEVAL, _PROVIDER
    _RETRIEVAL = HttpRetrievalClient(args.retrieval_url)
    try:
        _PROVIDER = build_provider(args)
    except RuntimeError as e:
        sys.exit(f"ERROR: {e}")
    print(
        f"[startup] provider={_PROVIDER.name} retrieval={args.retrieval_url} "
        f"guards=G1-G6 (machine-enforced)",
        file=sys.stderr,
    )
    print(
        "[security] LOCAL-ONLY by default (127.0.0.1). This service receives raw query text.",
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

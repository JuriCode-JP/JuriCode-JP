"""Unit tests for the resident retrieval service (PoC P1).

Layered by dependency so the file COLLECTS in CI (numpy is not a CI dependency):
    - pure-Python: Pydantic schema (extra=forbid -> 400), dedup-key / fold / layer-filter logic.
      These run everywhere (T1 schema, T2/T3 key+filter logic).
    - numpy-backed: build a tiny synthetic index + row-aligned corpus, construct the service,
      exercise retrieve()/chunks()/integrity (T2 filter, T3 dedup+fold, T4 lazy body, T5 fail-loud).
      Guarded by pytest.importorskip("numpy"); skip when numpy is absent (mirrors test_retrieve.py).
    - subprocess: `--help` smoke runs without numpy (argparse never builds the service) -> CI-safe.

The synthetic encode() is monkeypatched to a fixed query vector so ranking is deterministic and
no Gemini/network call is made. A-3 numeric reproduction lives in tools/serve/reproduce_a3.py (local).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import order is pinned (S first): importing retrieval_server inserts packages/juricode-retrieval/src
# on sys.path, so juricode_retrieval then resolves without a PYTHONPATH; do not let isort reorder.
import retrieval_server as S  # noqa: E402, I001  (numpy-free at import time)
import juricode_retrieval as JR  # noqa: E402  (resolves via the path S inserted)

# ---- pure-Python: Pydantic schema (T1) ----


def test_retrieve_request_rejects_unknown_field():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        S.RetrieveRequest(query="x", bogus=1)


def test_retrieve_request_defaults_lock_a3_condition():
    req = S.RetrieveRequest(query="x")
    assert req.top_k == 10
    assert req.mode == "dense"
    assert req.dedup is True
    assert req.target_layers is None
    assert req.taxanswer_fold is None  # None -> server default


def test_retrieve_request_rejects_out_of_range_top_k():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        S.RetrieveRequest(query="x", top_k=0)
    with pytest.raises(ValidationError):
        S.RetrieveRequest(query="x", top_k=51)


def test_chunks_request_requires_nonempty_list():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        S.ChunksRequest(chunk_ids=[])


# ---- pure-Python: dedup-key / fold / layer-filter logic (T2 / T3) ----


def test_fold_taxanswer_only_folds_taxanswer_subchunks():
    assert S.fold_taxanswer_chunk_id("shotoku-taxanswer-2011-sub2", "taxanswer") == (
        "shotoku-taxanswer-2011"
    )
    assert S.fold_taxanswer_chunk_id("shotoku-taxanswer-2011", "taxanswer") == (
        "shotoku-taxanswer-2011"
    )
    # non-taxanswer honbun chunk is never folded even if it ends in a digit pattern
    assert S.fold_taxanswer_chunk_id("law-a-art-1-p2", "statute") == "law-a-art-1-p2"


def test_build_dedup_keys_fold_off_is_identity():
    base = ["law-a-art-1", "law-a-art-1", "ta-1000-sub1", "ta-1000-sub2"]
    cids = ["law-a-art-1-p1", "law-a-art-1-p2", "ta-1000-sub1", "ta-1000-sub2"]
    layers = ["statute", "statute", "taxanswer", "taxanswer"]
    assert S.build_dedup_keys(base, cids, layers, fold=False) == base


def test_build_dedup_keys_fold_collapses_taxanswer_subchunks():
    base = ["law-a-art-1", "ta-1000-sub1", "ta-1000-sub2"]
    cids = ["law-a-art-1-p1", "ta-1000-sub1", "ta-1000-sub2"]
    layers = ["statute", "taxanswer", "taxanswer"]
    keys = S.build_dedup_keys(base, cids, layers, fold=True)
    assert keys == ["law-a-art-1", "ta-1000", "ta-1000"]  # sub1/sub2 collapse to one doc key


def test_filter_row_by_layers():
    layers = ["statute", "taxanswer", "tsutatsu", "statute"]
    assert S.filter_row_by_layers([0, 1, 2, 3], layers, None) == [0, 1, 2, 3]
    assert S.filter_row_by_layers([0, 1, 2, 3], layers, ["taxanswer"]) == [1]
    assert S.filter_row_by_layers([0, 1, 2, 3], layers, ["statute", "tsutatsu"]) == [0, 2, 3]


# ---- subprocess: --help smoke runs without numpy (T5) ----


def test_help_runs_without_heavy_deps():
    server = Path(__file__).resolve().parents[1] / "retrieval_server.py"
    proc = subprocess.run(
        [sys.executable, str(server), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "--index" in proc.stdout
    assert "--no-taxanswer-fold" in proc.stdout


# ---- numpy-backed: synthetic index fixture + service behaviour (T2/T3/T4/T5) ----


def _write_tiny_index(tmp_path):
    """Write a 6-record synthetic index (.npy/.meta.jsonl/.vec.pkl) + row-aligned corpus.

    Rows: two chunks of the same statute article (dup), one other statute article,
    two sub-chunks of one taxanswer doc (dup only when folded), one tsutatsu directive.
    """
    np = pytest.importorskip("numpy")
    import pickle

    meta = [
        {
            "article_id": "law-a-art-1",
            "chunk_id": "law-a-art-1-p1",
            "law_name_ja": "A法",
            "article_number": "1",
        },
        {
            "article_id": "law-a-art-1",
            "chunk_id": "law-a-art-1-p2",
            "law_name_ja": "A法",
            "article_number": "1",
        },
        {
            "article_id": "law-b-art-2",
            "chunk_id": "law-b-art-2-p1",
            "law_name_ja": "B法",
            "article_number": "2",
        },
        {
            "article_id": None,
            "chunk_id": "ta-1000-sub1",
            "law_name_ja": None,
            "article_number": None,
        },
        {
            "article_id": None,
            "chunk_id": "ta-1000-sub2",
            "law_name_ja": None,
            "article_number": None,
        },
        {"article_id": None, "chunk_id": "tsu-1", "law_name_ja": "A法", "article_number": None},
    ]
    layers = ["statute", "statute", "statute", "taxanswer", "taxanswer", "tsutatsu"]
    groups = ["statute", "statute", "statute", "taxanswer", "taxanswer", "tsutatsu"]
    dids = [None, None, None, None, None, "tsu-1"]
    vecs = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.95, 0.05],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    # pad to EXPECTED_DIM so the integrity check passes
    pad = np.zeros((6, S.EXPECTED_DIM - 4), dtype=np.float32)
    matrix = np.concatenate([vecs, pad], axis=1)

    prefix = tmp_path / "tiny-index"
    np.save(tmp_path / "tiny-index.npy", matrix)
    with (tmp_path / "tiny-index.meta.jsonl").open("w", encoding="utf-8") as fh:
        for r in meta:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (tmp_path / "tiny-index.vec.pkl").open("wb") as fh:
        pickle.dump({"provider": "tfidf", "model": "test"}, fh)

    corpus = tmp_path / "tiny-corpus.jsonl"
    with corpus.open("w", encoding="utf-8") as fh:
        for i, r in enumerate(meta):
            fh.write(
                json.dumps(
                    {
                        "chunk_id": r["chunk_id"],
                        "layer": layers[i],
                        "corpus_group": groups[i],
                        "directive_id": dids[i],
                        "law_name_ja": r["law_name_ja"],
                        "text": f"body-{r['chunk_id']}",
                        "text_raw": f"raw-{r['chunk_id']}",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return prefix, corpus


def _make_service(tmp_path, default_fold, query_vec):
    np = pytest.importorskip("numpy")
    prefix, corpus = _write_tiny_index(tmp_path)
    svc = S.RetrievalService(prefix, corpus, default_fold=default_fold)
    # deterministic offline encode (no Gemini): map any query to the supplied vector
    padded = np.zeros((1, S.EXPECTED_DIM), dtype=np.float32)
    padded[0, : len(query_vec)] = np.array(query_vec, dtype=np.float32)
    svc.encode = lambda q: padded  # type: ignore[method-assign]
    return svc


def test_service_dedup_collapses_same_article(tmp_path):
    # query points at the statute cluster; the two chunks of law-a-art-1 must collapse to one hit.
    svc = _make_service(tmp_path, default_fold=False, query_vec=[1.0, 0.05, 0.0, 0.0])
    vec = svc.encode("q")
    hits, _ = svc.retrieve(vec, top_k=10, target_layers=None, dedup=True, fold=False)
    art_ids = [h["article_id"] for h in hits]
    assert art_ids.count("law-a-art-1") == 1  # dup chunk removed


def test_service_no_dedup_keeps_duplicate_chunks(tmp_path):
    svc = _make_service(tmp_path, default_fold=False, query_vec=[1.0, 0.05, 0.0, 0.0])
    vec = svc.encode("q")
    hits, _ = svc.retrieve(vec, top_k=10, target_layers=None, dedup=False, fold=False)
    art_ids = [h["article_id"] for h in hits]
    assert art_ids.count("law-a-art-1") == 2  # both chunks retained


def test_service_taxanswer_fold_contrast(tmp_path):
    # query points at the taxanswer cluster; fold ON collapses sub1/sub2, OFF keeps both.
    svc = _make_service(tmp_path, default_fold=False, query_vec=[0.0, 0.0, 1.0, 0.0])
    vec = svc.encode("q")
    off, _ = svc.retrieve(vec, top_k=10, target_layers=None, dedup=True, fold=False)
    ta_off = [h for h in off if h["layer"] == "taxanswer"]
    assert len(ta_off) == 2
    on, _ = svc.retrieve(vec, top_k=10, target_layers=None, dedup=True, fold=True)
    ta_on = [h for h in on if h["layer"] == "taxanswer"]
    assert len(ta_on) == 1


def test_service_target_layers_filter(tmp_path):
    svc = _make_service(tmp_path, default_fold=False, query_vec=[1.0, 1.0, 1.0, 1.0])
    vec = svc.encode("q")
    hits, _ = svc.retrieve(vec, top_k=10, target_layers=["taxanswer"], dedup=False, fold=False)
    assert hits  # non-empty
    assert all(h["layer"] == "taxanswer" for h in hits)


def test_service_hits_have_no_body_but_chunks_do(tmp_path):
    svc = _make_service(tmp_path, default_fold=False, query_vec=[1.0, 0.0, 0.0, 0.0])
    vec = svc.encode("q")
    hits, _ = svc.retrieve(vec, top_k=5, target_layers=None, dedup=True, fold=False)
    assert hits
    assert all("text" not in h for h in hits)  # /retrieve is lazy (no body)
    chunk_ids = [h["chunk_id"] for h in hits]
    chunks, missing = svc.chunks(chunk_ids + ["does-not-exist"])
    assert missing == ["does-not-exist"]
    assert all(c["text"].startswith("body-") for c in chunks)


def test_service_defaults_report_fold_flag(tmp_path):
    svc = _make_service(tmp_path, default_fold=True, query_vec=[1.0, 0.0, 0.0, 0.0])
    d = svc.defaults()
    assert d == {
        "mode": "dense",
        "dedup": True,
        "task_type": "RETRIEVAL_QUERY",
        "normalize": False,
        "taxanswer_subchunk_fold": True,
    }


def test_fold_precompute_is_behavior_invariant(tmp_path):
    """T9 (P2 §3.6): 起動時 precompute した dedup キー列が build_dedup_keys の出力と一致し、
    かつ precompute 経路 (NEW) と inline 再構築 (OLD) の retrieve() hits が差分 0 であること."""
    np = pytest.importorskip("numpy")
    svc = _make_service(tmp_path, default_fold=False, query_vec=[0.0, 0.0, 1.0, 0.0])

    # (1) precompute == build_dedup_keys 出力 (キャッシュの正しさ)
    assert svc._keys_fold_off == list(svc._base_keys)
    assert svc._keys_fold_on == S.build_dedup_keys(
        svc._base_keys, svc.chunk_ids, svc.layers, fold=True
    )

    # (2) 複数クエリ・両 fold で NEW(precompute) 経路と OLD(inline) 経路の hits が完全一致。
    #     OLD 経路: build_dedup_keys を毎回呼んで dedup_by_article をかけ直す参照実装。
    def old_retrieve(query_vec, top_k, fold):
        sims, idx_row = svc.dense_pool(query_vec, max(top_k * 3, 60))
        idx_list = [int(i) for i in idx_row]
        keys = S.build_dedup_keys(svc._base_keys, svc.chunk_ids, svc.layers, fold)
        deduped = JR.dedup_by_article(np.array([idx_list], dtype=np.int64), keys, top_k)
        return [svc.chunk_ids[int(i)] for i in deduped[0] if int(i) >= 0]

    queries = [[1.0, 0.05, 0.0, 0.0], [0.0, 0.0, 1.0, 0.02], [0.0, 1.0, 0.0, 0.0]]
    for q in queries:
        padded = np.zeros((1, S.EXPECTED_DIM), dtype=np.float32)
        padded[0, : len(q)] = np.array(q, dtype=np.float32)
        for fold in (False, True):
            new_hits, _ = svc.retrieve(padded, top_k=10, target_layers=None, dedup=True, fold=fold)
            new_ids = [h["chunk_id"] for h in new_hits]
            assert new_ids == old_retrieve(padded, 10, fold), f"fold={fold} q={q} diverged"


def test_service_fail_loud_on_corpus_row_mismatch(tmp_path):
    pytest.importorskip("numpy")
    prefix, corpus = _write_tiny_index(tmp_path)
    # truncate the corpus so row counts disagree -> startup must fail loud
    lines = corpus.read_text(encoding="utf-8").splitlines()[:-1]
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corpus rows"):
        S.RetrievalService(prefix, corpus, default_fold=False)


# ---- numpy-backed: live HTTP round-trip proves the handler wiring (T1/T4) ----


def test_http_roundtrip(tmp_path):
    pytest.importorskip("numpy")
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    svc = _make_service(tmp_path, default_fold=True, query_vec=[1.0, 0.05, 0.0, 0.0])
    S._SERVICE = svc
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
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
        assert health["dim"] == S.EXPECTED_DIM
        assert health["defaults"]["taxanswer_subchunk_fold"] is True

        # /retrieve unknown field -> 400
        conn.request("POST", "/retrieve", json.dumps({"query": "q", "nope": 1}))
        r = conn.getresponse()
        assert r.status == 400
        r.read()

        # /retrieve ok -> hits with no body
        conn.request("POST", "/retrieve", json.dumps({"query": "q", "top_k": 5}))
        r = conn.getresponse()
        assert r.status == 200
        payload = json.loads(r.read())
        assert payload["hits"]
        assert "text" not in payload["hits"][0]
        assert payload["meta"]["index"] == svc.index_prefix.name

        # /chunks returns body
        cid = payload["hits"][0]["chunk_id"]
        conn.request("POST", "/chunks", json.dumps({"chunk_ids": [cid]}))
        r = conn.getresponse()
        assert r.status == 200
        chunks = json.loads(r.read())
        assert chunks["chunks"][0]["text"].startswith("body-")
        conn.close()
    finally:
        httpd.shutdown()
        S._SERVICE = None

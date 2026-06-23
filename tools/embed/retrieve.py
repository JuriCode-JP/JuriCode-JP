#!/usr/bin/env python3
"""JuriCode-JP Top-K Retrieval Tester.

Provider is detected from .vec.pkl. Supports tfidf / openai / gemini.

新規拡張 (2026-05-21):
- --normalize-query: 法令略称展開 + 漢数字->アラビア数字正規化
- --hybrid-bm25: TF-IDF (char 2-3gram) と Dense を RRF (k=60) で結合
- --bm25-corpus: BM25 用の corpus jsonl パス (text フィールド)
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

from juricode_shared.text_norm import (
    arabic_version_of_article_numbers as _arabic_version_of_article_numbers,
)
from juricode_shared.text_norm import (
    kanji_version_of_article_numbers as _kanji_version_of_article_numbers,
)
from juricode_shared.text_norm import (
    normalize_fullwidth_digits as _normalize_fullwidth_digits,
)

# =====================================================
# Query normalization (法令名・条番号の正規化)
# =====================================================

# 略称 -> (略称をそのまま残しつつ) 正式名称も付加することで両方で hit させる
LAW_ABBREV_EXPANSIONS = {
    "地公法": "地方公務員法",
    "国公法": "国家公務員法",
    "個保法": "個人情報保護法",
    "金商法": "金融商品取引法",
    "薬機法": "医薬品医療機器等法",
    "情報公開法": "行政機関の保有する情報の公開に関する法律",
    "公文書管理法": "公文書等の管理に関する法律",
    "行手法": "行政手続法",
    "行審法": "行政不服審査法",
    "刑訴法": "刑事訴訟法",
    "民訴法": "民事訴訟法",
    "労基法": "労働基準法",
    "デジタル基本法": "デジタル社会形成基本法",
    "デジタル社会基本法": "デジタル社会形成基本法",
    "独禁法": "私的独占の禁止及び公正取引の確保に関する法律",
    "犯収法": "犯罪による収益の移転防止に関する法律",
    "ストーカー規制法": "ストーカー行為等の規制等に関する法律",
    "風営法": "風俗営業等の規制及び業務の適正化等に関する法律",
    "警職法": "警察官職務執行法",
    "道交法": "道路交通法",
}


def _expand_law_abbreviations_list(text: str) -> list[str]:
    """略称の正式名称リストを返す (追加用)."""
    additions = []
    for abbrev, expanded in LAW_ABBREV_EXPANSIONS.items():
        if abbrev in text and expanded not in text:
            additions.append(expanded)
    return additions


def normalize_legal_query(query: str) -> str:
    """法令名・条番号の総合正規化(置換ではなく追加で複数バージョンを構築).

    e-Gov 法令本文は漢数字を使用するため、半角->漢数字版も追加することで
    corpus body の embedding マッチを強化する.
    """
    # 全角->半角
    base = _normalize_fullwidth_digits(query)

    additions = []
    # 漢数字版 (corpus body マッチ用)
    kanji_ver = _kanji_version_of_article_numbers(base)
    if kanji_ver != base and kanji_ver not in base:
        additions.append(kanji_ver)
    # アラビア数字版 (現代質問マッチ用)
    arabic_ver = _arabic_version_of_article_numbers(base)
    if arabic_ver != base and arabic_ver not in base:
        additions.append(arabic_ver)
    # 略称展開
    additions.extend(_expand_law_abbreviations_list(base))

    if additions:
        return base + " " + " ".join(additions)
    return base


# =====================================================
# BM25 (TF-IDF char-ngram) Hybrid
# =====================================================


def _tokenize_chargram(text: str, ngrams=(2, 3)) -> list[str]:
    """char n-gram tokenizer (Japanese-friendly, no external dep)."""
    if not text:
        return []
    tokens = []
    for n in ngrams:
        if len(text) >= n:
            tokens.extend(text[i : i + n] for i in range(len(text) - n + 1))
    return tokens


def build_tfidf_index(corpus_jsonl: Path, text_field: str = "text"):
    """corpus jsonl から純 numpy/scipy で TF-IDF インデックスを構築 (sklearn 非依存)."""
    from collections import Counter, defaultdict

    import numpy as np  # lazy import (FU-506)
    from scipy.sparse import csr_matrix

    texts = []
    article_ids = []
    with corpus_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            texts.append(obj.get(text_field, "") or "")
            # R14: directive/taxanswer records have article_id=None; fall back to chunk_id
            aid = obj.get("article_id") or obj.get("chunk_id") or ""
            article_ids.append(aid)

    print(f"  [bm25] tokenizing {len(texts)} docs...", file=sys.stderr)
    docs_tokens = [_tokenize_chargram(t) for t in texts]

    # Build vocab (min_df=2)
    df = defaultdict(int)
    for d in docs_tokens:
        for tok in set(d):
            df[tok] += 1
    vocab = {tok: i for i, tok in enumerate(t for t, c in df.items() if c >= 2)}
    n_vocab = len(vocab)

    # Cap vocab to top 30k by document frequency
    if n_vocab > 30000:
        top_terms = sorted(df.items(), key=lambda x: -x[1])[:30000]
        vocab = {t: i for i, (t, _) in enumerate(top_terms)}
        n_vocab = 30000

    n_docs = len(texts)

    # Build sparse TF matrix using IJV (COO) format
    rows, cols, vals = [], [], []
    for di, doc in enumerate(docs_tokens):
        cnt = Counter(doc)
        for tok, c in cnt.items():
            j = vocab.get(tok)
            if j is not None:
                rows.append(di)
                cols.append(j)
                vals.append(float(c))
    tf = csr_matrix((vals, (rows, cols)), shape=(n_docs, n_vocab), dtype=np.float32)

    # Compute IDF
    df_arr = np.zeros(n_vocab, dtype=np.float32)
    for tok, j in vocab.items():
        df_arr[j] = df[tok]
    idf = np.log((n_docs - df_arr + 0.5) / (df_arr + 0.5) + 1.0).astype(np.float32)

    # TF-IDF matrix: row-wise multiply tf by idf
    from scipy.sparse import diags as sp_diags

    tfidf_matrix = tf @ sp_diags(idf)

    print(f"  [bm25] TF-IDF index built: {tfidf_matrix.shape}, vocab={n_vocab}", file=sys.stderr)
    return {"vocab": vocab, "idf": idf}, tfidf_matrix, article_ids


def _l2_normalize_sparse(sparse_matrix):
    """純 scipy/numpy で L2 正規化."""
    import numpy as np  # lazy import (FU-506)
    from scipy.sparse import diags

    sq = sparse_matrix.multiply(sparse_matrix)
    sq_sum = np.array(sq.sum(axis=1)).flatten()
    norms = np.sqrt(sq_sum)
    norms[norms == 0] = 1.0
    inv_norm = diags(1.0 / norms)
    return inv_norm @ sparse_matrix


def _vectorize_query_with_index(queries, index_info, n_vocab):
    """クエリを TF-IDF インデックスにマッチさせて sparse 行列にする."""
    from collections import Counter

    import numpy as np  # lazy import (FU-506)
    from scipy.sparse import csr_matrix

    vocab = index_info["vocab"]
    idf = index_info["idf"]
    rows, cols, vals = [], [], []
    for qi, q in enumerate(queries):
        toks = _tokenize_chargram(q)
        cnt = Counter(toks)
        for tok, c in cnt.items():
            j = vocab.get(tok)
            if j is not None:
                rows.append(qi)
                cols.append(j)
                vals.append(float(c) * float(idf[j]))
    return csr_matrix((vals, (rows, cols)), shape=(len(queries), n_vocab), dtype=np.float32)


def bm25_topk_per_query(queries, index_info, tfidf_matrix, top_k):
    """各クエリの BM25 top-K インデックス (np.ndarray (N, K))."""
    import numpy as np  # lazy import (FU-506)

    n_vocab = tfidf_matrix.shape[1]
    q_mat = _vectorize_query_with_index(queries, index_info, n_vocab)
    q_norm = _l2_normalize_sparse(q_mat)
    c_norm = _l2_normalize_sparse(tfidf_matrix)
    sims = (q_norm @ c_norm.T).toarray()
    top_idx = np.argsort(-sims, axis=1)[:, :top_k]
    return sims, top_idx


# =====================================================
# Cross-encoder Reranker (bge-reranker-v2-m3)
# =====================================================


def _load_corpus_texts(corpus_jsonl: Path, text_field: str = "text") -> list[str]:
    """corpus jsonl から text のリストを順序保持して読み込む."""
    texts = []
    with corpus_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            texts.append(obj.get(text_field, "") or "")
    return texts


def rerank_with_cross_encoder(
    queries: list[str],
    candidates_per_query,
    corpus_texts: list[str],
    top_k_final: int,
    model_name: str = "BAAI/bge-reranker-v2-m3",
    max_length: int = 512,
    batch_size: int = 32,
):
    """Cross-encoder で各クエリの候補を re-rank.

    Args:
        queries: クエリ文字列リスト (N)
        candidates_per_query: 各クエリの候補インデックス配列 (N, M)
                              M は dense retrieval の top-N (例: 30)
        corpus_texts: corpus 全体の text リスト (順序は records と一致)
        top_k_final: 最終的に返す top-K
        model_name: HuggingFace model ID
        max_length: cross-encoder max sequence length
        batch_size: batch size for prediction

    Returns:
        np.ndarray (N, top_k_final): re-rank された候補インデックス
    """
    import numpy as np  # lazy import (FU-506)

    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        sys.exit(
            "ERROR: sentence-transformers not installed. Run: pip install sentence-transformers"
        )

    print(f"  [reranker] loading {model_name} ...", file=sys.stderr)
    model = CrossEncoder(model_name, max_length=max_length)
    print(
        f"  [reranker] re-ranking {len(queries)} queries x {candidates_per_query.shape[1]} candidates ...",
        file=sys.stderr,
    )

    n_queries = len(queries)
    reranked = np.zeros((n_queries, top_k_final), dtype=np.int64)

    for qi in range(n_queries):
        q = queries[qi]
        cand_idx = candidates_per_query[qi]
        pairs = []
        valid_cand = []
        for idx in cand_idx:
            idx_int = int(idx)
            if idx_int < 0:
                continue
            doc_text = corpus_texts[idx_int] if idx_int < len(corpus_texts) else ""
            pairs.append([q, doc_text])
            valid_cand.append(idx_int)

        if not pairs:
            # fallback to original order if no valid candidates
            reranked[qi] = list(cand_idx[:top_k_final]) + [-1] * max(0, top_k_final - len(cand_idx))
            continue

        scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=False)
        # Sort by score descending
        sorted_pairs = sorted(zip(scores, valid_cand, strict=False), key=lambda x: -x[0])
        sorted_indices = [int(c) for s, c in sorted_pairs][:top_k_final]
        # Pad if fewer than top_k_final
        while len(sorted_indices) < top_k_final:
            sorted_indices.append(-1)
        reranked[qi] = sorted_indices

    print("  [reranker] done.", file=sys.stderr)
    return reranked


def rrf_combine_per_query(dense_top_idx, bm25_top_idx, top_k, k_rrf=60):
    """各クエリで dense top-N と bm25 top-N を RRF で結合し top-K を返す.

    負 index (-1 padding) は寄与させず skip する (B7: 片側 0 件でも NaN・負 index 混入なし)。
    同率スコアは index 昇順で tie-break して決定的にする (B8)。scores のキーは int(idx) で
    構築するため (-score, index) タプル比較は型安全 (str/UUID 混入経路なし)。
    """
    import numpy as np  # lazy import (FU-506)

    n_queries = dense_top_idx.shape[0]
    combined = np.full((n_queries, top_k), -1, dtype=np.int64)
    for qi in range(n_queries):
        scores: dict[int, float] = {}
        for rank, idx in enumerate(dense_top_idx[qi], 1):
            i = int(idx)
            if i < 0:
                continue
            scores[i] = scores.get(i, 0.0) + 1.0 / (k_rrf + rank)
        for rank, idx in enumerate(bm25_top_idx[qi], 1):
            i = int(idx)
            if i < 0:
                continue
            scores[i] = scores.get(i, 0.0) + 1.0 / (k_rrf + rank)
        sorted_indices = sorted(scores.keys(), key=lambda x: (-scores[x], x))[:top_k]
        for j, idx_int in enumerate(sorted_indices):
            combined[qi, j] = idx_int
    return combined


# =====================================================
# Existing helpers
# =====================================================


def _load_artefacts(prefix):
    import numpy as np  # lazy import (FU-506)

    # NOTE: with_suffix() は "v0.2-gemini-17967" のようなドット含み名で
    # ".2-gemini-17967" を suffix と解釈して壊す。文字列連結で回避。
    npy_path = prefix.parent / (prefix.name + ".npy")
    meta_path = prefix.parent / (prefix.name + ".meta.jsonl")
    vec_path = prefix.parent / (prefix.name + ".vec.pkl")
    missing = [str(p) for p in (npy_path, meta_path, vec_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing artefact(s): {missing}")

    matrix = np.load(npy_path)
    records = []
    with meta_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    with vec_path.open("rb") as fh:
        state = pickle.load(fh)
    return matrix, records, state


def _load_queries(eval_set_paths):
    out = []
    for p in eval_set_paths:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    return out


def _encode_queries(questions, state):
    import numpy as np  # lazy import (FU-506)

    provider = state.get("provider")

    if provider == "tfidf":
        v = state["vectorizer"]
        return v.transform(questions).astype(np.float32).toarray()

    if provider == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("ERROR: openai package not installed. Run: pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("ERROR: OPENAI_API_KEY environment variable not set")
        client = OpenAI(api_key=api_key)
        model = state["model"]
        resp = client.embeddings.create(model=model, input=questions)
        return np.asarray([item.embedding for item in resp.data], dtype=np.float32)

    if provider == "gemini":
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            sys.exit("ERROR: google-genai package not installed. Run: pip install google-genai")
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            sys.exit("ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable not set")
        client = genai.Client(api_key=api_key)
        model = state["model"]
        BATCH_SIZE = 100
        MAX_RETRIES = 5
        all_embeddings = []
        import time as _time

        for batch_start in range(0, len(questions), BATCH_SIZE):
            batch = questions[batch_start : batch_start + BATCH_SIZE]
            last_err = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = client.models.embed_content(
                        model=model,
                        contents=batch,
                        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
                    )
                    all_embeddings.extend(emb.values for emb in resp.embeddings)
                    break
                except Exception as e:
                    last_err = e
                    if attempt < MAX_RETRIES:
                        # 429 RESOURCE_EXHAUSTED: wait at least 65s for quota reset
                        is_429 = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                        wait = 65.0 if is_429 else 1.5**attempt
                        print(
                            f"  [gemini retry {attempt}/{MAX_RETRIES}] {type(e).__name__}: waiting {wait:.1f}s",
                            file=sys.stderr,
                        )
                        _time.sleep(wait)
                    else:
                        print(
                            f"  [gemini FAILED after {MAX_RETRIES} retries] {last_err}",
                            file=sys.stderr,
                        )
                        raise
        return np.asarray(all_embeddings, dtype=np.float32)

    sys.exit(f"ERROR: unsupported provider in artefacts: {provider!r}")


def _cosine_topk(query_matrix, corpus_matrix, top_k):
    import numpy as np  # lazy import (FU-506)

    qn = np.linalg.norm(query_matrix, axis=1, keepdims=True)
    qn[qn == 0] = 1.0
    qnorm = query_matrix / qn

    cn = np.linalg.norm(corpus_matrix, axis=1, keepdims=True)
    cn[cn == 0] = 1.0
    cnorm = corpus_matrix / cn

    sims = qnorm @ cnorm.T
    top_idx = np.argsort(-sims, axis=1)[:, :top_k]
    return sims, top_idx


def _rank_of_first_match(ranked_ids, expected):
    for i, aid in enumerate(ranked_ids, start=1):
        if aid in expected:
            return i
    return None


def _apply_hyde(
    questions_raw, state, corpus_matrix, dense_sims, dense_top_idx, candidate_pool, args
):
    """HyDE 仮想文を生成/キャッシュ -> embed -> dense -> Late Fusion し dense 結果を置換して返す.

    Why: dense_retrieve 直後・hybrid/rerank の前に dense_top_idx/dense_sims を差し替えることで
    後段 (hybrid / dedup / rerank) を無改修で合成できる。融合は hyde.rrf_fuse / min_max_fuse のみ
    (生スコア加算禁止・Bug5)。キャッシュは query_hash 照合・欠落は fail-loud (Bug9)。
    """
    import hyde as _hyde  # sibling module (sys.path に tools/embed/ が入っている前提)
    import numpy as np  # lazy import (FU-506)

    cache = _hyde.load_hyde_cache(args.hyde_cache)
    missing = [q for q in questions_raw if _hyde.compute_query_hash(q) not in cache]
    if missing:
        # trial 1: 未生成のみ Gemini 生成 -> 永続化 (既存は再生成しない・Bug8)。
        generate_fn = _hyde.make_gemini_generator(args.hyde_gen_model)
        cache = _hyde.build_hyde_cache(questions_raw, generate_fn=generate_fn, existing=cache)
        _hyde.save_hyde_cache(args.hyde_cache, cache)
        print(f"  [hyde] generated {len(missing)} new doc(s) -> {args.hyde_cache}", file=sys.stderr)
    else:
        print(
            f"  [hyde] all {len(questions_raw)} doc(s) from cache {args.hyde_cache}",
            file=sys.stderr,
        )

    hyde_docs = _hyde.resolve_hypothetical_docs(questions_raw, cache)  # ID 照合・fail-loud
    hyde_matrix = _encode_queries(hyde_docs, state)
    hyde_sims, hyde_top_idx = _cosine_topk(hyde_matrix, corpus_matrix, candidate_pool)

    if args.hyde_only:
        # E3: HyDE 仮想文 dense のみ (原クエリと融合しない)。
        return hyde_top_idx, hyde_sims

    # E3': 原クエリ dense と HyDE dense の Late Fusion。
    if args.hyde_fusion == "rrf":
        fused = _hyde.rrf_fuse([dense_top_idx, hyde_top_idx], candidate_pool, k_rrf=args.rrf_k)
    else:
        score_o = np.take_along_axis(dense_sims, dense_top_idx, axis=1)
        score_h = np.take_along_axis(hyde_sims, hyde_top_idx, axis=1)
        fused = _hyde.min_max_fuse(
            [dense_top_idx, hyde_top_idx], [score_o, score_h], candidate_pool
        )
    return fused, dense_sims


def dedup_by_article(top_idx_wide, article_ids, k):
    """各 query で article_id でユニーク化、上位の rank を維持して unique articles 上位 K 個を返す.

    v0.2 segment-level retrieval を v0.1 article-level Recall と公平比較する用途.
    同じ article の複数 segment が top に来た場合、最初の (=top rank) segment のみ保持.

    Args:
        top_idx_wide: (N_queries, M) -- dense top-M segment indices (M > K 推奨)
        article_ids: list[str] -- corpus record (segment) 順の article_id
        k: target number of unique articles to return

    Returns:
        np.ndarray (N_queries, K) -- dedup 後の上位 K segment indices (代表 segment)
    """
    import numpy as np  # lazy import (FU-506)

    n_queries = top_idx_wide.shape[0]
    out = np.full((n_queries, k), -1, dtype=np.int64)
    for qi in range(n_queries):
        seen = set()
        kept = []
        for idx in top_idx_wide[qi]:
            idx_int = int(idx)
            if idx_int < 0:
                continue
            aid = article_ids[idx_int]
            if aid in seen:
                continue
            seen.add(aid)
            kept.append(idx_int)
            if len(kept) >= k:
                break
        for i, idx_int in enumerate(kept):
            out[qi, i] = idx_int
    return out


class RetrievalPipeline:
    """Retrieval の各段 (dense / hybrid / dedup / rerank / metrics) を集約するクラス (FU-406).

    LAZY 規律 (計画 §3.2): __init__ とモジュールレベルで torch / sentence_transformers を
    import しない (cold start 再発防止)。重い import は rerank メソッド内に局所化し、
    dense_retrieve / hybrid_combine / dedup_by_article / select_rerank_candidates /
    aggregate_metrics は torch 非依存の純関数として sandbox unit test 可能にする。
    """

    def __init__(self, state: dict, records: list[dict]):
        self.state = state
        self.records = records
        self.article_ids = [r.get("article_id") for r in records]
        self.law_name_ja = [r.get("law_name_ja") for r in records]
        self.article_number = [r.get("article_number") for r in records]
        # Non-article entities (tsutatsu / taxanswer) have article_id=None;
        # store fallback ids for aggregate_metrics matching.
        self._directive_ids = [r.get("directive_id") for r in records]
        self._chunk_ids = [r.get("chunk_id") for r in records]

    def dense_retrieve(self, query_matrix, corpus_matrix, top_k):
        """cosine 類似度で各 query の top-K segment を返す (sims, top_idx)。torch 非依存。"""
        return _cosine_topk(query_matrix, corpus_matrix, top_k)

    def hybrid_combine(self, dense_top_idx, bm25_top_idx, top_k, rrf_k=60):
        """dense と bm25 の rank list を RRF で結合し top-K を返す。torch 非依存。"""
        return rrf_combine_per_query(dense_top_idx, bm25_top_idx, top_k, k_rrf=rrf_k)

    def dedup_by_article(self, top_idx_wide, k):
        """同一 article の重複 segment を除去し代表 (最上位 rank) のみ残す。torch 非依存。"""
        return dedup_by_article(top_idx_wide, self.article_ids, k)

    def select_rerank_candidates(self, dense_top_idx, top_idx_wide, hybrid_on, n_candidates, top_k):
        """rerank に渡す candidate を選ぶ (FU-425 の候補選択を 1 箇所に局所化)。torch 非依存。

        柱1-B 修正 (FU-425): hybrid on なら hybrid 後集合 (RRF = top_idx_wide) の上位
        rerank_candidate_k 件を candidate にする (既定挙動、flag なし)。hybrid off は従来どおり
        dense top-N。top_idx_wide の列数は main 側で rerank_candidate_k 以上に補正済。
        スライスは列数に従うため実ヒット < k でも安全 (矩形維持・IndexError なし)。
        """
        k = max(n_candidates, top_k)
        if hybrid_on:
            return top_idx_wide[:, :k]
        return dense_top_idx[:, :k]

    def rerank(
        self, questions, candidates, corpus_texts, top_k, model_name="BAAI/bge-reranker-v2-m3"
    ):
        """cross-encoder で candidate を re-rank。重い import はこのメソッド内のみ (LAZY 規律)。"""
        return rerank_with_cross_encoder(
            questions, candidates, corpus_texts, top_k, model_name=model_name
        )

    def aggregate_metrics(self, top_idx, expected_per_query):
        """top_idx と各 query の expected 集合から R@1/3/5/10/20, MRR を計算 (純関数, torch 非依存)。

        Non-article entities (tsutatsu / taxanswer) は article_id=None のため、
        article_id が None の行は directive_id → chunk_id の順でフォールバックして照合する。
        これにより aggregate_metrics が per-query 表示 (797行) と対称になる。
        """
        ranks = []
        recall_1 = recall_3 = recall_5 = recall_10 = recall_20 = 0
        for qi, expected in enumerate(expected_per_query):
            idx_row = top_idx[qi]
            top_ids = []
            for i in idx_row:
                if i < 0:
                    top_ids.append(None)
                    continue
                aid = self.article_ids[i]
                if aid is not None:
                    top_ids.append(aid)
                else:
                    # Non-article fallback: directive_id then chunk_id (mirrors line 797)
                    top_ids.append(self._directive_ids[i] or self._chunk_ids[i])
            rank = _rank_of_first_match(top_ids, expected)
            ranks.append(rank)
            if rank is not None:
                if rank <= 1:
                    recall_1 += 1
                if rank <= 3:
                    recall_3 += 1
                if rank <= 5:
                    recall_5 += 1
                if rank <= 10:
                    recall_10 += 1
                if rank <= 20:
                    recall_20 += 1
        n = len(expected_per_query)
        mrr = sum((1.0 / r) if r is not None else 0.0 for r in ranks) / n if n else 0.0
        return {
            "n": n,
            "recall_1": recall_1,
            "recall_3": recall_3,
            "recall_5": recall_5,
            "recall_10": recall_10,
            "recall_20": recall_20,
            "mrr": mrr,
            "ranks": ranks,
        }


def main():
    ap = argparse.ArgumentParser(description="Top-K retrieval test on JuriCode-JP.")
    ap.add_argument("--embedded", type=Path, required=True)
    ap.add_argument("--eval-set", type=Path, nargs="+", required=True)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--show-per-query", action="store_true")
    ap.add_argument(
        "--normalize-query",
        action="store_true",
        help="法令略称展開 + 漢数字正規化を適用",
    )
    ap.add_argument(
        "--hybrid-bm25",
        action="store_true",
        help="BM25 (TF-IDF char-ngram) と Dense を RRF で結合",
    )
    ap.add_argument(
        "--bm25-corpus",
        type=Path,
        help="BM25 用の corpus jsonl パス (--hybrid-bm25 と併用)",
    )
    ap.add_argument(
        "--rrf-k",
        type=int,
        default=60,
        help="RRF の k パラメータ (default: 60)",
    )
    ap.add_argument(
        "--reranker",
        action="store_true",
        help="Cross-encoder (bge-reranker-v2-m3) で dense top-N を re-rank",
    )
    ap.add_argument(
        "--reranker-corpus",
        type=Path,
        help="reranker 用の corpus jsonl パス (text を読み込む。指定なければ --bm25-corpus 使用)",
    )
    ap.add_argument(
        "--reranker-model",
        type=str,
        default="BAAI/bge-reranker-v2-m3",
        help="Cross-encoder model ID (default: BAAI/bge-reranker-v2-m3)",
    )
    ap.add_argument(
        "--reranker-candidates",
        type=int,
        default=30,
        help="reranker に渡す dense top-N の N (default: 30)",
    )
    ap.add_argument(
        "--dedup-by-article",
        action="store_true",
        help="v0.2 segment retrieval を article-level Recall として測定 (同じ article の重複 segment を 1 つにまとめる)",
    )
    ap.add_argument(
        "--hyde",
        action="store_true",
        help="HyDE: 仮想法令条文を生成し 原クエリ dense と Late Fusion (E3')",
    )
    ap.add_argument(
        "--hyde-only",
        action="store_true",
        help="HyDE 仮想文 dense のみ (原クエリと融合しない・E3)",
    )
    ap.add_argument(
        "--hyde-fusion",
        choices=["rrf", "minmax"],
        default="rrf",
        help="Late Fusion 方式: rrf(ランクベース) / minmax(各パス正規化後加算)。生スコア加算は不可 (default: rrf)",
    )
    ap.add_argument(
        "--hyde-cache",
        type=Path,
        help="HyDE 仮想文キャッシュ jsonl (--hyde / --hyde-only で必須・query_hash 照合)",
    )
    ap.add_argument(
        "--hyde-gen-model",
        type=str,
        default="gemini-2.5-flash",
        help="仮想文生成 LLM (Gemini generation model, default: gemini-2.5-flash)",
    )
    args = ap.parse_args()

    if (args.hyde or args.hyde_only) and not args.hyde_cache:
        sys.exit("ERROR: --hyde / --hyde-only requires --hyde-cache <path>")

    try:
        matrix, records, state = _load_artefacts(args.embedded)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"Corpus: {len(records):,} record(s), dim {matrix.shape[1]:,}, "
        f"provider={state.get('provider')} model={state.get('model')}",
        file=sys.stderr,
    )

    queries = _load_queries(args.eval_set)
    print(f"Queries: {len(queries):,}", file=sys.stderr)

    # Query preprocessing
    questions_orig = [q["question"] for q in queries]
    if args.normalize_query:
        questions = [normalize_legal_query(q) for q in questions_orig]
        n_changed = sum(1 for a, b in zip(questions_orig, questions, strict=False) if a != b)
        print(f"  [normalize-query] {n_changed}/{len(questions)} queries modified", file=sys.stderr)
    else:
        questions = questions_orig

    print("", file=sys.stderr)

    # FU-406: RetrievalPipeline に責務を集約 (article_ids 展開・各段の retrieval)
    pipeline = RetrievalPipeline(state, records)
    article_ids = pipeline.article_ids

    # Dense retrieval -- dedup_by_article 時は候補プールを広めに取る。
    # reranker on のときは rerank candidate (rerank_candidate_k) を賄える幅を母集団決定時点で保証 (FU-425/§5-3)。
    rerank_k = max(args.reranker_candidates, args.top_k) if args.reranker else 0
    base_pool = max(args.top_k * 10, 100) if args.dedup_by_article else max(args.top_k * 3, 30)
    candidate_pool = max(base_pool, rerank_k)
    query_matrix = _encode_queries(questions, state)
    dense_sims, dense_top_idx = pipeline.dense_retrieve(query_matrix, matrix, candidate_pool)

    # HyDE (柱1-D E3/E3'): 仮想文 dense で dense 結果を置換し後段に渡す (hybrid/rerank と合成)。
    if args.hyde or args.hyde_only:
        dense_top_idx, dense_sims = _apply_hyde(
            questions_orig, state, matrix, dense_sims, dense_top_idx, candidate_pool, args
        )

    # Hybrid (BM25 + Dense via RRF)
    # dedup_by_article 併用時は wide な候補を維持して後段 dedup に渡す
    wide_pool = candidate_pool
    if args.hybrid_bm25:
        if not args.bm25_corpus:
            sys.exit("ERROR: --hybrid-bm25 requires --bm25-corpus <path>")
        print(f"Building BM25 index from {args.bm25_corpus} ...", file=sys.stderr)
        index_info, tfidf_matrix, _bm25_article_ids = build_tfidf_index(args.bm25_corpus)
        _bm25_sims, bm25_top_idx = bm25_topk_per_query(
            questions, index_info, tfidf_matrix, wide_pool
        )
        # RRF combine -- dedup / reranker 時は wide な top_idx_wide を出力 (rerank_candidate_k 以上を保証)
        result_k = wide_pool if args.dedup_by_article else args.top_k
        result_k = max(result_k, rerank_k)
        top_idx_wide = pipeline.hybrid_combine(
            dense_top_idx[:, :wide_pool],
            bm25_top_idx,
            result_k,
            rrf_k=args.rrf_k,
        )
        top_idx = top_idx_wide[:, : args.top_k]
        sims = dense_sims  # for display
    else:
        top_idx_wide = dense_top_idx
        top_idx = dense_top_idx[:, : args.top_k]
        sims = dense_sims

    # Article-level dedup -- hybrid 適用後の top_idx_wide を使う (バグ修正 2026-05-22)
    if args.dedup_by_article:
        top_idx = pipeline.dedup_by_article(top_idx_wide, args.top_k)
        print(
            f"  [dedup-by-article] top-{args.top_k} = {args.top_k} unique articles", file=sys.stderr
        )

    # Reranker (Cross-encoder)
    if args.reranker:
        reranker_corpus_path = args.reranker_corpus or args.bm25_corpus
        if not reranker_corpus_path:
            sys.exit("ERROR: --reranker requires --reranker-corpus (or --bm25-corpus) <path>")
        print(f"Loading corpus texts from {reranker_corpus_path} ...", file=sys.stderr)
        corpus_texts = _load_corpus_texts(reranker_corpus_path)
        if args.dedup_by_article:
            # dedup モード: rerank 前に各記事トップチャンク1件のみ残し、ユニーク記事を
            # rerank_candidate_k 件集めてから rerank (RRF 上位が1記事のチャンクで偏った際の
            # 出力枯渇 2-1 を構造的に防止)。
            candidates = pipeline.dedup_by_article(top_idx_wide, rerank_k)
        else:
            # FU-425 の candidate 選択を 1 箇所に局所化 (select_rerank_candidates)。
            # hybrid on なら hybrid 後集合 (top_idx_wide) の上位 rerank_candidate_k 件を candidate に。
            candidates = pipeline.select_rerank_candidates(
                dense_top_idx,
                top_idx_wide,
                hybrid_on=args.hybrid_bm25,
                n_candidates=args.reranker_candidates,
                top_k=args.top_k,
            )
        top_idx = pipeline.rerank(
            questions,
            candidates,
            corpus_texts,
            args.top_k,
            model_name=args.reranker_model,
        )
        sims = dense_sims  # for display

    # article_ids は既に上で展開済 (pipeline.article_ids)
    law_name_ja = pipeline.law_name_ja
    article_number = pipeline.article_number

    # Support both article queries (expected_article_ids) and directive queries (expected_directive_id)
    # R14: directive queries use chunk_id / directive_id as the match key
    def _expected_ids(q: dict) -> set:
        ids: set = set(q.get("expected_article_ids") or [])
        did = q.get("expected_directive_id")
        if did:
            ids.add(did)
        # TaxAnswer queries: expected_qa_code -> chunk_id form "hojin-taxanswer-NNNN"
        qa_code = q.get("expected_qa_code")
        if qa_code:
            ids.add(f"hojin-taxanswer-{qa_code}")
        return ids

    expected_per_query = [_expected_ids(q) for q in queries]
    metrics = pipeline.aggregate_metrics(top_idx, expected_per_query)
    n = metrics["n"]
    if n == 0:
        return 1
    ranks = metrics["ranks"]

    if args.show_per_query:
        for qi, q in enumerate(queries):
            question = questions[qi]
            expected = expected_per_query[qi]
            idx_row = top_idx[qi]
            print(f"=== {q['id']}: {question}", file=sys.stderr)
            print(f"   expected: {sorted(expected)}", file=sys.stderr)
            print(f"   first match rank: {ranks[qi]}", file=sys.stderr)
            for i, idx in enumerate(idx_row[:5], 1):
                if idx < 0:
                    continue
                aid = article_ids[idx]
                score = float(sims[qi, idx]) if (sims is not None and idx >= 0) else 0.0
                lawname = law_name_ja[idx] or ""
                artnum = article_number[idx] or ""
                # R14: directive records have article_id=None; use chunk_id for match + display
                chunk_id = pipeline.records[idx].get("chunk_id") or ""
                directive_id = pipeline.records[idx].get("directive_id") or ""
                match_key = aid if aid else (directive_id or chunk_id)
                marker = " OK" if match_key in expected else ""
                # Display: law article vs directive vs taxanswer
                seg_type = pipeline.records[idx].get("segment_type") or ""
                if aid:
                    entity_desc = f"{lawname} 第{artnum}条"
                elif seg_type == "taxanswer":
                    qa_code = pipeline.records[idx].get("code") or chunk_id
                    qa_title = pipeline.records[idx].get("title") or ""
                    entity_desc = f"タックスアンサー No.{qa_code} {qa_title}"
                else:
                    directive_num = pipeline.records[idx].get("directive_number") or directive_id
                    entity_desc = f"{lawname} {directive_num}"
                display_id = aid or directive_id or chunk_id
                print(
                    f"   [{i}] {display_id:48s} {score:.3f}  {entity_desc}{marker}",
                    file=sys.stderr,
                )
            print("", file=sys.stderr)

    recall_1 = metrics["recall_1"]
    recall_3 = metrics["recall_3"]
    recall_5 = metrics["recall_5"]
    recall_10 = metrics["recall_10"]
    recall_20 = metrics["recall_20"]
    print("=== Aggregate metrics ===", file=sys.stderr)
    print(f"  N (queries)  : {n}", file=sys.stderr)
    print(f"  Recall@1     : {recall_1}/{n} = {recall_1 / n:.1%}", file=sys.stderr)
    print(f"  Recall@3     : {recall_3}/{n} = {recall_3 / n:.1%}", file=sys.stderr)
    print(f"  Recall@5     : {recall_5}/{n} = {recall_5 / n:.1%}", file=sys.stderr)
    print(f"  Recall@10    : {recall_10}/{n} = {recall_10 / n:.1%}", file=sys.stderr)
    print(f"  Recall@20    : {recall_20}/{n} = {recall_20 / n:.1%}", file=sys.stderr)
    print(f"  MRR          : {metrics['mrr']:.3f}", file=sys.stderr)

    # Settings tag for log-friendliness
    settings: list[str] = []
    if args.normalize_query:
        settings.append("normalize-query")
    if args.hybrid_bm25:
        settings.append(f"hybrid-bm25(rrf-k={args.rrf_k})")
    if args.reranker:
        settings.append(f"reranker({args.reranker_model.split('/')[-1]})")
    if args.dedup_by_article:
        settings.append("dedup-by-article")
    if args.hyde_only:
        settings.append(f"hyde-only(gen={args.hyde_gen_model})")
    elif args.hyde:
        settings.append(f"hyde({args.hyde_fusion},gen={args.hyde_gen_model})")
    if settings:
        print(f"  Settings     : {','.join(settings)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

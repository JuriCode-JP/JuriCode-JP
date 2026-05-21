#!/usr/bin/env python3
"""JuriCode-JP Top-K Retrieval Tester.

Provider is detected from .vec.pkl. Supports tfidf / openai / gemini.

新規拡張 (2026-05-21):
- --normalize-query: 法令略称展開 + 漢数字→アラビア数字正規化
- --hybrid-bm25: TF-IDF (char 2-3gram) と Dense を RRF (k=60) で結合
- --bm25-corpus: BM25 用の corpus jsonl パス (text フィールド)
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import re
import sys
from pathlib import Path

import numpy as np


# =====================================================
# Query normalization (法令名・条番号の正規化)
# =====================================================

KANJI_DIGIT = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

# 略称 → (略称をそのまま残しつつ) 正式名称も付加することで両方で hit させる
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


def _normalize_fullwidth_digits(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _kanji_to_int(s: str) -> int | None:
    """漢数字 → 整数. 「百二十三」 -> 123."""
    if not s:
        return None
    total = 0
    current = 0
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    for ch in s:
        if ch in KANJI_DIGIT:
            current = current * 10 + KANJI_DIGIT[ch] if current else KANJI_DIGIT[ch]
        elif ch in unit_map:
            unit = unit_map[ch]
            current = current if current else 1
            total += current * unit
            current = 0
    total += current
    return total if total > 0 else None


def _arabic_version_of_article_numbers(text: str) -> str:
    """漢数字の条番号をアラビア数字に変換した版を生成 (置換せず別バージョン)."""
    def repl(m):
        main_kanji = m.group(1)
        sub_kanji = m.group(2)
        main_num = _kanji_to_int(main_kanji)
        if main_num is None:
            return m.group(0)
        if sub_kanji:
            sub_num = _kanji_to_int(sub_kanji)
            if sub_num is not None:
                return f"第{main_num}条の{sub_num}"
        return f"第{main_num}条"

    pattern = r"第([〇一二三四五六七八九十百千万]+)条(?:の([〇一二三四五六七八九十百千万]+))?"
    return re.sub(pattern, repl, text)


def _kanji_version_of_article_numbers(text: str) -> str:
    """アラビア数字の条番号を漢数字に変換した版を生成 (corpus body マッチ用)."""
    def int_to_kanji(n: int) -> str:
        # Simple int -> kanji for numbers up to 9999
        if n == 0:
            return "〇"
        digits = "〇一二三四五六七八九"
        result = ""
        if n >= 1000:
            d = n // 1000
            result += (digits[d] if d > 1 else "") + "千"
            n %= 1000
        if n >= 100:
            d = n // 100
            result += (digits[d] if d > 1 else "") + "百"
            n %= 100
        if n >= 10:
            d = n // 10
            result += (digits[d] if d > 1 else "") + "十"
            n %= 10
        if n > 0:
            result += digits[n]
        return result

    def repl(m):
        main_num = int(m.group(1))
        sub_str = m.group(2)
        result = f"第{int_to_kanji(main_num)}条"
        if sub_str:
            sub_num = int(sub_str)
            result += f"の{int_to_kanji(sub_num)}"
        return result

    pattern = r"第(\d+)条(?:の(\d+))?"
    return re.sub(pattern, repl, text)


def _expand_law_abbreviations_list(text: str) -> list[str]:
    """略称の正式名称リストを返す (追加用)."""
    additions = []
    for abbrev, expanded in LAW_ABBREV_EXPANSIONS.items():
        if abbrev in text and expanded not in text:
            additions.append(expanded)
    return additions


def normalize_legal_query(query: str) -> str:
    """法令名・条番号の総合正規化(置換ではなく追加で複数バージョンを構築).

    e-Gov 法令本文は漢数字を使用するため、半角→漢数字版も追加することで
    corpus body の embedding マッチを強化する.
    """
    # 全角→半角
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
            article_ids.append(obj.get("article_id", ""))

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
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        sys.exit(
            "ERROR: sentence-transformers not installed. "
            "Run: pip install sentence-transformers"
        )

    print(f"  [reranker] loading {model_name} ...", file=sys.stderr)
    model = CrossEncoder(model_name, max_length=max_length)
    print(f"  [reranker] re-ranking {len(queries)} queries x {candidates_per_query.shape[1]} candidates ...", file=sys.stderr)

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
        sorted_pairs = sorted(zip(scores, valid_cand), key=lambda x: -x[0])
        sorted_indices = [int(c) for s, c in sorted_pairs][:top_k_final]
        # Pad if fewer than top_k_final
        while len(sorted_indices) < top_k_final:
            sorted_indices.append(-1)
        reranked[qi] = sorted_indices

    print(f"  [reranker] done.", file=sys.stderr)
    return reranked



def rrf_combine_per_query(dense_top_idx, bm25_top_idx, top_k, k_rrf=60):
    """各クエリで dense top-N と bm25 top-N を RRF で結合し top-K を返す."""
    n_queries = dense_top_idx.shape[0]
    combined = np.zeros((n_queries, top_k), dtype=np.int64)
    for qi in range(n_queries):
        scores = {}
        for rank, idx in enumerate(dense_top_idx[qi], 1):
            scores[int(idx)] = scores.get(int(idx), 0.0) + 1.0 / (k_rrf + rank)
        for rank, idx in enumerate(bm25_top_idx[qi], 1):
            scores[int(idx)] = scores.get(int(idx), 0.0) + 1.0 / (k_rrf + rank)
        sorted_indices = sorted(scores.keys(), key=lambda x: -scores[x])[:top_k]
        # pad if fewer than top_k
        while len(sorted_indices) < top_k:
            sorted_indices.append(-1)
        combined[qi] = sorted_indices[:top_k]
    return combined


# =====================================================
# Existing helpers
# =====================================================


def _load_artefacts(prefix):
    npy_path = prefix.with_suffix(".npy")
    meta_path = prefix.with_suffix(".meta.jsonl")
    vec_path = prefix.with_suffix(".vec.pkl")
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
                        wait = 1.5 ** attempt
                        print(
                            f"  [gemini retry {attempt}/{MAX_RETRIES}] {type(e).__name__}: {e} - waiting {wait:.1f}s",
                            file=sys.stderr,
                        )
                        _time.sleep(wait)
                    else:
                        print(f"  [gemini FAILED after {MAX_RETRIES} retries] {last_err}", file=sys.stderr)
                        raise
        return np.asarray(all_embeddings, dtype=np.float32)

    sys.exit(f"ERROR: unsupported provider in artefacts: {provider!r}")


def _cosine_topk(query_matrix, corpus_matrix, top_k):
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
    args = ap.parse_args()

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
        n_changed = sum(1 for a, b in zip(questions_orig, questions) if a != b)
        print(f"  [normalize-query] {n_changed}/{len(questions)} queries modified", file=sys.stderr)
    else:
        questions = questions_orig

    print("", file=sys.stderr)

    # Dense retrieval
    query_matrix = _encode_queries(questions, state)
    dense_sims, dense_top_idx = _cosine_topk(query_matrix, matrix, max(args.top_k * 3, 30))

    # Hybrid (BM25 + Dense via RRF)
    if args.hybrid_bm25:
        if not args.bm25_corpus:
            sys.exit("ERROR: --hybrid-bm25 requires --bm25-corpus <path>")
        print(f"Building BM25 index from {args.bm25_corpus} ...", file=sys.stderr)
        index_info, tfidf_matrix, _bm25_article_ids = build_tfidf_index(args.bm25_corpus)
        _bm25_sims, bm25_top_idx = bm25_topk_per_query(
            questions, index_info, tfidf_matrix, max(args.top_k * 3, 30)
        )
        # RRF combine
        top_idx = rrf_combine_per_query(
            dense_top_idx[:, : max(args.top_k * 3, 30)],
            bm25_top_idx,
            args.top_k,
            k_rrf=args.rrf_k,
        )
        sims = dense_sims  # for display
    else:
        top_idx = dense_top_idx[:, : args.top_k]
        sims = dense_sims

    # Reranker (Cross-encoder)
    if args.reranker:
        reranker_corpus_path = args.reranker_corpus or args.bm25_corpus
        if not reranker_corpus_path:
            sys.exit("ERROR: --reranker requires --reranker-corpus (or --bm25-corpus) <path>")
        print(f"Loading corpus texts from {reranker_corpus_path} ...", file=sys.stderr)
        corpus_texts = _load_corpus_texts(reranker_corpus_path)
        # Take dense top-N (e.g. 30) as candidates, then rerank to top-K
        n_candidates = args.reranker_candidates
        candidates = dense_top_idx[:, : max(n_candidates, args.top_k)]
        top_idx = rerank_with_cross_encoder(
            questions,
            candidates,
            corpus_texts,
            args.top_k,
            model_name=args.reranker_model,
        )
        sims = dense_sims  # for display

    article_ids = [r.get("article_id") for r in records]
    law_name_ja = [r.get("law_name_ja") for r in records]
    article_number = [r.get("article_number") for r in records]

    ranks = []
    recall_1 = recall_3 = recall_10 = 0

    for qi, q in enumerate(queries):
        question = questions[qi]
        expected = set(q["expected_article_ids"])
        idx_row = top_idx[qi]
        top_ids = [article_ids[i] if i >= 0 else None for i in idx_row]

        rank = _rank_of_first_match(top_ids, expected)
        ranks.append(rank)

        if rank is not None:
            if rank <= 1:
                recall_1 += 1
            if rank <= 3:
                recall_3 += 1
            if rank <= 10:
                recall_10 += 1

        if args.show_per_query:
            print(f"=== {q['id']}: {question}", file=sys.stderr)
            print(f"   expected: {sorted(expected)}", file=sys.stderr)
            print(f"   first match rank: {rank}", file=sys.stderr)
            for i, idx in enumerate(idx_row[:5], 1):
                if idx < 0:
                    continue
                aid = article_ids[idx]
                score = float(sims[qi, idx]) if (sims is not None and idx >= 0) else 0.0
                lawname = law_name_ja[idx] or ""
                artnum = article_number[idx] or ""
                marker = " OK" if aid in expected else ""
                print(
                    f"   [{i}] {aid:48s} {score:.3f}  {lawname} 第{artnum}条{marker}",
                    file=sys.stderr,
                )
            print("", file=sys.stderr)

    n = len(queries)
    if n == 0:
        return 1
    mrr = sum((1.0 / r) if r is not None else 0.0 for r in ranks) / n

    print("=== Aggregate metrics ===", file=sys.stderr)
    print(f"  N (queries)  : {n}", file=sys.stderr)
    print(f"  Recall@1     : {recall_1}/{n} = {recall_1 / n:.1%}", file=sys.stderr)
    print(f"  Recall@3     : {recall_3}/{n} = {recall_3 / n:.1%}", file=sys.stderr)
    print(f"  Recall@10    : {recall_10}/{n} = {recall_10 / n:.1%}", file=sys.stderr)
    print(f"  MRR          : {mrr:.3f}", file=sys.stderr)

    # Settings tag for log-friendliness
    settings = []
    if args.normalize_query:
        settings.append("normalize-query")
    if args.hybrid_bm25:
        settings.append(f"hybrid-bm25(rrf-k={args.rrf_k})")
    if args.reranker:
        settings.append(f"reranker({args.reranker_model.split('/')[-1]})")
    if settings:
        print(f"  Settings     : {', '.join(settings)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

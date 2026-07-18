"""Cosine-similarity top-k for dense retrieval.

Single source of truth for `_cosine_topk`, moved verbatim from
tools/embed/retrieve.py. numpy is imported lazily inside the function.
"""

from __future__ import annotations


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

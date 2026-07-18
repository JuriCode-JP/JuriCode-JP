"""Article-level dedup for dense retrieval.

Single source of truth for `dedup_by_article`, moved verbatim from
tools/embed/retrieve.py. numpy is imported lazily inside the function.
"""

from __future__ import annotations


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

"""Resident retrieval service core for JuriCode-JP (moved from tools/serve).

Load the embedding index once, run dense top-k + article-level dedup, and return
citation-bearing hit dicts. Pure core: no HTTP, no pydantic. tools/serve/
retrieval_server.py re-imports this so every eval caller (b4_eval, reproduce_a3)
runs the identical class object.

numpy is imported lazily inside methods, so this module imports where numpy is absent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .artefacts import _load_artefacts
from .dedup import dedup_by_article
from .encode import _encode_queries

EXPECTED_DIM = 3072  # gemini-embedding-001
_SUBCHUNK_RE = re.compile(r"-sub\d+$")  # taxanswer sub-chunk suffix (FU-553 PoC fold)


# =====================================================
# Pure helpers (numpy-free; unit-testable everywhere)
# =====================================================


def fold_taxanswer_chunk_id(chunk_id: str, layer: str | None) -> str:
    """taxanswer sub-chunk の chunk_id から '-subN' を落とした doc key を返す (FU-553 PoC).

    Why: taxanswer は article_id も directive_id も持たない -> 既定の dedup キーは chunk_id に
    fallback し、同一タックスアンサーの sub-chunk (例 '...-2011-sub2') が top-K の複数枠を
    占有し得る。layer=='taxanswer' の sub-chunk のみ接尾辞を畳んで doc 単位に dedup する。
    非 taxanswer や sub 無しはそのまま (honbun の '-art-1-p1' 等を誤って畳まない)。
    """
    if layer == "taxanswer" and _SUBCHUNK_RE.search(chunk_id):
        return _SUBCHUNK_RE.sub("", chunk_id)
    return chunk_id


def build_dedup_keys(
    base_keys: list[str], chunk_ids: list[str], layers: list[str | None], fold: bool
) -> list[str]:
    """dedup キー列を返す。fold=False なら base_keys をそのまま (A-3 測定条件と同一)。

    Why: base_keys = article_id else chunk_id (RetrievalPipeline._dedup_keys と同一規則で、
    索引 meta に directive_id が無いため A-3 の _match_keys と一致)。fold=True のときだけ
    taxanswer sub-chunk を doc key に畳む。これにより「畳み込み OFF = A-3 再現」「ON = PoC 改善」を
    同一コードで切替でき、サイレント乖離を防ぐ。
    """
    if not fold:
        return list(base_keys)
    out: list[str] = []
    for bk, cid, lay in zip(base_keys, chunk_ids, layers, strict=True):
        # taxanswer は base_key が chunk_id (article_id 無し) なので、その chunk_id を畳む。
        out.append(fold_taxanswer_chunk_id(cid, lay) if lay == "taxanswer" else bk)
    return out


def filter_row_by_layers(
    idx_row: list[int], layers: list[str | None], target_layers: list[str] | None
) -> list[int]:
    """候補 index 列を target_layers で事前フィルタ (順序保持)。null なら全層 (無変更)。

    Why (§3.5): target_layers は boost ではなく filter。呼び出し側が明示指定した layer のみを
    候補プールに残し、その後に dedup + top-K を適用する。自動 boost (A3-F) は実装しない。
    """
    if not target_layers:
        return list(idx_row)
    allowed = set(target_layers)
    return [i for i in idx_row if i >= 0 and layers[i] in allowed]


# =====================================================
# RetrievalService (numpy-backed; loaded once at startup)
# =====================================================


class RetrievalService:
    """v8b 索引と行アライン corpus を常駐ロードし、dense+dedup 検索を提供する (1 責務).

    Why lazy import: numpy は宣言依存でなく retrieve.py 同様 method 内 import。--help / schema
    テストは numpy 無し環境でも通す (cold start / CI 非依存の規律)。
    """

    def __init__(self, index_prefix: Path, corpus_path: Path, default_fold: bool):
        import numpy as np  # lazy import

        self.index_prefix = index_prefix
        self.corpus_path = corpus_path
        self.default_fold = default_fold

        matrix, records, state = _load_artefacts(index_prefix)
        self.state = state
        self.records = records
        n = len(records)

        # ---- fail-loud integrity checks (§3.4): 黙って動かさない ----
        if matrix.shape[0] != n:
            raise ValueError(f"npy rows ({matrix.shape[0]}) != meta rows ({n})")
        if matrix.shape[1] != EXPECTED_DIM:
            raise ValueError(f"dim ({matrix.shape[1]}) != expected {EXPECTED_DIM}")
        meta_chunk_ids = [r.get("chunk_id") for r in records]
        if len(set(meta_chunk_ids)) != n:
            raise ValueError(f"chunk_id not unique in meta ({len(set(meta_chunk_ids))} of {n})")

        # ---- row-aligned corpus supplies layer / corpus_group / directive_id / text ----
        # (これらは索引 meta に無い。A-3 harness と同じ行アライン corpus から供給する。)
        corpus_rows = _load_corpus(corpus_path)
        if len(corpus_rows) != n:
            raise ValueError(f"corpus rows ({len(corpus_rows)}) != meta rows ({n})")
        corpus_chunk_ids = [r.get("chunk_id") for r in corpus_rows]
        if corpus_chunk_ids != meta_chunk_ids:
            first = next((i for i in range(n) if corpus_chunk_ids[i] != meta_chunk_ids[i]), -1)
            raise ValueError(f"corpus/meta chunk_id row misalignment (first at row {first})")

        self.chunk_ids = meta_chunk_ids
        self.layers: list[str | None] = [r.get("layer") for r in corpus_rows]
        self.corpus_groups: list[str | None] = [r.get("corpus_group") for r in corpus_rows]
        self.directive_ids: list[str | None] = [r.get("directive_id") for r in corpus_rows]
        self.law_name_ja: list[str | None] = [r.get("law_name_ja") for r in records]
        self.article_ids: list[str | None] = [r.get("article_id") for r in records]
        self.article_number: list[str | None] = [r.get("article_number") for r in records]
        self._texts: list[str] = [r.get("text") or "" for r in corpus_rows]
        self._texts_raw: list[str | None] = [r.get("text_raw") for r in corpus_rows]
        self._chunk_pos = {c: i for i, c in enumerate(self.chunk_ids)}

        # retrieval_server は META records で pipeline を作っていた (meta に directive_id は無い)。
        # RetrievalPipeline._dedup_keys と 1 バイト同一の式をインライン化する
        # (pipeline._dedup_keys = article_id else chunk_id で A-3 の _match_keys と一致・T6 再現の要):
        meta_directive_ids = [r.get("directive_id") for r in records]
        # 3リストは同一 records 由来ゆえ長さは構造的に等しい。将来の破壊を fail-loud で捕える
        # 挙動中立ガード (正常データでは決して発火しない・_base_keys の値は変えない):
        assert len(self.article_ids) == len(meta_directive_ids) == len(self.chunk_ids)
        self._base_keys = [
            (a if a is not None else (d or c))
            for a, d, c in zip(self.article_ids, meta_directive_ids, self.chunk_ids, strict=False)
        ]

        # fold precompute (§3.6 P2): dedup キー列を fold OFF/ON 両方で起動時に構築し、
        # リクエスト毎の build_dedup_keys 再構築 (+16ms) を解消する。挙動不変 (同関数の
        # 出力を起動時にキャッシュするだけ)。retrieve() は fold 値でこの 2 本から選ぶ。
        self._keys_fold_off: list[str] = list(self._base_keys)
        self._keys_fold_on: list[str] = build_dedup_keys(
            self._base_keys, self.chunk_ids, self.layers, fold=True
        )

        # 事前正規化 (常駐サービスの標準形。server.py と同じ)。_cosine_topk と同一の正規化式で
        # corpus を 1 回だけ正規化し、クエリ時は正規化クエリとの内積 + argsort に落とす。
        # 結果は _cosine_topk と数学的に同一 (T6 が S 相当の等価ゲートとして保証する)。
        cn = np.linalg.norm(matrix, axis=1, keepdims=True)
        cn[cn == 0] = 1.0
        self._norm_matrix = (matrix / cn).astype(np.float32)
        del matrix
        self.n_records = n
        self.dim = EXPECTED_DIM

    # ---- encode ----
    def encode(self, query: str):
        """1 クエリを埋め込みに変換 (1, dim)。retrieve._encode_queries を再利用 (A-3 と同一経路)."""
        return _encode_queries([query], self.state)

    # ---- retrieval ----
    def dense_pool(self, query_vec, pool: int):
        """事前正規化 corpus に対する dense top-`pool` の (sims_row, idx_row) を返す。

        _cosine_topk と同一 (query 正規化 -> 内積 -> argsort(-sims))。corpus 正規化のみ
        起動時に前倒し済み。
        """
        import numpy as np  # lazy import

        qn = np.linalg.norm(query_vec, axis=1, keepdims=True)
        qn[qn == 0] = 1.0
        qnorm = (query_vec / qn).astype(np.float32)
        sims = (qnorm @ self._norm_matrix.T)[0]  # (N,)
        idx_row = np.argsort(-sims)[:pool]
        return sims, idx_row

    def retrieve(
        self,
        query_vec,
        top_k: int,
        target_layers: list[str] | None,
        dedup: bool,
        fold: bool,
    ) -> tuple[list[dict], int]:
        """dense -> (target_layers filter) -> (dedup) -> top-K。hit dict のリストと候補数を返す."""
        import numpy as np  # lazy import

        # candidate pool: A-3 は CANDIDATE_POOL=60 (top_k=20)。dedup で unique-K を賄える幅を確保。
        # >=60 なら top-K unique は dense 上位から決まり pool 幅に不感 (T6 が確認)。
        pool = max(top_k * 3, 60)
        sims, idx_row = self.dense_pool(query_vec, pool)
        idx_list = [int(i) for i in idx_row]
        n_candidates = len(idx_list)

        idx_list = filter_row_by_layers(idx_list, self.layers, target_layers)

        if dedup:
            # 起動時 precompute 済みのキー列を選ぶ (build_dedup_keys の出力と同一・挙動不変)。
            keys = self._keys_fold_on if fold else self._keys_fold_off
            deduped = dedup_by_article(np.array([idx_list], dtype=np.int64), keys, top_k)
            final = [int(i) for i in deduped[0] if int(i) >= 0]
        else:
            final = idx_list[:top_k]

        hits: list[dict] = []
        for rank, i in enumerate(final, start=1):
            hits.append(
                {
                    "chunk_id": self.chunk_ids[i],
                    "article_id": self.article_ids[i],
                    "directive_id": self.directive_ids[i],
                    "layer": self.layers[i],
                    "corpus_group": self.corpus_groups[i],
                    "law_name_ja": self.law_name_ja[i],
                    "article_number": self.article_number[i],
                    "score": float(sims[i]),
                    "rank": rank,
                }
            )
        return hits, n_candidates

    def chunks(self, chunk_ids: list[str]) -> tuple[list[dict], list[str]]:
        """chunk_id -> 本文つき chunk dict。見つからない id は missing に返す (Lazy 本文取得)."""
        out: list[dict] = []
        missing: list[str] = []
        for cid in chunk_ids:
            i = self._chunk_pos.get(cid)
            if i is None:
                missing.append(cid)
                continue
            out.append(
                {
                    "chunk_id": self.chunk_ids[i],
                    "article_id": self.article_ids[i],
                    "directive_id": self.directive_ids[i],
                    "layer": self.layers[i],
                    "corpus_group": self.corpus_groups[i],
                    "law_name_ja": self.law_name_ja[i],
                    "article_number": self.article_number[i],
                    "text": self._texts[i],
                    "text_raw": self._texts_raw[i],
                }
            )
        return out, missing

    def defaults(self) -> dict:
        """/healthz が出す既定値 (測定条件との差分を目視できるようにする)."""
        return {
            "mode": "dense",
            "dedup": True,
            "task_type": "RETRIEVAL_QUERY",
            "normalize": False,
            "taxanswer_subchunk_fold": self.default_fold,
        }


def _load_corpus(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows

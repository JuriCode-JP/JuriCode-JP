#!/usr/bin/env python3
"""HyDE (Hypothetical Document Embeddings) module for JuriCode-JP retrieval.

口語クエリと形式法令文の語彙ギャップを埋めるため、クエリから LLM が「仮想的な
法令条文文」を生成し、それを embed して dense retrieve する (柱1-D ablation, E3/E3')。

設計ロック (Rev.3 査読 Bug3/5/8/9):
  - **Late Fusion 限定**: 原クエリ dense と HyDE 仮想文 dense を独立検索し、得た
    rank/score を融合する。embedding の直接加算/平均・生スコア加算は禁止
    (口語クエリと擬似法令文はスコア分布が異なり、レンジの広いパスが他方を
    サイレント抹殺してダミーアンサンブル化するため)。融合は RRF(k=60) か
    各パス Min-Max 正規化後の score fusion のいずれかに限定する。
  - **仮想文キャッシュは ID キー照合**: trial 1 で生成した仮想文を jsonl 永続化し、
    trial 2/3 は ``query_hash`` での照合で引き当てる。ループ index 依存は禁止
    (順序ゆらぎで別クエリの仮想文を掴むサイレントなデータ汚染源)。引き当て失敗は
    warn でなく fail-loud (:class:`HydeCacheMiss`)。

torch / google-genai 非依存の純関数 (compute_query_hash / fusion / cache 照合) のみを
module top-level に置き、重い import (numpy / safe_write / google-genai) は関数内に
局所化する (retrieve.py の LAZY import 規律と同じ・sandbox unit test 可)。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# 仮想文生成のプロンプト雛形。{query} に口語クエリを差し込む。
HYDE_PROMPT_TEMPLATE = (
    "あなたは日本の法令文書の専門家です。次の質問に答える条文が実在すると仮定し、"
    "その条文として最も自然な日本語の法令文を1段落で作成してください。"
    "前置き・解説・引用符は付けず、条文本文だけを出力してください。\n\n"
    "質問: {query}\n\n条文:"
)


class HydeCacheMiss(KeyError):
    """仮想文キャッシュに該当 ID が無いことを表す fail-loud 例外 (Bug9)."""


@dataclass(frozen=True)
class HydeRecord:
    """1 クエリ分の HyDE 仮想文キャッシュレコード (ID キー = query_hash)."""

    query_hash: str
    query: str
    hypothetical_doc: str

    def to_dict(self) -> dict:
        return {
            "query_hash": self.query_hash,
            "query": self.query,
            "hypothetical_doc": self.hypothetical_doc,
        }

    @classmethod
    def from_dict(cls, obj: dict) -> HydeRecord:
        return cls(
            query_hash=obj["query_hash"],
            query=obj["query"],
            hypothetical_doc=obj["hypothetical_doc"],
        )


def compute_query_hash(query: str) -> str:
    """クエリ文字列から順序非依存で安定な ID キーを返す.

    Why: trial 2/3 のキャッシュ引き当てを「何番目か」でなく内容ハッシュで行うため
    (Bug9)。同一クエリは trial を跨いで必ず同じキーになり、出現順がズレても安全。
    """
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


# =====================================================
# 仮想文キャッシュ (ID キー照合・fail-loud)
# =====================================================


def load_hyde_cache(path: Path) -> dict[str, HydeRecord]:
    """jsonl キャッシュを ``query_hash`` キーの dict として読み込む.

    Why: ファイル不在は trial 1 (初回生成) を意味するため空 dict を返す。重複キーは
    キャッシュ破損として fail-loud (黙って後勝ちにすると別クエリ汚染を見逃すため)。
    """
    cache: dict[str, HydeRecord] = {}
    if not path.exists():
        return cache
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            rec = HydeRecord.from_dict(json.loads(line))
            if rec.query_hash in cache:
                raise ValueError(
                    f"Duplicate query_hash {rec.query_hash!r} in HyDE cache {path} (line {line_no})"
                )
            cache[rec.query_hash] = rec
    return cache


def save_hyde_cache(path: Path, cache: dict[str, HydeRecord]) -> None:
    """キャッシュを query_hash 昇順で jsonl 永続化 (safe_write 経由・LF 固定)."""
    from juricode_shared.safe_write import safe_write_jsonl  # lazy (§10.2)

    records = [cache[k].to_dict() for k in sorted(cache)]
    safe_write_jsonl(path, records)


def build_hyde_cache(
    queries: Sequence[str],
    *,
    generate_fn: Callable[[str], str],
    existing: dict[str, HydeRecord] | None = None,
    key_fn: Callable[[str], str] = compute_query_hash,
) -> dict[str, HydeRecord]:
    """trial 1: 未キャッシュのクエリだけ ``generate_fn`` で仮想文生成しキャッシュを拡張.

    Why: 同一 query_hash は1度だけ生成 (172x3 trial を素朴に回すと Gemini 429 死・Bug8)。
    既存キャッシュは再生成しないため trial 跨ぎで決定的・API 乱用を防ぐ。
    """
    cache: dict[str, HydeRecord] = dict(existing or {})
    for query in queries:
        key = key_fn(query)
        if key in cache:
            continue
        doc = generate_fn(query)
        cache[key] = HydeRecord(query_hash=key, query=query, hypothetical_doc=doc)
    return cache


def resolve_hypothetical_docs(
    queries: Sequence[str],
    cache: dict[str, HydeRecord],
    *,
    key_fn: Callable[[str], str] = compute_query_hash,
) -> list[str]:
    """queries に揃えて仮想文を ID キー照合で引き当てる (index 依存禁止・Bug9).

    Why: 引き当て失敗は warn でなく fail-loud。欠落を見逃すと別クエリの仮想文を
    黙って使うサイレント汚染になるため。
    """
    docs: list[str] = []
    for query in queries:
        key = key_fn(query)
        rec = cache.get(key)
        if rec is None:
            raise HydeCacheMiss(
                f"No cached hypothetical doc for query_hash {key!r} (query={query!r})"
            )
        docs.append(rec.hypothetical_doc)
    return docs


# =====================================================
# Late Fusion (RRF / Min-Max・生スコア加算禁止・Bug5)
# =====================================================


def rrf_fuse(rank_lists: Sequence, top_k: int, k_rrf: int = 60):
    """複数の dense rank list を RRF で融合し top_k の idx を返す (ランクベース=スケール非依存).

    Why: 原クエリ dense と HyDE 仮想文 dense は同一 modality だがスコア分布が異なる。
    ランク順位だけを使う RRF はレンジ差の影響を受けず、片方の抹殺を防ぐ (Bug5)。
    retrieve.rrf_combine_per_query と同じ -1 padding skip / 同率 (-score, idx) tie-break
    のセマンティクスを N-list へ一般化したもの。
    """
    import numpy as np  # lazy import

    n_queries = rank_lists[0].shape[0]
    combined = np.full((n_queries, top_k), -1, dtype=np.int64)
    for qi in range(n_queries):
        scores: dict[int, float] = {}
        for ranks in rank_lists:
            for rank, idx in enumerate(ranks[qi], 1):
                i = int(idx)
                if i < 0:
                    continue
                scores[i] = scores.get(i, 0.0) + 1.0 / (k_rrf + rank)
        ordered = sorted(scores.keys(), key=lambda x: (-scores[x], x))[:top_k]
        for j, idx_int in enumerate(ordered):
            combined[qi, j] = idx_int
    return combined


def min_max_fuse(top_idx_lists: Sequence, score_lists: Sequence, top_k: int):
    """各パス内で Min-Max 正規化した score を加算して融合し top_k の idx を返す.

    引数:
      top_idx_lists: 各パスの top_idx (n_queries, n_cand)。-1 は padding。
      score_lists:   各パスの score (top_idx_lists と同形・各候補の類似度)。

    Why: 生スコアを直接加算するとレンジの広いパスが他方を圧倒してサイレント抹殺する
    (Bug5)。各パス内で [0,1] へ正規化してから加算すれば、スケール差があっても両パスの
    順位情報が等しく反映される。全候補同値のパス (denom=0) は識別情報ゼロとして寄与 0。
    """
    import numpy as np  # lazy import

    n_queries = top_idx_lists[0].shape[0]
    combined = np.full((n_queries, top_k), -1, dtype=np.int64)
    for qi in range(n_queries):
        fused: dict[int, float] = {}
        for top_idx, scores in zip(top_idx_lists, score_lists, strict=True):
            pairs = [
                (int(idx), float(scores[qi][j]))
                for j, idx in enumerate(top_idx[qi])
                if int(idx) >= 0
            ]
            if not pairs:
                continue
            vals = [s for _, s in pairs]
            smin, smax = min(vals), max(vals)
            denom = smax - smin
            for idx, score in pairs:
                norm = (score - smin) / denom if denom > 0 else 0.0
                fused[idx] = fused.get(idx, 0.0) + norm
        ordered = sorted(fused.keys(), key=lambda x: (-fused[x], x))[:top_k]
        for j, idx_int in enumerate(ordered):
            combined[qi, j] = idx_int
    return combined


def make_gemini_generator(model: str, api_key: str | None = None) -> Callable[[str], str]:
    """Gemini generation モデルで仮想文を生成する generate_fn を返す (本番用・lazy import).

    Why: module を torch/google 非依存に保つため google-genai は呼び出し時に局所 import。
    unit test は本関数を使わず純粋な generate_fn を注入する。
    """
    import os

    from google import genai  # lazy import

    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set for HyDE generation")
    client = genai.Client(api_key=key)

    def _generate(query: str) -> str:
        resp = client.models.generate_content(
            model=model,
            contents=HYDE_PROMPT_TEMPLATE.format(query=query),
        )
        return (resp.text or "").strip()

    return _generate

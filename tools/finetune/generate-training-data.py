#!/usr/bin/env python3
"""generate-training-data.py -- JuriCode-JP corpus から reranker 訓練データを合成生成.

各 article について Gemini で 3 件の質問を生成し、
hard negative として dense embedding で類似する別 article を選定する.

出力 jsonl 形式 (1 line = 1 training triple):
  {"query": "...", "positive_id": "...", "negative_id": "...",
   "positive_text": "...", "negative_text": "...", "law_name_ja": "..."}

使い方:
  python tools/finetune/generate-training-data.py \\
    --corpus build/juricode-bq-11760.jsonl \\
    --embedded build/juricode-bq-11760-embedded \\
    --output data/training/2026-05-21-reranker-train.jsonl \\
    --max-articles 500 \\
    --questions-per-article 3 \\
    --hard-negatives-per-positive 2 \\
    --phases phase1-administrative phase1-police phase1-practitioner phase1-foundational

環境変数: GEMINI_API_KEY  (必須)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import numpy as np

# -------- Gemini setup --------


def _gemini_client():
    try:
        from google import genai
    except ImportError:
        sys.exit("ERROR: google-genai package not installed. Run: uv pip install google-genai")
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("ERROR: GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


# -------- Question generation --------

GENERATE_PROMPT = """以下の日本の法令条文を読み、自治体職員や一般市民が実務上抱きうる質問を {n} 件、日本語で生成してください。

【生成ルール】
1. 各質問は 20-50 文字程度の自然な日本語にしてください
2. 法令名 ({law_name}) や条番号は質問に含めないでください
3. 「この条文によると」「上記の規定では」などのメタ表現は避けてください
4. 1 件目は具体的な手続き・要件を問う質問
5. 2 件目は概念や定義を問う質問
6. 3 件目以降は応用的・状況設定型の質問

【条文】
{text}

【出力形式】
必ず以下の JSON 形式のみで出力してください. 説明やコードブロック (```) は不要です.
{{"questions": ["質問1", "質問2", "質問3"]}}
"""


def generate_questions(
    client, model: str, law_name: str, text: str, n: int, max_retries: int = 5
) -> list[str]:
    prompt = GENERATE_PROMPT.format(n=n, law_name=law_name, text=text[:1800])
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            raw = (resp.text or "").strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            qs = data.get("questions") or []
            qs = [q.strip() for q in qs if isinstance(q, str) and q.strip()]
            if qs:
                return qs[:n]
            raise ValueError(f"no questions in response: {raw[:200]}")
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = 1.5**attempt
                print(
                    f"    [retry {attempt}/{max_retries}] {type(e).__name__}: {e} - wait {wait:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
    print(f"    [FAILED after {max_retries}] {last_err}", file=sys.stderr)
    return []


# -------- Corpus loading --------


def load_corpus(jsonl_path: Path) -> list[dict]:
    """corpus 全件を順番通りにロード (idx は embedded 行と一致する前提)."""
    records = []
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def load_embeddings(embedded_prefix: Path):
    npy_path = Path(str(embedded_prefix) + ".npy")
    matrix = np.load(str(npy_path), mmap_mode="r")
    return matrix


# -------- Hard negative selection --------


def find_hard_negatives_per_idx(positive_idx: int, matrix, top_k: int = 10) -> list[int]:
    q = matrix[positive_idx]
    qn = np.linalg.norm(q)
    if qn == 0:
        return []
    qnorm = q / qn

    cn = np.linalg.norm(matrix, axis=1)
    cn[cn == 0] = 1.0
    cnorm = matrix / cn[:, None]

    sims = cnorm @ qnorm
    top_idx = np.argsort(-sims)[: top_k + 1]
    return [int(i) for i in top_idx if int(i) != positive_idx][:top_k]


# -------- Main --------


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--embedded", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-articles", type=int, default=500)
    parser.add_argument("--questions-per-article", type=int, default=3)
    parser.add_argument("--hard-negatives-per-positive", type=int, default=2)
    parser.add_argument("--phases", nargs="*", default=None)
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit-per-law", type=int, default=None)
    parser.add_argument("--sleep-between-articles", type=float, default=0.5)
    args = parser.parse_args()

    random.seed(args.seed)

    print(f"=== Loading corpus from {args.corpus} ===", file=sys.stderr)
    all_records = load_corpus(args.corpus)
    print(f"  total: {len(all_records)} articles", file=sys.stderr)

    print(f"=== Loading embeddings from {args.embedded} ===", file=sys.stderr)
    matrix = load_embeddings(args.embedded)
    print(f"  matrix shape: {matrix.shape}", file=sys.stderr)
    if matrix.shape[0] != len(all_records):
        print(
            f"WARNING: matrix rows ({matrix.shape[0]}) != corpus rows ({len(all_records)})",
            file=sys.stderr,
        )

    # idx → record の単純な配列 (embedded 行と corpus jsonl 行が一致と仮定)
    all_records_by_idx: list[dict] = all_records

    # phase フィルタ
    candidates = list(range(len(all_records)))
    if args.phases:
        phase_set = set(args.phases)
        candidates = [i for i in candidates if all_records[i].get("phase_category") in phase_set]
        print(f"  after phase filter {args.phases}: {len(candidates)} articles", file=sys.stderr)

    # law_id でグルーピング + cap
    if args.limit_per_law:
        per_law: dict[str, list[int]] = {}
        for i in candidates:
            per_law.setdefault(all_records[i].get("law_id", ""), []).append(i)
        capped: list[int] = []
        for _lid, idxs in per_law.items():
            random.shuffle(idxs)
            capped.extend(idxs[: args.limit_per_law])
        candidates = capped
        print(
            f"  after limit-per-law={args.limit_per_law}: {len(candidates)} articles",
            file=sys.stderr,
        )

    # text が短すぎる article は除外
    candidates = [i for i in candidates if len(all_records[i].get("text", "")) >= 30]

    # ランダムサンプル
    if len(candidates) > args.max_articles:
        random.shuffle(candidates)
        candidates = candidates[: args.max_articles]
    print(f"  sampled {len(candidates)} articles for question generation", file=sys.stderr)

    # 出力先準備
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # resume
    done_ids: set[str] = set()
    if args.resume and args.output.exists():
        with args.output.open(encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("positive_id"):
                        done_ids.add(d["positive_id"])
                except Exception:
                    pass
        print(f"  resume: skip {len(done_ids)} already-done positive_ids", file=sys.stderr)

    client = _gemini_client()

    n_triples = 0
    n_done = 0
    n_failed = 0
    n_skipped = 0

    mode = "a" if args.resume and args.output.exists() else "w"
    with args.output.open(mode, encoding="utf-8") as out_f:
        for cnt, pos_idx in enumerate(candidates, 1):
            rec = all_records[pos_idx]
            aid = rec.get("article_id") or rec.get("chunk_id") or ""
            if not aid:
                continue
            if aid in done_ids:
                n_skipped += 1
                continue

            text = rec.get("text", "")
            law_name = rec.get("law_name_ja", "")

            print(
                f"  [{cnt}/{len(candidates)}] {aid} ({law_name}, {len(text)} chars) ...",
                file=sys.stderr,
            )

            questions = generate_questions(
                client=client,
                model=args.model,
                law_name=law_name,
                text=text,
                n=args.questions_per_article,
            )
            if not questions:
                n_failed += 1
                continue

            neg_candidates = find_hard_negatives_per_idx(pos_idx, matrix, top_k=10)
            random.shuffle(neg_candidates)
            chosen_negs = neg_candidates[: args.hard_negatives_per_positive]

            for q in questions:
                for neg_idx in chosen_negs:
                    neg_rec = all_records_by_idx[neg_idx]
                    triple = {
                        "query": q,
                        "positive_id": aid,
                        "negative_id": neg_rec.get("article_id") or neg_rec.get("chunk_id") or "",
                        "positive_text": text,
                        "negative_text": neg_rec.get("text", ""),
                        "law_name_ja": law_name,
                        "negative_law_name_ja": neg_rec.get("law_name_ja", ""),
                    }
                    out_f.write(json.dumps(triple, ensure_ascii=False) + "\n")
                    n_triples += 1

            out_f.flush()
            n_done += 1
            time.sleep(args.sleep_between_articles)

    print("\n=== DONE ===", file=sys.stderr)
    print(f"  articles processed: {n_done}", file=sys.stderr)
    print(f"  articles failed:    {n_failed}", file=sys.stderr)
    print(f"  articles skipped:   {n_skipped}", file=sys.stderr)
    print(f"  triples written:    {n_triples}", file=sys.stderr)
    print(f"  output:             {args.output}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

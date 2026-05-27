#!/usr/bin/env python3
"""train-reranker.py -- JuriCode-JP 専用 reranker を fine-tune.

generate-training-data.py が生成した triple jsonl を使い、
既存の Japanese cross-encoder reranker を継続学習する.

使い方:
  python tools/finetune/train-reranker.py \\
    --training-data data/training/2026-05-21-reranker-train.jsonl \\
    --base-model /home/masa/models/japanese-reranker-cross-encoder-small-v1 \\
    --output-dir ~/models/juricode-reranker-v0.1 \\
    --epochs 2 \\
    --batch-size 16 \\
    --learning-rate 2e-5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--training-data", type=Path, required=True)
    parser.add_argument(
        "--base-model", required=True, help="local path or HF model id of base cross-encoder"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--limit", type=int, default=None, help="limit number of training examples (debug)"
    )
    args = parser.parse_args()

    # Import inside main so script can show --help without heavy deps
    from sentence_transformers import CrossEncoder, InputExample

    try:
        from sentence_transformers.cross_encoder.evaluation import (
            CrossEncoderClassificationEvaluator as _Eval,
        )
    except ImportError:
        from sentence_transformers.cross_encoder.evaluation import (
            CEBinaryClassificationEvaluator as _Eval,
        )
    from torch.utils.data import DataLoader

    print(f"=== Loading training data from {args.training_data} ===", file=sys.stderr)
    examples: list = []
    with args.training_data.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            q = d.get("query")
            pos = d.get("positive_text")
            neg = d.get("negative_text")
            if not (q and pos and neg):
                continue
            # positive: label 1
            examples.append(InputExample(texts=[q, pos], label=1.0))
            # negative: label 0
            examples.append(InputExample(texts=[q, neg], label=0.0))

    if args.limit:
        examples = examples[: args.limit]
    print(f"  loaded {len(examples)} examples (positive + negative pairs)", file=sys.stderr)

    if not examples:
        sys.exit("ERROR: no training examples loaded")

    # 8:2 split
    import random

    random.seed(args.seed)
    random.shuffle(examples)
    split = int(len(examples) * 0.9)
    train_examples = examples[:split]
    eval_examples = examples[split:]
    print(f"  train: {len(train_examples)}, eval: {len(eval_examples)}", file=sys.stderr)

    print(f"=== Loading base model from {args.base_model} ===", file=sys.stderr)
    model = CrossEncoder(
        args.base_model, num_labels=1, device=args.device, max_length=args.max_length
    )
    print(f"  device: {model.model.device}", file=sys.stderr)

    train_dl = DataLoader(train_examples, shuffle=True, batch_size=args.batch_size)

    eval_q = [(ex.texts[0], ex.texts[1]) for ex in eval_examples]
    eval_labels = [int(ex.label) for ex in eval_examples]
    evaluator = _Eval(
        sentence_pairs=eval_q,
        labels=eval_labels,
        name="dev",
    )

    args.output_dir.expanduser().mkdir(parents=True, exist_ok=True)
    output_path = str(args.output_dir.expanduser())

    print(
        f"=== Training: epochs={args.epochs}, batch={args.batch_size}, lr={args.learning_rate} ===",
        file=sys.stderr,
    )
    model.fit(
        train_dataloader=train_dl,
        epochs=args.epochs,
        evaluator=evaluator,
        evaluation_steps=max(1, len(train_dl) // 4),
        warmup_steps=int(len(train_dl) * args.epochs * args.warmup_ratio),
        optimizer_params={"lr": args.learning_rate},
        output_path=output_path,
        show_progress_bar=True,
    )

    print(f"\n=== Saved model to {output_path} ===", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

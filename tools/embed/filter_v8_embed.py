#!/usr/bin/env python3
"""filter_v8_embed.py -- Track A / A2: embed 対象の事前フィルタ (embed_skip 除外).

Why (the A2 design brief §3.1):
`embed.py` は全行の `text` を埋め込む (`embed_skip` を解さない)。よって A2 で事前に
`build/corpus-v8.jsonl` から **`embed_skip != true` かつ text 非空** の行のみを
`build/corpus-v8-embed.jsonl` に書き出す。**この embed корпус が dense 索引と (A3 の)
BM25 の共通コーパス**ゆえ、再現可能な生成器として commit する (inline one-off にしない)。

除外内訳を報告し、出力の chunk_id 全ユニーク・空 text 0 を assert する (D-1/KFS の漏れ検知)。
空 text 行は本来 KFS マップ漏れの検知点だが、実データでは消費税法基本通達に text 空の
tsutatsu 生チャンクが4件存在する (source 由来・pre-existing)。これらは embed 不能ゆえ除外し、
除外を報告する (自己申告せず件数で示す)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "tools" / "shared" / "src"))

from juricode_shared.safe_write import safe_write_text  # noqa: E402


def filter_embed_rows(records: list[dict]) -> tuple[list[dict], dict]:
    """embed_skip / 空 text を除外し、(kept, report) を返す (純ロジック・テスト対象).

    Why: 除外理由を skip(rollup) と empty(text 空) に分けて数える。kept の chunk_id 全ユニーク
    を assert し、非ユニークなら D-1 漏れとして例外 (embed の resume が誤 skip するため)。
    """
    kept: list[dict] = []
    skipped_embed_skip = 0
    excluded_empty: list[str] = []
    for r in records:
        if r.get("embed_skip"):
            skipped_embed_skip += 1
            continue
        if not (r.get("text") or "").strip():
            excluded_empty.append(r.get("chunk_id"))
            continue
        kept.append(r)

    ids = [r["chunk_id"] for r in kept]
    if len(ids) != len(set(ids)):
        raise ValueError(f"chunk_id not unique in embed corpus ({len(ids) - len(set(ids))} dup)")

    report = {
        "n_input": len(records),
        "n_embed_target": len(kept),
        "skipped_embed_skip": skipped_embed_skip,
        "excluded_empty_text": len(excluded_empty),
        "excluded_empty_ids": excluded_empty,
    }
    return kept, report


def main() -> int:
    ap = argparse.ArgumentParser(description="A2: filter corpus-v8.jsonl to embed-ready corpus.")
    ap.add_argument("--input", type=Path, default=_REPO / "build" / "corpus-v8.jsonl")
    ap.add_argument("--output", type=Path, default=_REPO / "build" / "corpus-v8-embed.jsonl")
    args = ap.parse_args()

    records = [
        json.loads(ln) for ln in args.input.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    kept, report = filter_embed_rows(records)

    lines = [json.dumps(r, ensure_ascii=False) for r in kept]
    safe_write_text(args.output, "\n".join(lines) + "\n", newline="\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"output -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

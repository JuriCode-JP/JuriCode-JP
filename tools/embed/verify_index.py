#!/usr/bin/env python3
"""verify_index.py -- 新しく作った索引の整合を assert する.

Why:
    embed は 1 回で 143,749 件・約 77 分・課金あり。「出来たつもり」で先へ進むと、
    退化ベクトル (all-zero) や行のズレを抱えたまま baseline を測ってしまう。
    索引は作った直後に、**入力コーパスと突き合わせて**検査する。

検査項目:
    T1 行数一致      : .npy の行数 == meta の行数 == 入力 corpus の embed 対象数
    T2 chunk_id 一意 : meta の chunk_id に重複が無い
    T3 chunk_id 対応 : meta の chunk_id 集合 == corpus の embed 対象 chunk_id 集合
    T4 次元          : 3072
    T5 退化ベクトル  : L2 ノルム 0 のベクトルが 0 件 (NaN / Inf も 0 件)
    T6 旧索引不変    : 比較対象の旧索引 (v8b) が embed 実行前と byte 一致
    T7 位置対応      : meta[i].chunk_id == corpus[i].chunk_id (**順序も含めて**)
    T8 ベクトル対応  : 標本を再 embed し、.npy の i 行目との cosine が ~1.0

Why T7 / T8 が要るのか (T1-T6 では **沈黙の破損** を見逃す):
    resume に失敗して「.npy の N 行目のベクトル」と「meta の N 行目の chunk_id」が
    ズレても、行数一致 (T1)・一意性 (T2)・集合一致 (T3) は **全部通る**。
    retrieval は無関係な条文を返すのに、数値上は正常に見える。
    集合の一致は順序を見ておらず、meta と npy の対応は誰も検算していなかった
    ----「検査範囲の外にあるものは、永久に見えない」の同型。
    T8 は resume の **境界** (checkpoint 行の前後) を重点サンプルする。
    実装ミスは境界で出るため。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", required=True, help="build/embeddings/<name> (拡張子なし)")
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--dim", type=int, default=3072)
    ap.add_argument("--prev-index", help="不変であるべき旧索引 (拡張子なし)")
    ap.add_argument("--prev-sha256", type=Path, help="旧索引の embed 実行前 sha256 一覧")
    ap.add_argument(
        "--resume-boundary",
        type=int,
        default=None,
        help="resume した checkpoint 行番号 (T8 でこの前後 +-5 行を重点サンプルする)",
    )
    ap.add_argument("--probe-samples", type=int, default=10, help="T8 の再 embed サンプル数")
    ap.add_argument("--text-field", default="embed_text")
    ap.add_argument("--no-probe", action="store_true", help="T8 をスキップ (API を呼ばない)")
    args = ap.parse_args()

    base = Path(args.index)
    vecs = np.load(Path(str(base) + ".npy"), mmap_mode="r")
    meta = [json.loads(ln) for ln in Path(str(base) + ".meta.jsonl").open(encoding="utf-8")]

    # 入力の chunk_id を **順序どおり** に読む (T7 が必要とする)。
    in_ids: list[str] = []
    in_texts: list[str] = []
    with args.corpus.open(encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            if r.get("embed_skip"):
                continue
            in_ids.append(r["chunk_id"])
            in_texts.append(r.get(args.text_field) or "")
    expected = set(in_ids)

    fails: list[str] = []
    ok: list[str] = []

    n = vecs.shape[0]
    if n == len(meta) == len(expected):
        ok.append(
            f"T1 行数一致            : {n:,} == meta {len(meta):,} == corpus {len(expected):,}"
        )
    else:
        fails.append(
            f"T1 行数不一致          : npy {n:,} / meta {len(meta):,} / corpus {len(expected):,}"
        )

    ids = [m["chunk_id"] for m in meta]
    dups = len(ids) - len(set(ids))
    (ok if dups == 0 else fails).append(f"T2 chunk_id 重複       : {dups}")

    missing = expected - set(ids)
    extra = set(ids) - expected
    if not missing and not extra:
        ok.append("T3 chunk_id 対応       : corpus と完全一致")
    else:
        fails.append(f"T3 chunk_id 不整合     : 欠落 {len(missing)} / 余分 {len(extra)}")

    dim = vecs.shape[1]
    (ok if dim == args.dim else fails).append(f"T4 次元                : {dim}")

    norms = np.linalg.norm(np.asarray(vecs, dtype=np.float32), axis=1)
    degenerate = int((norms == 0).sum())
    nonfinite = int((~np.isfinite(norms)).sum())
    if degenerate == 0 and nonfinite == 0:
        ok.append(f"T5 退化ベクトル        : 0 (L2 min {norms.min():.4f} / max {norms.max():.4f})")
    else:
        fails.append(f"T5 退化ベクトル        : L2==0 {degenerate} / 非有限 {nonfinite}")

    # ---- T7: 位置対応 (行数一致と一意性だけでは、ズレは検出できない) ----------
    # resume が失敗して .npy の i 行目と .meta.jsonl の i 行目が別物になっていても、
    # T1/T2/T3 は全部通る。retrieval が無関係な条文を返すのに数値上は正常に見える
    # (沈黙の破損)。ゆえに **順序も含めた** 一致を assert する。
    meta_ids = [m["chunk_id"] for m in meta]
    if len(meta_ids) == len(in_ids):
        off = [i for i, (a, b) in enumerate(zip(meta_ids, in_ids, strict=True)) if a != b]
        if not off:
            ok.append(f"T7 位置対応 (順序)     : meta[i] == corpus[i] 全 {len(in_ids):,} 行")
        else:
            fails.append(
                f"T7 位置ズレ            : {len(off)} 行 (最初は {off[0]}: "
                f"meta={meta_ids[off[0]]} / corpus={in_ids[off[0]]})"
            )
    else:
        fails.append("T7 位置対応            : 行数が違うので比較不能")

    # ---- T8: ベクトルと meta の対応を、実際に embed し直して確かめる ------------
    # resume の実装ミスは **境界** で出る。checkpoint 前後を重点的に見る。
    if not args.no_probe and len(meta_ids) == len(in_ids) and len(in_ids) > 0:
        rng = np.random.default_rng(20260714)  # seed 固定 (再現可能にする)
        idx: list[int] = []
        if args.resume_boundary:
            b = args.resume_boundary
            idx += [i for i in range(b - 5, b + 6) if 0 <= i < len(in_ids)]
        n_rand = max(0, args.probe_samples - len(idx))
        if n_rand:
            idx += [int(i) for i in rng.choice(len(in_ids), size=n_rand, replace=False)]
        idx = sorted(set(idx))

        try:
            from eval_branch_item import embed_queries  # 同ディレクトリ

            probe = embed_queries([in_texts[i] for i in idx], task_type="RETRIEVAL_DOCUMENT")
            worst = 1.0
            worst_i = -1
            for k, i in enumerate(idx):
                v = np.asarray(vecs[i], dtype=np.float32)
                p = probe[k]
                cos = float(v @ p / (np.linalg.norm(v) * np.linalg.norm(p)))
                if cos < worst:
                    worst, worst_i = cos, i
            if worst >= 0.98:
                ok.append(
                    f"T8 ベクトル対応 (再embed): {len(idx)} 件, cosine 最小 {worst:.4f} "
                    f"(境界 {args.resume_boundary or '-'} 前後を含む)"
                )
            else:
                fails.append(
                    f"T8 ベクトルと meta がズレている: 行 {worst_i} の cosine {worst:.4f} "
                    f"(chunk_id={meta_ids[worst_i]})"
                )
        except Exception as e:
            fails.append(f"T8 実行不能 (確認できていない -- 通ったことにしない): {e}")

    if args.prev_index and args.prev_sha256 and args.prev_sha256.exists():
        before = {}
        for ln in args.prev_sha256.read_text(encoding="utf-8").splitlines():
            parts = ln.split()
            if len(parts) >= 2:
                before[Path(parts[-1].replace("\\", "/")).name] = parts[0]
        changed = []
        for suf in (".npy", ".meta.jsonl", ".vec.pkl", ".vec.json"):
            p = Path(str(args.prev_index) + suf)
            name = p.name
            if name in before and _sha256(p)[: len(before[name])] != before[name]:
                changed.append(name)
        if changed:
            fails.append(f"T6 旧索引が改変された  : {changed}")
        else:
            ok.append(f"T6 旧索引不変          : {Path(args.prev_index).name} は byte 一致")

    for line in ok:
        print(f"  OK   {line}")
    for line in fails:
        print(f"  FAIL {line}", file=sys.stderr)
    print(f"\n=== index verify: {len(ok)} passed / {len(fails)} failed ===")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

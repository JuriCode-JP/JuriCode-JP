#!/usr/bin/env python3
"""build_v8_corpus.py -- Track A / A1: v8 corpus merge (layer/corpus_group/KFS/context_prefix).

Why (the design brief / parent plan §0.9 locked design rulings):
v7 索引未反映の新規コーパス (租特法・通達・タックスアンサー・KFS 裁決) を、the locked design rulings
(K-1/S-1/C-1/A-1/D-1) に従って layer/corpus_group 付与・KFS マップ・単層 context_prefix・
token 超過処理・chunk_id 一意化を施し、新規 `build/corpus-v8.jsonl` に merge する。**v7
成果物 (corpus-v0.2.jsonl / embeddings/v0.2-aug-v7-*) は非改変**。canonical data/ 非改変。

裁定 (§0.9・機械実装・設計判断しない):
  - A-1: 租特法本法=layer=statute+corpus_group=sochi / 令規=enforcement+sochi。
  - K-1: KFS text=case_name_ja+summary_ja, layer/corpus_group=ruling。kfs-hojin 13件のみ。
  - C-1: 項柱書(hashira)->号(kou) の単層のみ。原文 rewrite 禁止 = 別フィールド context_prefix。
  - S-1: rollup系=embed_skip=true。非rollup 超過=実トークン再判定後に overlap sub-chunk。
  - D-1: chunk_id 一意化 (衝突に決定論サフィックス, chunk_id_orig 保持, 重複0 assert)。

実装ノート: v7 corpus は text==text_raw==原文 (実測) ゆえ v8 も text=text_raw=原文
(flatten_chunk(augment=False) 流用)。ラベル/柱書の embed 折込は A3 で確定 = A1 は
context_prefix を別フィールドで保持するだけ (§3.3)。build-v0.2-corpus.py の CI-critical な
v7 パスを壊さないため本 module は独立 (flatten_chunk / build_law_to_phase は importlib 流用)。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "tools" / "shared" / "src"))

from juricode_shared.safe_write import safe_write_text  # noqa: E402

CHUNKS_SUFFIX = ".chunks.jsonl"
KFS_SUFFIX = ".saiketsu.jsonl"
ROLLUP_SEGMENTS = frozenset({"rollup", "supplproviso_rollup"})

# S-1: 実トークンで再判定する候補の char 事前フィルタ。日本語は概ね tokens <= chars ゆえ
# char <= しきい値なら 2048 token 超は起きない (安全側)。しきい値超のみ count_tokens する。
CHAR_TOKEN_PREFILTER = 1800
MAX_TOKENS = 2048
TARGET_TOKENS = 1800  # sub-chunk 1 片の目標 (2048 の安全マージン)
OVERLAP_RATIO = 0.10


def _load_bv02():
    """build-v0.2-corpus.py (ハイフン名) を importlib で読み flatten_chunk 等を流用."""
    path = _HERE / "build-v0.2-corpus.py"
    spec = importlib.util.spec_from_file_location("_bv02_corpus", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bv02_corpus"] = mod
    spec.loader.exec_module(mod)
    return mod


# =====================================================
# 純ロジック (テスト対象)
# =====================================================


def v8_layer_group(dir_name: str, segment_type: str | None, *, is_kfs: bool) -> tuple[str, str]:
    """(layer, corpus_group) を導出する (A-1 裁定).

    Why: 粗い layer (boost 用) と細かい corpus_group (filter 用) の2軸 (§3.1)。租特法本法は
    法令本体と同構造ゆえ layer=statute だが corpus_group=sochi で filter 可能にする (A-1)。
    """
    if is_kfs:
        return "ruling", "ruling"
    if segment_type == "taxanswer" or dir_name.endswith("-taxanswer"):
        return "taxanswer", "taxanswer"
    if segment_type == "tsutatsu" or dir_name.endswith("-tsutatsu"):
        return "tsutatsu", "tsutatsu"
    if dir_name == "sochi-hou":
        return "statute", "sochi"
    if dir_name in ("sochi-hou-shikkourei", "sochi-hou-shikoukisoku"):
        return "enforcement", "sochi"
    if any(x in dir_name for x in ("shikkourei", "shikoukisoku", "furei")):
        return "enforcement", "enforcement"
    return "statute", "statute"


def kfs_map_text(record: dict) -> str:
    """KFS 検索 text = case_name_ja + summary_ja を結合 (K-1)."""
    name = (record.get("case_name_ja") or "").strip()
    summary = (record.get("summary_ja") or "").strip()
    return "\n".join(p for p in (name, summary) if p)


_KFS_META_KEYS = (
    "case_id",
    "case_type",
    "decision_date",
    "url",
    "relevance",
    "source_license",
    "summary_source",
    "case_name_ja",
    "summary_ja",
    "saiketsu_ref",
    "issue_code",
    "tax_item",
    "tags",
)


def kfs_to_v8(record: dict) -> dict | None:
    """KFS 生レコードを v8 flat record にマップする。text 空なら None (除外・K-1).

    Why: KFS は text 不在ゆえ case_name_ja+summary_ja を検索 text にマップ (K-1)。真に空の
    もののみ除外 (一律除外は裁決全消失ゆえ禁止)。出典メタは retrieve 表示用に保持。
    """
    text = kfs_map_text(record)
    if not text.strip():
        return None
    flat = {
        "chunk_id": record["case_id"],
        "chunk_id_orig": record["case_id"],
        "segment_type": "ruling",
        "layer": "ruling",
        "corpus_group": "ruling",
        "text": text,
        "text_raw": text,
        "context_prefix": "",
        "embed_skip": False,
        "law_name_ja": record.get("case_name_ja"),
    }
    for k in _KFS_META_KEYS:
        if k in record:
            flat[k] = record[k]
    return flat


def build_hashira_map(chunks: list[dict]) -> dict[tuple, str]:
    """1 ファイル内の (article_id, paragraph_number) -> 項柱書(hashira) text を作る (C-1).

    Why: 号(kou) の context_prefix は同一 (条, 項) の hashira segment の本文。ファイル内
    (= 同一条) で完結するため per-file マップで足りる。
    """
    hmap: dict[tuple, str] = {}
    for c in chunks:
        if c.get("segment_type") == "hashira":
            key = (c.get("article_id"), c.get("paragraph_number"))
            hmap[key] = c.get("text") or ""
    return hmap


def context_prefix_for(chunk: dict, hashira_map: dict[tuple, str]) -> str:
    """号(kou) に対し同 (条,項) の項柱書を返す (単層・C-1)。非号や柱書不在は空."""
    if chunk.get("segment_type") != "kou":
        return ""
    key = (chunk.get("article_id"), chunk.get("paragraph_number"))
    return hashira_map.get(key, "")


def char_slices_with_overlap(text: str, n: int, overlap_ratio: float) -> list[str]:
    """text を n 個の連続 char スライス (overlap 付) に分割する (S-1 sub-chunk).

    Why: 実トークンで n = ceil(tokens/target) を決めた上で、意味区切りを跨ぐ overlap を
    付けて分割 (pooling 禁止・各片は原文の連続部分文字列 = 文字 rewrite なし)。
    """
    if n <= 1 or not text:
        return [text]
    base = math.ceil(len(text) / n)
    ov = int(base * overlap_ratio)
    slices = []
    start = 0
    while start < len(text):
        end = min(len(text), start + base + ov)
        slices.append(text[start:end])
        if end >= len(text):
            break
        start += base
    return slices


def plan_subchunks(text: str, token_count_fn) -> list[str]:
    """非rollup チャンクを実トークンで再判定し、2048 token 超のみ overlap 分割する (S-1).

    Why: char>プレフィルタ のみ count_tokens を呼ぶ (API 節約)。<=MAX なら単一のまま。
    token_count_fn はテストで注入可能 (実 gemini は CLI で束縛)。
    """
    if len(text) <= CHAR_TOKEN_PREFILTER:
        return [text]
    ntok = token_count_fn(text)
    if ntok <= MAX_TOKENS:
        return [text]
    n = math.ceil(ntok / TARGET_TOKENS)
    return char_slices_with_overlap(text, n, OVERLAP_RATIO)


def uniqueize_id(cid: str, seen: Counter) -> str:
    """chunk_id 衝突に決定論サフィックス (#2,#3,...) を付与して一意化する (D-1).

    Why: 附則の施行日項目が art-1-p1-kou-N 名前空間に誤集約され衝突 (v7 既存)。出現順で
    安定サフィックスを付け、chunk_id 全ユニークを保証する (根本 parser 修正は D-1-root 別track)。
    """
    seen[cid] += 1
    if seen[cid] == 1:
        return cid
    return f"{cid}#{seen[cid]}"


# =====================================================
# ビルド
# =====================================================


def _iter_files(chunks_dir: Path) -> list[tuple[Path, bool]]:
    files: list[tuple[Path, bool]] = []
    for p in sorted(chunks_dir.rglob("*.jsonl")):
        if "backup" in str(p).lower():
            continue
        if p.name.endswith(KFS_SUFFIX):
            files.append((p, True))
        elif p.name.endswith(CHUNKS_SUFFIX):
            files.append((p, False))
    return files


def _make_token_counter():
    """実 gemini-embedding-001 の count_tokens を返す (lazy import・CLI 用)."""
    import os

    from google import genai

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set for token counting")
    client = genai.Client(api_key=key)

    def _count(text: str) -> int:
        return client.models.count_tokens(model="gemini-embedding-001", contents=text).total_tokens

    return _count


def build(
    chunks_dir: Path,
    data_dir: Path,
    output: Path,
    token_count_fn,
) -> dict:
    """v8 corpus を build/corpus-v8.jsonl に merge し、実測サマリを返す (§3.1-3.6)."""
    bv = _load_bv02()
    law_to_phase = bv.build_law_to_phase(data_dir)
    # Resolve captions via the SAME path v7 used (build-v0.2-corpus.build_article_to_caption),
    # so embed_text reproduces the v7 augmented recipe byte-for-byte (parity gate below).
    article_to_caption = bv.build_article_to_caption(data_dir)

    files = _iter_files(chunks_dir)
    seen_ids: Counter = Counter()
    records: list[dict] = []

    summary = {
        "n_input_files": len(files),
        "layer_counts": Counter(),
        "corpus_group_counts": Counter(),
        "kfs_records": 0,
        "kfs_excluded_empty": 0,
        "context_prefix_assigned": 0,
        "embed_skip_rollup": 0,
        "subchunked_parents": 0,
        "subchunks_emitted": 0,
        "id_collisions_uniqueized": 0,
        "text_unchanged_checked": 0,
        "embed_text_assigned": 0,
        "embed_text_empty": 0,
    }

    for path, is_kfs in files:
        group = path.parent.name
        raw_records = [
            json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]

        if is_kfs:
            for rec in raw_records:
                flat = kfs_to_v8(rec)
                if flat is None:
                    summary["kfs_excluded_empty"] += 1
                    continue
                flat["chunk_id"] = uniqueize_id(flat["chunk_id"], seen_ids)
                # K-1: KFS retrieval text (case_name+summary) through the SAME augment recipe.
                flat["embed_text"] = bv.make_augmented_text(flat, None)
                records.append(flat)
                summary["kfs_records"] += 1
                summary["layer_counts"]["ruling"] += 1
                summary["corpus_group_counts"]["ruling"] += 1
            continue

        phase = _phase_for(path, group, law_to_phase, bv)
        hashira_map = build_hashira_map(raw_records)

        for chunk in raw_records:
            flat = bv.flatten_chunk(chunk, phase, False, {})  # augment=False -> text=text_raw=原文
            seg = flat.get("segment_type")
            layer, cgroup = v8_layer_group(group, seg, is_kfs=False)
            flat["layer"] = layer
            flat["corpus_group"] = cgroup
            summary["layer_counts"][layer] += 1
            summary["corpus_group_counts"][cgroup] += 1

            cprefix = context_prefix_for(chunk, hashira_map)
            flat["context_prefix"] = cprefix
            if cprefix:
                summary["context_prefix_assigned"] += 1

            orig_id = flat["chunk_id"]
            flat["chunk_id_orig"] = orig_id
            base_text = flat.get("text") or ""
            # v7 parity: embed_text = augmented recipe (law name / article no / caption / labels)
            # on the RAW chunk, exactly as build-v0.2-corpus.flatten_chunk(augment=True) did.
            caption = article_to_caption.get(flat.get("article_id"))

            if seg in ROLLUP_SEGMENTS:
                # S-1: rollup系は embed 対象外 (粒度チャンクが内容保持)
                flat["embed_skip"] = True
                flat["embed_text"] = bv.make_augmented_text(chunk, caption)
                flat["chunk_id"] = uniqueize_id(orig_id, seen_ids)
                records.append(flat)
                summary["embed_skip_rollup"] += 1
                summary["embed_text_assigned"] += 1
                continue

            # S-1: 非rollup は実トークンで再判定し、超過のみ overlap sub-chunk
            slices = plan_subchunks(base_text, token_count_fn) if base_text.strip() else [base_text]
            if len(slices) == 1:
                flat["embed_skip"] = False
                flat["embed_text"] = bv.make_augmented_text(chunk, caption)
                flat["chunk_id"] = uniqueize_id(orig_id, seen_ids)
                records.append(flat)
                summary["text_unchanged_checked"] += 1
                summary["embed_text_assigned"] += 1
            else:
                summary["subchunked_parents"] += 1
                for i, piece in enumerate(slices, 1):
                    sub = dict(flat)
                    sub["text"] = piece
                    sub["text_raw"] = piece
                    # Prefix the SAME augmented head onto each verbatim sub-slice.
                    sub["embed_text"] = bv.make_augmented_text({**chunk, "text": piece}, caption)
                    sub["embed_skip"] = False
                    sub["subchunk_of"] = orig_id
                    sub["subchunk_index"] = i
                    sub["chunk_id"] = uniqueize_id(f"{orig_id}-sub{i}", seen_ids)
                    records.append(sub)
                    summary["subchunks_emitted"] += 1
                    summary["embed_text_assigned"] += 1

    summary["id_collisions_uniqueized"] = sum(1 for cid, n in seen_ids.items() if n > 1)
    summary["embed_text_empty"] = sum(1 for r in records if not (r.get("embed_text") or "").strip())

    # write
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    safe_write_text(output, "\n".join(lines) + "\n", newline="\n")

    summary["n_records_out"] = len(records)
    summary["layer_counts"] = dict(summary["layer_counts"])
    summary["corpus_group_counts"] = dict(summary["corpus_group_counts"])
    return summary


def _phase_for(path: Path, group: str, law_to_phase: dict, bv) -> str:
    if path.name.endswith(".tsutatsu.chunks.jsonl"):
        return "tsutatsu"
    if path.name.endswith(".taxanswer.chunks.jsonl"):
        return "taxanswer"
    return law_to_phase.get(group, "unknown")


def verify_parity(v8_path: Path, v6_path: Path) -> dict:
    """v7 recipe parity gate: v8 embed_text must equal the v7 augmented text.

    Why: the -20pt A3-M regression was caused by v8 embedding raw body only. This asserts
    the restored embed_text reproduces v7's augmented recipe byte-for-byte on the shared set
    (matched by chunk_id_orig <-> v6 chunk_id). Sub-chunks are a v8-only transformation and
    are excluded; collisions are handled dup-safe (v6 keeps a SET of texts per id). Any
    honbun mismatch => recipe drift => STOP (return with n_mismatch > 0).
    """
    v6_texts: dict[str, set[str]] = {}
    with v6_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            cid = r.get("chunk_id")
            if cid is not None:
                v6_texts.setdefault(cid, set()).add(r.get("text") or "")

    n_common = 0
    n_mismatch = 0
    examples: list[dict] = []
    with v8_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("subchunk_of"):
                continue  # v8-only split, no v7 counterpart
            orig = r.get("chunk_id_orig")
            if orig not in v6_texts:
                continue  # new corpus (sochi/KFS) or absent in v7 -> not a parity case
            n_common += 1
            if (r.get("embed_text") or "") not in v6_texts[orig]:
                n_mismatch += 1
                if len(examples) < 8:
                    examples.append(
                        {
                            "chunk_id": r.get("chunk_id"),
                            "chunk_id_orig": orig,
                            "v8_embed_text": (r.get("embed_text") or "")[:160],
                            "v7_text_sample": next(iter(v6_texts[orig]))[:160],
                        }
                    )
    return {"n_common": n_common, "n_mismatch": n_mismatch, "examples": examples}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Track A / A1: build v8 corpus (layer/corpus_group/KFS/context_prefix)."
    )
    ap.add_argument("--chunks-dir", type=Path, default=_REPO / "build" / "chunks")
    ap.add_argument("--data-dir", type=Path, default=_REPO / "data" / "v0.2")
    ap.add_argument("--output", type=Path, default=_REPO / "build" / "corpus-v8.jsonl")
    ap.add_argument(
        "--no-token-api",
        action="store_true",
        help="disable real gemini token counting (char-prefilter only; skips sub-chunking)",
    )
    ap.add_argument(
        "--verify-parity",
        type=Path,
        default=None,
        help="after build, assert embed_text == v7 augmented text on the shared set "
        "(pass the v7 augmented corpus, e.g. build/corpus-v0.2-augmented-v6.jsonl)",
    )
    args = ap.parse_args()

    if not args.chunks_dir.exists():
        print(f"ERROR: chunks dir not found: {args.chunks_dir}", file=sys.stderr)
        return 1

    if args.no_token_api:
        # char<=プレフィルタ は既に単一。超過は「不明ゆえ分割せず」= sub-chunk 抑止 (要 --token-api で本番)。
        def token_count_fn(_text: str) -> int:
            return 0
    else:
        token_count_fn = _make_token_counter()

    summary = build(args.chunks_dir, args.data_dir, args.output, token_count_fn)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"output -> {args.output.relative_to(_REPO)}")

    if args.verify_parity is not None:
        if not args.verify_parity.exists():
            print(f"ERROR: v7 parity corpus not found: {args.verify_parity}", file=sys.stderr)
            return 1
        parity = verify_parity(args.output, args.verify_parity)
        print("parity: " + json.dumps({k: parity[k] for k in ("n_common", "n_mismatch")}))
        if parity["n_mismatch"] > 0:
            print("PARITY FAIL: embed_text != v7 augmented text (recipe drift):", file=sys.stderr)
            for ex in parity["examples"]:
                print(f"  {ex['chunk_id']}: v8={ex['v8_embed_text']!r}", file=sys.stderr)
                print(f"      v7={ex['v7_text_sample']!r}", file=sys.stderr)
            return 1
        print(f"parity OK: {parity['n_common']} shared chunks, 0 mismatch")

    return 0


if __name__ == "__main__":
    sys.exit(main())

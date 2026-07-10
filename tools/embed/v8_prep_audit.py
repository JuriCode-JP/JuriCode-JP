#!/usr/bin/env python3
"""v8_prep_audit.py -- Track A / A0 棚卸し監査 (read-only, canonical 非改変).

Why (the A0 audit brief / parent plan):
`build/chunks` に整備済みだが v7 索引未反映の新規コーパス (租特法・通達・タックスアンサー・
KFS 裁決) を、**一切改変せず計測**して `build/v8-prep-report/audit.json` に出力する。数値は
報告のみ = 方針決定 (KFS text マッピング K-1 / token 超過処理 S-1 / 階層結合 C-1 /
sochi layer 種別 A-1) は locked design ruling。本スクリプトは設計判断をしない。

計測項目 (design brief §3.0):
  1. 群別件数表: 法令群 x segment_type x layer 候補。破損 (NUL/空行/二重貼付) 検出 = 0 assert。
  2. KFS スキーマ: kfs-* のキー・text マップ候補・マップ後空レコード数。
  3. token/char 長: 全チャンク (+ KFS マップ後) の文字長、>2048 を種別別・rollup/非rollup 別に。
  4. 階層インベントリ: segment_type 分布、kou 下位細別 (イ/ロ/ハ)、柱書欠落 号/下位数。
  5. sochi(租特法) の segment_type/phase 実態 (A-1 材料)。

**layer は「候補」= the A-1 ruling で確定する**。本監査は候補を機械導出して件数表に出すだけ。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "tools" / "shared" / "src"))

from juricode_shared.safe_write import safe_write_text  # noqa: E402

# gemini-embedding-001 の入力上限に対する char ベースの保守的しきい値。
# design brief の既知値 (taxanswer 149件>2048字 等) が字数基準ゆえ字数で計測 (over-flag 側=安全)。
CHAR_LIMIT = 2048

# 記録ファイルの拡張子。KFS のみ .saiketsu.jsonl、他は .chunks.jsonl。
CHUNKS_SUFFIX = ".chunks.jsonl"
KFS_SUFFIX = ".saiketsu.jsonl"

ROLLUP_SEGMENTS = frozenset({"rollup", "supplproviso_rollup"})


# =====================================================
# 純ロジック (テスト対象)
# =====================================================


def kfs_text(record: dict) -> str:
    """KFS 裁決レコードの検索 text マップ候補 (K-1 既定候補: case_name_ja + summary_ja).

    Why: KFS は `text` を持たない (本文は case_name_ja/summary_ja)。**最終マップは the K-1 ruling**
    だが、A0 では「マップ後に空になるレコード数」を測るため既定候補で仮マップする。
    """
    name = (record.get("case_name_ja") or "").strip()
    summary = (record.get("summary_ja") or "").strip()
    parts = [p for p in (name, summary) if p]
    return "\n".join(parts)


def record_text(record: dict, *, is_kfs: bool) -> str:
    """レコードの検索対象 text を返す (KFS はマップ、他は text フィールド)."""
    if is_kfs:
        return kfs_text(record)
    return record.get("text") or ""


def derive_layer_candidate(dir_name: str, segment_type: str | None, *, is_kfs: bool) -> str:
    """法令群ディレクトリ名 + segment_type から layer 候補を導出する (A-1 で確定).

    Why: 件数表を layer 候補別に出すための機械導出。**確定値域は the A-1 ruling**。sochi(租特法)
    本法は statute/sochi のどちらか未確定ゆえ独立候補 "sochi" として分離し、A-1 の材料にする。
    """
    if is_kfs:
        return "ruling"
    if segment_type == "taxanswer" or dir_name.endswith("-taxanswer"):
        return "taxanswer"
    if segment_type == "tsutatsu" or dir_name.endswith("-tsutatsu"):
        return "tsutatsu"
    # 租特法本法は A-1 未確定 = 独立候補 sochi。施行令/規則は enforcement。
    if dir_name == "sochi-hou":
        return "sochi"
    if any(x in dir_name for x in ("shikkourei", "shikoukisoku", "furei")):
        return "enforcement"
    return "statute"


def detect_line_corruption(raw_line: str) -> str | None:
    """1 行の破損種別を返す (NUL / 二重貼付=結合 JSON)。健全なら None.

    Why: 既知事故 (b) NUL padding / (c) heredoc 二重貼付 を静かに通さない。空行は呼び出し側で
    別途カウントする (ここでは非空行前提)。二重貼付は「1 行に複数 JSON オブジェクト連結」を
    `}{`... のパターンと再パース失敗で近似検出する。
    """
    if "\x00" in raw_line:
        return "nul_byte"
    try:
        json.loads(raw_line)
    except json.JSONDecodeError:
        # 連結 JSON (二重貼付) か真の壊れか区別: '}{' を含めば二重貼付候補。
        if "}{" in raw_line.replace(" ", "").replace("\n", ""):
            return "concatenated_json"
        return "json_decode_error"
    return None


def is_sub_item(chunk_id: str) -> bool:
    """chunk_id が号下位細別 (イ/ロ/ハ = -i/-ro/-ha 断片) かを判定.

    Why: 階層インベントリで kou 配下の下位細別を数える (design brief §3.0.4)。末尾または途中に
    `-i` / `-ro` / `-ha` 断片を持つものを下位細別とみなす。
    """
    for frag in ("i", "ro", "ha"):
        if chunk_id.endswith(f"-{frag}") or f"-{frag}-" in chunk_id:
            return True
    return False


# =====================================================
# 走査
# =====================================================


def iter_record_files(chunks_dir: Path) -> list[tuple[Path, bool]]:
    """記録ファイル (path, is_kfs) を列挙する。backup ディレクトリ / appendix・dry-run は除外.

    Why: 現行 builder は *.chunks.jsonl のみ glob し KFS *.saiketsu.jsonl を取りこぼす。監査は
    両方を対象にする。appendix-*.json / dry-run-*.json は記録でない (中間生成物) ゆえ除外。
    """
    files: list[tuple[Path, bool]] = []
    for p in sorted(chunks_dir.rglob("*.jsonl")):
        if "backup" in str(p).lower():
            continue
        if p.name.endswith(KFS_SUFFIX):
            files.append((p, True))
        elif p.name.endswith(CHUNKS_SUFFIX):
            files.append((p, False))
    return files


def audit(chunks_dir: Path) -> dict:
    """build/chunks を非改変走査し design brief §3.0 の全計測を dict で返す."""
    files = iter_record_files(chunks_dir)

    # 1. 群別件数
    group_seg = defaultdict(Counter)  # group -> segment_type -> n
    group_layer = defaultdict(Counter)  # group -> layer_candidate -> n
    layer_total = Counter()
    seg_total = Counter()

    # 破損
    corruption: list[dict] = []
    total_blank = 0

    # 2. KFS
    kfs_keys = Counter()
    kfs_total = 0
    kfs_empty_after_map = 0
    kfs_by_group = Counter()

    # 3. token/char
    over_limit = []  # {chunk_id, group, segment_type, char_len, is_rollup}
    maxlen_by_rollup = {"rollup": 0, "non_rollup": 0}
    over_counts = {"rollup": Counter(), "non_rollup": Counter()}  # segment_type -> n over

    # 4. 階層
    sub_item_count = 0
    kou_count = 0
    # 柱書欠落判定: article 単位に hashira の有無と kou/sub の有無を集計
    article_has_hashira: dict[str, bool] = defaultdict(bool)
    article_kou_sub_ids: dict[str, list[str]] = defaultdict(list)

    # 5. sochi
    sochi_seg = defaultdict(Counter)  # sochi group -> segment_type -> n
    sochi_phase = defaultdict(Counter)  # sochi group -> phase_category -> n

    # id -> {line_hash: count}: byte 同一二重貼付 (同一 hash 反復) と id 衝突 (同一 id 別内容)
    # を分類するため、id ごとに行内容ハッシュの分布を保持する。
    id_line_hashes: dict[str, Counter] = defaultdict(Counter)
    n_blank_trailing = 0  # EOF 末尾の空行 (良性)
    n_blank_midfile = 0  # 行間の空行 (切断/破損の疑い = a/b/c)

    for path, is_kfs in files:
        group = path.parent.name
        raw = path.read_bytes()
        if b"\x00" in raw:
            corruption.append({"type": "nul_byte_file", "file": str(path.relative_to(_REPO))})
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        # 空行分類: 最終非空行より後ろの空行のみ trailing (良性)、それ以外は mid-file (破損疑い)
        last_nonblank = max((i for i, ln in enumerate(lines) if ln.strip()), default=-1)
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                total_blank += 1
                if (lineno - 1) > last_nonblank:
                    n_blank_trailing += 1
                else:
                    n_blank_midfile += 1
                    corruption.append(
                        {
                            "type": "midfile_blank",
                            "file": str(path.relative_to(_REPO)),
                            "line": lineno,
                        }
                    )
                continue
            corr = detect_line_corruption(line)
            if corr:
                corruption.append(
                    {"type": corr, "file": str(path.relative_to(_REPO)), "line": lineno}
                )
                continue
            rec = json.loads(line)
            cid = rec.get("id") or rec.get("case_id") or f"{group}:L{lineno}"
            id_line_hashes[cid][hashlib.sha256(line.encode("utf-8")).hexdigest()] += 1
            seg = rec.get("segment_type")
            layer = derive_layer_candidate(group, seg, is_kfs=is_kfs)

            group_seg[group][seg or ("_kfs" if is_kfs else "None")] += 1
            group_layer[group][layer] += 1
            layer_total[layer] += 1
            seg_total[seg or ("_kfs" if is_kfs else "None")] += 1

            body = record_text(rec, is_kfs=is_kfs)
            clen = len(body)
            rollup_key = "rollup" if seg in ROLLUP_SEGMENTS else "non_rollup"
            if clen > maxlen_by_rollup[rollup_key]:
                maxlen_by_rollup[rollup_key] = clen
            if clen > CHAR_LIMIT:
                over_counts[rollup_key][seg or "_kfs"] += 1
                over_limit.append(
                    {
                        "chunk_id": cid,
                        "group": group,
                        "segment_type": seg,
                        "char_len": clen,
                        "is_rollup": rollup_key == "rollup",
                    }
                )

            if is_kfs:
                kfs_total += 1
                kfs_by_group[group] += 1
                for k in rec:
                    kfs_keys[k] += 1
                if not body.strip():
                    kfs_empty_after_map += 1

            # 階層 (本則 article 系のみ)
            aid = rec.get("article_id")
            if seg == "hashira" and aid:
                article_has_hashira[aid] = True
            if seg == "kou":
                kou_count += 1
                if aid:
                    article_kou_sub_ids[aid].append(cid)
            if is_sub_item(cid):
                sub_item_count += 1
                if aid:
                    article_kou_sub_ids[aid].append(cid)

            # sochi
            if group.startswith("sochi"):
                sochi_seg[group][seg or "None"] += 1
                sochi_phase[group][str(rec.get("phase_category"))] += 1

    # 柱書欠落: hashira を持たない article に属する kou/sub チャンク数
    kou_sub_without_hashira = sum(
        len(ids) for aid, ids in article_kou_sub_ids.items() if not article_has_hashira.get(aid)
    )
    articles_without_hashira = sum(
        1 for aid in article_kou_sub_ids if not article_has_hashira.get(aid)
    )

    # 重複 id の分類:
    #   - 単一 hash が複数回      = byte 同一二重貼付 (double-paste / 既知事故 c)
    #   - 同一 id に複数 hash     = id 衝突 (同一 chunk_id に別内容 = chunker の id 非一意)
    byte_identical_dup = []  # {chunk_id, count}
    id_collision = []  # {chunk_id, occurrences, distinct}
    for cid, hashes in id_line_hashes.items():
        occ = sum(hashes.values())
        distinct = len(hashes)
        if distinct > 1:
            id_collision.append({"chunk_id": cid, "occurrences": occ, "distinct": distinct})
        elif occ > 1:
            byte_identical_dup.append({"chunk_id": cid, "count": occ})
    for d in byte_identical_dup:
        corruption.append({"type": "byte_identical_dup", **d})

    total_records = sum(seg_total.values())

    return {
        "chunks_dir": str(chunks_dir.relative_to(_REPO)),
        "n_record_files": len(files),
        "n_records_total": total_records,
        "corruption_abc": {
            "count": len(corruption),
            "n_blank_lines_total": total_blank,
            "n_blank_trailing_benign": n_blank_trailing,
            "n_blank_midfile": n_blank_midfile,
            "n_byte_identical_dup": len(byte_identical_dup),
            "items": corruption[:200],
        },
        "integrity_findings": {
            "id_collision_count": len(id_collision),
            "id_collision_affected_records": sum(x["occurrences"] for x in id_collision),
            "id_collision_top": sorted(id_collision, key=lambda x: -x["occurrences"])[:50],
            "note": (
                "same chunk_id, different content (chunker id 非一意). v7 corpus にも既存. "
                "K-1/S-1/C-1/A-1 とは別軸 (D-1) として escalation to the maintainer."
            ),
        },
        "group_counts": {
            g: {"by_segment_type": dict(group_seg[g]), "by_layer_candidate": dict(group_layer[g])}
            for g in sorted(group_seg)
        },
        "layer_candidate_totals": dict(layer_total.most_common()),
        "segment_type_totals": dict(seg_total.most_common()),
        "kfs": {
            "n_records": kfs_total,
            "by_group": dict(kfs_by_group),
            "keys_observed": dict(kfs_keys.most_common()),
            "text_map_candidate": "case_name_ja + summary_ja (K-1 pending)",
            "empty_after_map": kfs_empty_after_map,
        },
        "token_char": {
            "char_limit": CHAR_LIMIT,
            "n_over_limit": len(over_limit),
            "max_char_len": maxlen_by_rollup,
            "over_by_segment_rollup": dict(over_counts["rollup"]),
            "over_by_segment_non_rollup": dict(over_counts["non_rollup"]),
            "over_items_top50": sorted(over_limit, key=lambda x: -x["char_len"])[:50],
        },
        "hierarchy": {
            "segment_type_distribution": dict(seg_total.most_common()),
            "kou_count": kou_count,
            "sub_item_count": sub_item_count,
            "articles_with_kou_or_sub_but_no_hashira": articles_without_hashira,
            "kou_sub_chunks_without_hashira": kou_sub_without_hashira,
        },
        "sochi": {
            g: {"by_segment_type": dict(sochi_seg[g]), "by_phase_category": dict(sochi_phase[g])}
            for g in sorted(sochi_seg)
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Track A / A0 read-only chunk-corpus audit (canonical unchanged)."
    )
    ap.add_argument("--chunks-dir", type=Path, default=_REPO / "build" / "chunks")
    ap.add_argument(
        "--output", type=Path, default=_REPO / "build" / "v8-prep-report" / "audit.json"
    )
    args = ap.parse_args()

    if not args.chunks_dir.exists():
        print(f"ERROR: chunks dir not found: {args.chunks_dir}", file=sys.stderr)
        return 1

    report = audit(args.chunks_dir)
    safe_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    c = report["corruption_abc"]
    integ = report["integrity_findings"]
    print(f"records: {report['n_records_total']} in {report['n_record_files']} files")
    print(
        f"KFS: {report['kfs']['n_records']} records, empty-after-map={report['kfs']['empty_after_map']}"
    )
    print(f"over {CHAR_LIMIT} chars: {report['token_char']['n_over_limit']}")
    print(
        f"corruption(a/b/c): {c['count']} "
        f"(midfile_blank={c['n_blank_midfile']}, byte_dup={c['n_byte_identical_dup']}, "
        f"trailing_blank_benign={c['n_blank_trailing_benign']})"
    )
    print(
        f"integrity(D-1) id_collision: {integ['id_collision_count']} ids / "
        f"{integ['id_collision_affected_records']} records (pre-existing in v7)"
    )
    print(f"report -> {args.output.relative_to(_REPO)}")

    # design brief §3.0.1: 既知事故 a/b/c (NUL/mid-file 空行/二重貼付/連結 JSON) > 0 は fail-loud.
    # id 衝突 (D-1) は v7 既存の別軸ゆえ fail-loud にせず報告 escalation に留める。
    if c["count"] > 0:
        print("FAIL-LOUD: a/b/c corruption detected (>0). See report.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

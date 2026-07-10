"""tests/test_v8_prep_audit.py -- Track A / A0 監査の hermetic 単体テスト.

canonical 非改変・純ロジック中心。layer 候補導出 / KFS text マップ / 破損検出 /
下位細別判定 / audit() の集計を合成データで固定する (実 build/chunks 非依存)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import v8_prep_audit as V  # noqa: E402


def test_kfs_text_joins_name_and_summary():
    rec = {"case_name_ja": "事例名", "summary_ja": "要旨本文"}
    assert V.kfs_text(rec) == "事例名\n要旨本文"


def test_kfs_text_empty_when_both_missing():
    assert V.kfs_text({"case_name_ja": "", "summary_ja": "   "}) == ""


def test_record_text_kfs_vs_regular():
    assert V.record_text({"text": "本文"}, is_kfs=False) == "本文"
    assert V.record_text({"case_name_ja": "A", "summary_ja": "B"}, is_kfs=True) == "A\nB"


def test_derive_layer_candidate():
    assert V.derive_layer_candidate("kfs-hojin", None, is_kfs=True) == "ruling"
    assert V.derive_layer_candidate("hojin-taxanswer", "taxanswer", is_kfs=False) == "taxanswer"
    assert V.derive_layer_candidate("hojin-kihon-tsutatsu", "tsutatsu", is_kfs=False) == "tsutatsu"
    assert V.derive_layer_candidate("sochi-hou", "simple", is_kfs=False) == "sochi"
    assert V.derive_layer_candidate("sochi-hou-shikkourei", "simple", is_kfs=False) == "enforcement"
    assert (
        V.derive_layer_candidate("houjin-zei-hou-shikoukisoku", "kou", is_kfs=False)
        == "enforcement"
    )
    assert V.derive_layer_candidate("kinsho-hou", "simple", is_kfs=False) == "statute"


def test_detect_line_corruption():
    assert V.detect_line_corruption('{"a": 1}') is None
    assert V.detect_line_corruption('{"a": 1}\x00') == "nul_byte"
    assert V.detect_line_corruption('{"a":1}{"a":2}') == "concatenated_json"
    assert V.detect_line_corruption("not json at all") == "json_decode_error"


def test_is_sub_item():
    assert V.is_sub_item("law-art-1-p1-kou-4-i") is True
    assert V.is_sub_item("law-art-1-p1-kou-4-ro") is True
    assert V.is_sub_item("law-art-1-p1-kou-4-ha-2") is True
    assert V.is_sub_item("law-art-1-p1-kou-4") is False
    assert V.is_sub_item("law-art-1-rollup") is False


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def test_audit_smoke(tmp_path, monkeypatch):
    # _REPO を tmp に差し替えて relative_to が壊れないようにする
    monkeypatch.setattr(V, "_REPO", tmp_path)
    chunks = tmp_path / "build" / "chunks"

    # 通常法令: hashira 有りの article と、hashira 無しの article
    _write_jsonl(
        chunks / "kinsho-hou" / "kinsho-hou-article-1.chunks.jsonl",
        [
            {
                "id": "k-art-1-p1-hashira",
                "article_id": "k-art-1",
                "segment_type": "hashira",
                "text": "柱書",
            },
            {
                "id": "k-art-1-p1-kou-1",
                "article_id": "k-art-1",
                "segment_type": "kou",
                "text": "号1",
            },
            {
                "id": "k-art-2-p1-kou-1",
                "article_id": "k-art-2",
                "segment_type": "kou",
                "text": "孤立号",
            },
        ],
    )
    # rollup (長大) + 非rollup 超過
    _write_jsonl(
        chunks / "chihou-zei-hou" / "chihou-zei-hou-article-1.chunks.jsonl",
        [
            {
                "id": "c-art-1-rollup",
                "article_id": "c-art-1",
                "segment_type": "rollup",
                "text": "x" * 5000,
            },
            {
                "id": "c-art-1-p1",
                "article_id": "c-art-1",
                "segment_type": "simple",
                "text": "y" * 3000,
            },
        ],
    )
    # KFS: 1 件正常 + 1 件マップ後空
    _write_jsonl(
        chunks / "kfs-hojin" / "kfs-0204040000.saiketsu.jsonl",
        [
            {"case_id": "ntt-1", "case_type": "ruling", "case_name_ja": "名", "summary_ja": "要旨"},
            {"case_id": "ntt-2", "case_type": "ruling", "case_name_ja": "", "summary_ja": ""},
        ],
    )

    rep = V.audit(chunks)
    assert rep["n_records_total"] == 7
    assert rep["corruption_abc"]["count"] == 0
    assert rep["integrity_findings"]["id_collision_count"] == 0
    # layer 候補
    assert rep["layer_candidate_totals"].get("ruling") == 2
    assert rep["layer_candidate_totals"].get("statute") == 5  # kinsho 3 + chihou-zei 2
    # KFS
    assert rep["kfs"]["n_records"] == 2
    assert rep["kfs"]["empty_after_map"] == 1
    # token/char: rollup と 非rollup 別に over をカウント
    assert rep["token_char"]["over_by_segment_rollup"].get("rollup") == 1
    assert rep["token_char"]["over_by_segment_non_rollup"].get("simple") == 1
    assert rep["token_char"]["max_char_len"]["rollup"] == 5000
    # 階層: k-art-2 は hashira 無しで kou を持つ -> 柱書欠落 1 article / 1 chunk
    assert rep["hierarchy"]["articles_with_kou_or_sub_but_no_hashira"] == 1
    assert rep["hierarchy"]["kou_sub_chunks_without_hashira"] == 1


def test_audit_detects_corruption(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "_REPO", tmp_path)
    chunks = tmp_path / "build" / "chunks"
    p = chunks / "kinsho-hou" / "kinsho-hou-article-9.chunks.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    # 二重貼付 (連結 JSON) を 1 行に
    p.write_text('{"id":"a","segment_type":"simple","text":"x"}{"id":"a2"}\n', encoding="utf-8")

    rep = V.audit(chunks)
    assert rep["corruption_abc"]["count"] >= 1
    assert any(item["type"] == "concatenated_json" for item in rep["corruption_abc"]["items"])


def test_audit_classifies_id_collision_vs_byte_dup(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "_REPO", tmp_path)
    chunks = tmp_path / "build" / "chunks"
    p = chunks / "chihou-jichi-hou" / "chihou-jichi-hou-article-1.chunks.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    # same id, different text = id_collision (D-1); trailing blank line = benign
    p.write_text(
        '{"id":"x-art-1-p1-kou-4","segment_type":"kou","text":"A"}\n'
        '{"id":"x-art-1-p1-kou-4","segment_type":"kou","text":"B"}\n'
        # same id, identical line = byte_identical_dup (a/b/c)
        '{"id":"y-art-2-p1","segment_type":"simple","text":"Z"}\n'
        '{"id":"y-art-2-p1","segment_type":"simple","text":"Z"}\n'
        "\n",  # trailing blank (benign)
        encoding="utf-8",
    )
    rep = V.audit(chunks)
    assert rep["integrity_findings"]["id_collision_count"] == 1  # kou-4 (A vs B)
    assert rep["corruption_abc"]["n_byte_identical_dup"] == 1  # y-art-2-p1 (Z==Z)
    assert rep["corruption_abc"]["n_blank_midfile"] == 0
    assert rep["corruption_abc"]["n_blank_trailing_benign"] == 1

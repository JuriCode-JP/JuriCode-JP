"""test_tsutatsu_byte_regression.py -- 法人税基本通達 chunk の出力保持ゲート (FU-514 D-1).

Why this test exists:
    FU-514 は parse-nta-tsutatsu.py を dict 直書きから DirectiveChunk (Pydantic IR)
    経由に移行する。これは **出力完全保持** (data/v0.2 非接触・再embed なし) が最優先
    gate のリファクタなので、移行前後で .jsonl が **バイト一致** することを機械保証する。

    2 層構成:
      (1) キー集合監査 (CI-safe): committed baseline fixture を読み、全 chunk が
          DIRECTIVE_KEY_ORDER の 14 キーをこの順で持つこと、related_articles の各 ref が
          linked / unlinked の 2 形以外のキーを持たないことを assert。隠れ動的キーが
          途中行に混入していないことを保証する (計画 Bug4 ゲート恒久化)。
      (2) byte 回帰 (ローカル限定): NTA HTML cache (`cache/tsutatsu/` は gitignored) が
          在れば parser を subprocess 実行し、出力が baseline と **バイト一致** することを
          assert。cache 不在の CI では skip する (FU-515 E-1 のフルコーパス byte-match と
          同型: 機械検証は push 前ローカル、CI 内はモデル単体 test + schema drift で担保)。

    **落ちたら直すのはモデル/直列化であって baseline ではない** (briefing §1・source-locked)。
    baseline は現 parser の LF 出力スナップショット (safe_write_jsonl が newline="\\n" で
    LF 強制するため、リファクタ後も LF。stale な CRLF 版は使わない)。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
_BASELINE = _THIS.parent / "fixtures" / "hojin-kihon-tsutatsu.tsutatsu.chunks.baseline.jsonl"
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"
_CACHE_DIR = _REPO_ROOT / "cache" / "tsutatsu" / "hojin" / "09"

# LOCKED (§source-lock・改変禁止). 現 dict 出力のキー順 (parse-nta-tsutatsu.py:216-232).
DIRECTIVE_KEY_ORDER = [
    "id",
    "directive_id",
    "law_name_ja",
    "law_abbrev",
    "directive_number",
    "title",
    "text",
    "amendment_note",
    "related_articles",
    "source_url",
    "license",
    "segment_type",
    "article_id",
    "law_name_ja_display",
]

# disjoint Union の 2 形 (相手フィールドを持たない・計画 §2)。
LINKED_REF_KEYS = {"raw", "law_abbrev", "article_number", "article_id"}
UNLINKED_REF_KEYS = {"raw", "law_abbrev", "article_number", "unlinked_reason"}


def _read_baseline_records() -> list[dict]:
    import json

    return [
        json.loads(line)
        for line in _BASELINE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ===========================================================
# (1) キー集合監査 (CI-safe: committed baseline のみ参照)
# ===========================================================


def test_baseline_fixture_exists() -> None:
    assert _BASELINE.exists(), f"baseline fixture 不在: {_BASELINE}"


def test_all_chunks_have_locked_key_order() -> None:
    """全 chunk が DIRECTIVE_KEY_ORDER の 14 キーをこの順で持つ (隠れキー 0)."""
    records = _read_baseline_records()
    assert records, "baseline が空"
    for i, rec in enumerate(records):
        assert list(rec.keys()) == DIRECTIVE_KEY_ORDER, (
            f"chunk[{i}] (id={rec.get('id')!r}) のキー順/集合が DIRECTIVE_KEY_ORDER と不一致: "
            f"{list(rec.keys())}"
        )


def test_related_article_refs_match_disjoint_forms() -> None:
    """related_articles の各 ref が linked / unlinked の 2 形以外のキーを持たない."""
    records = _read_baseline_records()
    for rec in records:
        for ref in rec["related_articles"]:
            keys = set(ref.keys())
            assert keys in (LINKED_REF_KEYS, UNLINKED_REF_KEYS), (
                f"id={rec['id']!r} の ref が disjoint 2 形のいずれにも一致しない: {sorted(keys)}"
            )


def test_corpus_ref_population_is_linked_only() -> None:
    """現コーパスの ref 母集団を pin する (linked 31 / unlinked 0・briefing §0 実測)."""
    records = _read_baseline_records()
    linked = unlinked = 0
    for rec in records:
        for ref in rec["related_articles"]:
            if set(ref.keys()) == LINKED_REF_KEYS:
                linked += 1
            elif set(ref.keys()) == UNLINKED_REF_KEYS:
                unlinked += 1
    assert (linked, unlinked) == (31, 0), (
        f"現コーパスの ref 母集団が変化: linked={linked} unlinked={unlinked} (期待 31/0). "
        "コーパスが変わった場合は baseline 再採取の妥当性を人間が判断すること."
    )


def test_chunk_count_locked() -> None:
    assert len(_read_baseline_records()) == 35, "現コーパスの chunk 数は 35"


# ===========================================================
# (2) byte 回帰 (ローカル限定: cache 不在の CI では skip)
# ===========================================================


@pytest.mark.skipif(
    not _CACHE_DIR.exists(),
    reason="NTA HTML cache (cache/tsutatsu/, gitignored) 不在 -- byte 回帰は push 前ローカルゲート",
)
def test_parser_output_byte_identical_to_baseline(tmp_path: Path) -> None:
    """parser を現入力で再実行 -> 出力が baseline と **バイト一致** (出力保持の核)."""
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(_PARSER),
            "--cache-dir",
            str(_CACHE_DIR),
            "--output-dir",
            str(out_dir),
        ],
        cwd=str(_REPO_ROOT),  # 相対 path (cache/tsutatsu/) を見失わない (briefing Bug31)
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        # 子プロセスの stderr 日本語サマリを utf-8 で吐かせる (Windows の cp932
        # デフォルトだと親側 utf-8 decode が 0x82 等で割れる)。
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, f"parser 失敗 (rc={result.returncode}):\n{result.stderr}"

    produced = out_dir / "hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    assert produced.exists(), f"出力不在: {produced}\n{result.stderr}"

    produced_bytes = produced.read_bytes()
    baseline_bytes = _BASELINE.read_bytes()
    assert produced_bytes == baseline_bytes, (
        f"出力が baseline とバイト不一致 (produced={len(produced_bytes)}B "
        f"baseline={len(baseline_bytes)}B). 直すのはモデル/直列化であって baseline ではない."
    )

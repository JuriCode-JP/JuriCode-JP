"""Hermetic tests for the citation registry builder (W6 MVP, T1-T9).

Everything runs on a synthetic mini-tree under tmp_path (no dependence on
build/ artifacts, which are gitignored and absent in CI). The tests lock the
RULES: id derivation, per-layer document text, hash_basis classification,
determinism, count/coverage/orphan gates, and the allow-list STOP.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_registry as BR  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "build_registry.py"

# ---- fixture mini-tree ----------------------------------------------------

LAW_ID = "999AC0000000001"
LAW_NUM = "令和二年法律第一号"

MD_TEMPLATE = """---
law_id: {law_id}
law_name_ja: テスト法
article_number: '{num}'
article_id: {aid}
version_date: '2020-01-01'
source_url: https://laws.e-gov.go.jp/law/{law_id}
last_verified: '2026-01-01'
license: MIT
translation_status: none
---

# テスト法 第{num}条

## 原文 (日本語)
### 第{kanji}条
{text}

## English Translation
(pending)
"""


def _canonical_sha(md_text: str) -> str:
    """Expected manifest sha via the SAME extraction verify.py/CI uses."""
    import importlib.util

    parse_dir = BR._REPO / "tools" / "parse"
    if str(parse_dir) not in sys.path:
        sys.path.insert(0, str(parse_dir))
    spec = importlib.util.spec_from_file_location("_test_verify", parse_dir / "verify.py")
    vf = importlib.util.module_from_spec(spec)
    sys.modules["_test_verify"] = vf  # dataclass field resolution needs this
    spec.loader.exec_module(vf)
    canonical = vf.canonicalize("\n\n".join(vf.extract_ja_paragraphs_from_md(md_text)))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
        newline="\n",
    )


def make_tree(tmp_path: Path) -> BR.RegistryPaths:
    """Synthetic repo slice: 1 law x 2 articles, 附則 (group + 条), and one
    document per store layer. All allow-listed store files exist (empty where
    unused) because the loaders read the full allow-list by design."""
    data = tmp_path / "data"
    cache = tmp_path / "cache"
    chunks = tmp_path / "chunks"
    law_dir = data / "phase-test" / "test-hou"
    law_dir.mkdir(parents=True)
    cache.mkdir()
    chunks.mkdir()

    arts = [("1", "一", "test-hou-art-1"), ("1-2", "一", "test-hou-art-1-2")]
    entries = []
    for num, kanji, aid in arts:
        md = MD_TEMPLATE.format(law_id=LAW_ID, num=num, kanji=kanji, aid=aid, text="本文" + aid)
        (law_dir / f"test-hou-article-{num}.md").write_text(md, encoding="utf-8", newline="\n")
        entries.append(
            {
                "article_id": aid,
                "article_number": num,
                "filename": f"test-hou-article-{num}.md",
                "ja_text_sha256": _canonical_sha(md),
            }
        )
    (law_dir / "_source-manifest.json").write_text(
        json.dumps(
            {
                "law_abbrev": "test-hou",
                "law_id": LAW_ID,
                "law_name_ja": "テスト法",
                "version_date": "2020-01-01",
                "articles": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cache / f"{LAW_ID}.xml").write_text(
        f"<Law><LawNum>{LAW_NUM}</LawNum><LawBody/></Law>", encoding="utf-8"
    )

    # Allow-listed stores (empty unless populated below).
    for name in BR.TAXANSWER_STORES:
        _write_jsonl(chunks / name / f"{name}.taxanswer.chunks.jsonl", [])
    for name in BR.TSUTATSU_STORE_DIRS:
        _write_jsonl(chunks / name / f"{name}.tsutatsu.chunks.jsonl", [])
    for name in BR.TSUTATSU_STORE_FILES:
        _write_jsonl(chunks / name, [])
    for name in BR.KFS_STORE_DIRS:
        (chunks / name).mkdir()
    _write_jsonl(
        chunks / "hojin-taxanswer" / "hojin-taxanswer.taxanswer.chunks.jsonl",
        [
            {
                "id": "hojin-taxanswer-1000",
                "text": "タックスアンサー本文",
                "title": "テスト",
                "related_articles": [],
                "law_name_ja": "タックスアンサー",
                "version_date": "2025-04-01",
                "source_url": "https://www.nta.go.jp/t/1000.htm",
                "license": "cc-by-jp-nta",
            }
        ],
    )
    _write_jsonl(
        chunks / "hojin-kihon-tsutatsu" / "hojin-kihon-tsutatsu.tsutatsu.chunks.jsonl",
        [
            {
                "directive_id": "hojin-kihon-tsutatsu-1-1-1",
                "id": "hojin-kihon-tsutatsu-1-1-1",
                "text": "通達本文",
                "law_name_ja": "法人税基本通達",
                "source_url": "https://www.nta.go.jp/law/t/1.htm",
                "license": "public-domain-13-2",
            }
        ],
    )
    _write_jsonl(
        chunks / "kfs-hojin" / "kfs-0000000000.saiketsu.jsonl",
        [
            {
                "case_id": "ntt-2000-01-01-j1-1",
                "case_name_ja": "テスト裁決",
                "summary_ja": "テスト要旨",
                "decision_date": "2000-01-01",
                "url": "https://www.kfs.go.jp/t.html#y01",
                "source_license": "pdl-1.0",
            }
        ],
    )

    corpus = [
        # 本則 (statute): hyphen id + underscore variant of the branch article.
        {
            "chunk_id": "test-hou-art-1-p1",
            "layer": "statute",
            "segment_type": "simple",
            "article_id": "test-hou-art-1",
            "law_id": LAW_ID,
        },
        {
            "chunk_id": "test-hou-art-1_2-p1",
            "layer": "statute",
            "segment_type": "simple",
            "article_id": "test-hou-art-1_2",  # corpus underscore form
            "law_id": LAW_ID,
        },
        # 附則 group with 条 substructure: art doc (2 paragraphs) + group rollup.
        {
            "chunk_id": "test-hou-supplproviso-1-art1-p1",
            "layer": "statute",
            "segment_type": "supplproviso",
            "article_id": None,
            "law_id": LAW_ID,
            "text_raw": "附則第一条第一項",
        },
        {
            "chunk_id": "test-hou-supplproviso-1-art1-p2",
            "layer": "statute",
            "segment_type": "supplproviso",
            "article_id": None,
            "law_id": LAW_ID,
            "text_raw": "附則第一条第二項",
        },
        {
            "chunk_id": "test-hou-supplproviso-1-rollup",
            "layer": "statute",
            "segment_type": "supplproviso_rollup",
            "article_id": None,
            "law_id": LAW_ID,
            "text_raw": "附　則（全文）",
        },
        # tsutatsu: doc chunk + split chunk of the same directive.
        {
            "chunk_id": "hojin-kihon-tsutatsu-1-1-1",
            "layer": "tsutatsu",
            "segment_type": "tsutatsu",
            "directive_id": "hojin-kihon-tsutatsu-1-1-1",
        },
        # taxanswer: two -sub chunks -> one document.
        {
            "chunk_id": "hojin-taxanswer-1000-sub1",
            "layer": "taxanswer",
            "segment_type": "taxanswer",
        },
        {
            "chunk_id": "hojin-taxanswer-1000-sub2",
            "layer": "taxanswer",
            "segment_type": "taxanswer",
        },
        # ruling.
        {
            "chunk_id": "ntt-2000-01-01-j1-1",
            "layer": "ruling",
            "segment_type": "ruling",
            "case_id": "ntt-2000-01-01-j1-1",
        },
    ]
    _write_jsonl(tmp_path / "corpus.jsonl", corpus)
    _write_jsonl(
        tmp_path / "embed.jsonl",
        [{"chunk_id": c["chunk_id"]} for c in corpus if c["segment_type"] != "supplproviso_rollup"],
    )
    return BR.RegistryPaths(
        data_dir=data,
        cache_dir=cache,
        chunks_dir=chunks,
        corpus_path=tmp_path / "corpus.jsonl",
        embed_path=tmp_path / "embed.jsonl",
        out_dir=tmp_path / "registry",
    )


EXPECTED = {"articles": 2, "taxanswer": 1, "tsutatsu": 1, "ruling": 1}


def _docs(documents_bytes: bytes) -> dict[str, dict]:
    rows = [json.loads(line) for line in documents_bytes.decode("utf-8").splitlines()]
    return {r["juri_id"]: r for r in rows}


# ---- T5 determinism / basic shape ----------------------------------------


def test_build_is_deterministic_and_sorted(tmp_path):
    paths = make_tree(tmp_path)
    d1, c1, report = BR.build_registry(paths, EXPECTED)
    d2, c2, _ = BR.build_registry(paths, EXPECTED)
    assert d1 == d2 and c1 == c2  # byte identity (T5)
    ids = [json.loads(line)["juri_id"] for line in d1.decode("utf-8").splitlines()]
    assert ids == sorted(ids)
    assert report.docs_by_layer == {"statute": 4, "taxanswer": 1, "tsutatsu": 1, "ruling": 1}
    assert report.suppl_docs == 2 and report.suppl_chunks == 3
    assert report.articles_not_in_corpus == 0


# ---- T1 uniqueness / orphans ----------------------------------------------


def test_orphan_chunk_stops(tmp_path):
    paths = make_tree(tmp_path)
    rows = [json.loads(line) for line in paths.corpus_path.read_text(encoding="utf-8").splitlines()]
    rows.append(
        {"chunk_id": "hojin-taxanswer-9999", "layer": "taxanswer", "segment_type": "taxanswer"}
    )
    _write_jsonl(paths.corpus_path, rows)
    with pytest.raises(BR.RegistryError, match="orphan"):
        BR.build_registry(paths, EXPECTED)


# ---- T2 statute sha chain (sample verify) ---------------------------------


def test_sample_verify_passes_and_catches_corruption(tmp_path):
    paths = make_tree(tmp_path)
    d1, _, _ = BR.build_registry(paths, EXPECTED)
    assert BR.sample_verify(paths, d1, per_layer=5) == 7  # 2 statute + 2 suppl + 3 stored
    md = paths.data_dir / "phase-test" / "test-hou" / "test-hou-article-1.md"
    md.write_text(
        md.read_text(encoding="utf-8").replace("本文test-hou-art-1", "改変された本文"),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(BR.RegistryError, match="sample verify failed"):
        BR.sample_verify(paths, d1, per_layer=5)


# ---- T3 hash_basis classification -----------------------------------------


def test_hash_basis_classification(tmp_path):
    paths = make_tree(tmp_path)
    d1, _, _ = BR.build_registry(paths, EXPECTED)
    docs = _docs(d1)
    assert docs["test-hou-art-1"]["hash_basis"] == BR.HASH_EGOV_CANONICAL
    assert docs["test-hou-supplproviso-1"]["hash_basis"] == BR.HASH_EGOV_DERIVED
    assert docs["test-hou-supplproviso-1-art1"]["hash_basis"] == BR.HASH_EGOV_DERIVED
    for jid in ("hojin-kihon-tsutatsu-1-1-1", "hojin-taxanswer-1000", "ntt-2000-01-01-j1-1"):
        assert docs[jid]["hash_basis"] == BR.HASH_STORED_TEXT
    # statute sha is the manifest value verbatim, never recomputed here
    manifest = json.loads(
        (paths.data_dir / "phase-test" / "test-hou" / "_source-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    by_id = {a["article_id"]: a["ja_text_sha256"] for a in manifest["articles"]}
    assert docs["test-hou-art-1"]["text_sha256"] == by_id["test-hou-art-1"]


# ---- T4 law_num ------------------------------------------------------------


def test_law_num_must_be_single_valued(tmp_path):
    paths = make_tree(tmp_path)
    (paths.cache_dir / f"{LAW_ID}.xml").write_text(
        f"<Law><LawNum>{LAW_NUM}</LawNum><LawNum>別の番号</LawNum><LawBody/></Law>",
        encoding="utf-8",
    )
    with pytest.raises(BR.RegistryError, match="exactly one"):
        BR.build_registry(paths, EXPECTED)


def test_duplicate_law_num_values_warn_not_fail(tmp_path):
    paths = make_tree(tmp_path)
    # Second law sharing the same LawNum value: WARN, build continues.
    law2 = "999AC0000000002"
    law_dir = paths.data_dir / "phase-test" / "test-ni-hou"
    law_dir.mkdir()
    md = MD_TEMPLATE.format(
        law_id=law2, num="1", kanji="一", aid="test-ni-hou-art-1", text="第二法本文"
    )
    (law_dir / "test-ni-hou-article-1.md").write_text(md, encoding="utf-8", newline="\n")
    (law_dir / "_source-manifest.json").write_text(
        json.dumps(
            {
                "law_abbrev": "test-ni-hou",
                "law_id": law2,
                "law_name_ja": "テスト第二法",
                "articles": [
                    {
                        "article_id": "test-ni-hou-art-1",
                        "article_number": "1",
                        "filename": "test-ni-hou-article-1.md",
                        "ja_text_sha256": _canonical_sha(md),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (paths.cache_dir / f"{law2}.xml").write_text(
        f"<Law><LawNum>{LAW_NUM}</LawNum><LawBody/></Law>", encoding="utf-8"
    )
    rows = [json.loads(line) for line in paths.corpus_path.read_text(encoding="utf-8").splitlines()]
    rows.append(
        {
            "chunk_id": "test-ni-hou-art-1-p1",
            "layer": "statute",
            "segment_type": "simple",
            "article_id": "test-ni-hou-art-1",
            "law_id": law2,
        }
    )
    _write_jsonl(paths.corpus_path, rows)
    expected = dict(EXPECTED, articles=3)
    with pytest.warns(RuntimeWarning, match="law_num value"):
        _, _, report = BR.build_registry(paths, expected)
    assert report.law_num_duplicate_values == 1


# ---- T6 metadata does not affect the hash ----------------------------------


def test_metadata_change_does_not_change_text_sha256(tmp_path):
    paths = make_tree(tmp_path)
    d1, _, _ = BR.build_registry(paths, EXPECTED)
    store = paths.chunks_dir / "hojin-taxanswer" / "hojin-taxanswer.taxanswer.chunks.jsonl"
    row = json.loads(store.read_text(encoding="utf-8"))
    row["related_articles"] = [{"raw": "法34"}]
    row["title"] = "変更後タイトル"
    _write_jsonl(store, [row])
    d2, _, _ = BR.build_registry(paths, EXPECTED)
    before = _docs(d1)["hojin-taxanswer-1000"]["text_sha256"]
    after = _docs(d2)["hojin-taxanswer-1000"]["text_sha256"]
    assert before == after


# ---- T7 count drift ---------------------------------------------------------


def test_document_count_drift_stops(tmp_path):
    paths = make_tree(tmp_path)
    with pytest.raises(BR.RegistryError, match="count drift"):
        BR.build_registry(paths, dict(EXPECTED, taxanswer=2))


# ---- T8 allow-list ----------------------------------------------------------


def test_unexpected_store_dir_stops(tmp_path):
    paths = make_tree(tmp_path)
    (paths.chunks_dir / "foo-taxanswer").mkdir()
    with pytest.raises(BR.RegistryError, match="allow-list"):
        BR.build_registry(paths, EXPECTED)


def test_known_backup_dir_is_ignored(tmp_path):
    paths = make_tree(tmp_path)
    (paths.chunks_dir / "build-chunks-backup").mkdir()
    BR.build_registry(paths, EXPECTED)  # no STOP


# ---- T9 CLI smoke -----------------------------------------------------------


def test_cli_help_smoke():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0
    assert "citation registry" in proc.stdout


# ---- id derivation / per-layer text rules -----------------------------------


def test_suppl_doc_id_derivation():
    cases = {
        "x-hou-supplproviso-1-art1-p1": "x-hou-supplproviso-1-art1",
        "x-hou-supplproviso-389-art1-p1-sub2": "x-hou-supplproviso-389-art1",
        "x-hou-supplproviso-1-art5_11-p1-tbl2-w3": "x-hou-supplproviso-1-art5_11",
        "x-hou-supplproviso-71-p1-sub3": "x-hou-supplproviso-71",
        "x-hou-supplproviso-1-rollup": "x-hou-supplproviso-1",
        # e-Gov range Nums surface as a single 附則 unit (colon kept verbatim)
        "x-hou-supplproviso-1-art39:40-p1": "x-hou-supplproviso-1-art39:40",
        "x-hou-supplproviso-1-art5_2:5_3-p1": "x-hou-supplproviso-1-art5_2:5_3",
    }
    for chunk_id, doc_id in cases.items():
        assert BR.suppl_doc_id(chunk_id) == doc_id
    with pytest.raises(BR.RegistryError, match="unrecognized"):
        BR.suppl_doc_id("x-hou-art-1-p1")  # not a supplproviso id


def test_suppl_doc_text_rollup_wins_else_join_in_order(tmp_path):
    paths = make_tree(tmp_path)
    d1, _, _ = BR.build_registry(paths, EXPECTED)
    docs = _docs(d1)
    # group doc = rollup text_raw verbatim
    assert docs["test-hou-supplproviso-1"]["text_sha256"] == BR.sha256_text("附　則（全文）")
    # 条 doc without rollup = "\n"-join of its chunks in corpus order
    joined = "附則第一条第一項\n附則第一条第二項"
    assert docs["test-hou-supplproviso-1-art1"]["text_sha256"] == BR.sha256_text(joined)


def test_ruling_text_is_k1_concatenation(tmp_path):
    paths = make_tree(tmp_path)
    d1, _, _ = BR.build_registry(paths, EXPECTED)
    expected = BR.sha256_text("テスト裁決\nテスト要旨")
    doc = _docs(d1)["ntt-2000-01-01-j1-1"]
    assert doc["text_sha256"] == expected
    assert doc["decision_date"] == "2000-01-01"
    assert doc["version_date"] is None  # decision_date is NOT a version_date substitute
    assert doc["license"] == "pdl-1.0"


def test_underscore_article_id_normalized_to_manifest_form(tmp_path):
    paths = make_tree(tmp_path)
    _, c1, _ = BR.build_registry(paths, EXPECTED)
    rows = [json.loads(line) for line in c1.decode("utf-8").splitlines()]
    by_chunk = {r["chunk_id"]: r["juri_id"] for r in rows}
    assert by_chunk["test-hou-art-1_2-p1"] == "test-hou-art-1-2"


def test_embed_index_coverage_gate(tmp_path):
    paths = make_tree(tmp_path)
    _write_jsonl(paths.embed_path, [{"chunk_id": "ghost-chunk-1"}])
    with pytest.raises(BR.RegistryError, match="coverage hole"):
        BR.build_registry(paths, EXPECTED)


def test_null_metadata_counted_not_fabricated(tmp_path):
    paths = make_tree(tmp_path)
    d1, _, report = BR.build_registry(paths, EXPECTED)
    docs = _docs(d1)
    assert docs["hojin-kihon-tsutatsu-1-1-1"]["version_date"] is None  # tsutatsu has none
    assert docs["test-hou-supplproviso-1"]["version_date"] is None  # 附則 has none
    assert report.null_version_date == 4  # 2 suppl + 1 tsutatsu + 1 ruling

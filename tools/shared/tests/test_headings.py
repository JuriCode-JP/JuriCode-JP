"""test_headings.py -- 項見出し regex の単一真実源テスト (FU-554).

Why: 同一の見出し regex が 5 箇所に独立実装され、枝番の扱いが食い違っていた
(segment_parser は 1 段のみ・export-jsonl は枝番非対応)。生成側と検証側で
regex がずれると「生成が落としたものを検証が見逃す」構造になる。
本テストは (1) 枝番 0..N 段を全て拾うこと (2) 5 つの利用側が同一 regex を
参照していること (identity) を固定する。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from juricode_shared.headings import (
    PARAGRAPH_HEADING_RE,
    PARAGRAPH_HEADING_SPLIT_RE,
    split_paragraph_blocks,
)

_REPO = Path(__file__).resolve().parents[3]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MATCHING = [
    "### 第三十六条",
    "### 第三十六条第二項",
    "### 第百三十二条の二",  # 単枝番
    "### 第百三十二条の二第一項",
    "### 第十条の五の二",  # 二重枝番 (旧 segment_parser では全滅)
    "### 第十条の五の二第三項",
    "### 第三十七条の十一の三",
    "### 第36条",  # アラビア数字
]

NOT_MATCHING = [
    "## 原文 (日本語)",
    "### Article 36",
    "#### 第三十六条",  # H4 は項見出しでない
    "第三十六条",  # 見出し記号なし
]


def test_matches_branch_articles_of_any_depth():
    for h in MATCHING:
        assert PARAGRAPH_HEADING_RE.match(h), f"should match: {h}"
        assert PARAGRAPH_HEADING_SPLIT_RE.match(h), f"split re should match: {h}"


def test_rejects_non_headings():
    for h in NOT_MATCHING:
        assert not PARAGRAPH_HEADING_RE.match(h), f"should not match: {h}"


def test_split_re_has_no_capture_group():
    """re.split 用は capture group を持たないこと (持つと分割結果に group が混入する)."""
    assert PARAGRAPH_HEADING_SPLIT_RE.groups == 0
    body = "intro\n### 第十条の五の二\n本文A\n### 第十条の五の二第二項\n本文B\n"
    parts = PARAGRAPH_HEADING_SPLIT_RE.split(body)
    assert len(parts) == 3  # intro + 2 項 (group 混入なら 5 になる)
    assert parts[1].strip() == "本文A"
    assert parts[2].strip() == "本文B"


def test_finditer_re_exposes_paragraph_number():
    m = PARAGRAPH_HEADING_RE.match("### 第十条の五の二第三項")
    assert m.group(1) == "三"


def test_split_paragraph_blocks_pairs_headings_and_bodies():
    ja = "\n### 第一条\n\n本文A\n\n### 第一条第二項\n\n本文B\n"
    intro, heads, bodies = split_paragraph_blocks(ja)
    assert intro == "\n"
    assert len(heads) == len(bodies) == 2
    assert bodies[1].strip() == "本文B"


def test_all_consumers_share_the_same_regex_object():
    """5 つの利用側が shared の regex を参照していること (drift の再発防止)."""
    seg = _load("_t_segment_parser", _REPO / "tools/parse/v0.2/segment_parser.py")
    ver = _load("_t_verify", _REPO / "tools/parse/verify.py")
    emit = _load("_t_emit_table_md", _REPO / "tools/parse/v0.2/emit_table_md.py")
    chash = _load("_t_canonical_hash", _REPO / "tools/parse/v0.2/manifest/canonical_hash.py")
    exp = _load("_t_export_jsonl", _REPO / "tools/export/lawsy-bq/export-jsonl.py")

    assert seg.PARAGRAPH_HEADING_PATTERN is PARAGRAPH_HEADING_SPLIT_RE
    assert ver.PARAGRAPH_HEADING_RE is PARAGRAPH_HEADING_RE
    assert emit.PARAGRAPH_HEADING_RE is PARAGRAPH_HEADING_RE
    assert chash._PARAGRAPH_HEADING_RE is PARAGRAPH_HEADING_RE
    assert exp.PARAGRAPH_HEADING_RE is PARAGRAPH_HEADING_RE


def test_double_branch_article_now_splits_in_segment_parser():
    """二重枝番の項分割が復活していること (旧実装では 0 分割 = chunk 空)."""
    seg = _load("_t_segment_parser2", _REPO / "tools/parse/v0.2/segment_parser.py")
    body = "\n## 原文 (日本語)\n\n### 第十条の五の二\n\n本文である。\n"
    parts = seg.PARAGRAPH_HEADING_PATTERN.split(body)
    assert len(parts) == 2, "二重枝番の見出しで分割できること"
    assert parts[1].strip() == "本文である。"


def test_shared_regex_is_multiline():
    assert PARAGRAPH_HEADING_RE.flags & re.MULTILINE
    assert PARAGRAPH_HEADING_SPLIT_RE.flags & re.MULTILINE

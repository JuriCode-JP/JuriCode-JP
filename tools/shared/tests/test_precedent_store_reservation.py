"""PrecedentStoreEntry の D5 予約フィールド (overruled_by / modified_by) のテスト.

Why: 判例変更 (overruling) の新旧関係を構造化する空箱を予約する (D5・2026-07-10 佐藤裁定)。
populate は後段 FU。ここでは (1) 既定空 (2) 往復保持 (3) 既存 store の後方互換
(4) extra=forbid 回帰、の 4 点で「予約が既存データを壊さない」ことを固定する。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from juricode_shared.ir import PrecedentStoreEntry, Relevance

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CASE_LAW_DIR = _REPO_ROOT / "data" / "v0.2" / "case-law"


def _store_entry(**overrides) -> PrecedentStoreEntry:
    """最小限の有効な PrecedentStoreEntry を構築."""
    defaults = dict(
        case_type="precedent",
        case_id="scj-1969-12-04-keishu-23-12-1573",
        court="最高裁判所第一小法廷",
        court_en="Supreme Court of Japan, First Petty Bench",
        decision_date=date(1969, 12, 4),
        citation="刑集23巻12号1573頁",
        relevance=Relevance.HIGH,
        source_license="public-domain",
        summary_source="none",
    )
    defaults.update(overrides)
    return PrecedentStoreEntry(**defaults)


def test_reserved_fields_default_empty() -> None:
    entry = _store_entry()
    assert entry.overruled_by == []
    assert entry.modified_by == []


def test_reserved_fields_round_trip() -> None:
    entry = _store_entry(
        overruled_by=["scj-2000-01-01-keishu-54-1-1"],
        modified_by=["scj-2010-05-01-keishu-64-4-100"],
    )
    dumped = entry.model_dump(mode="json")
    assert dumped["overruled_by"] == ["scj-2000-01-01-keishu-54-1-1"]
    assert dumped["modified_by"] == ["scj-2010-05-01-keishu-64-4-100"]
    restored = PrecedentStoreEntry(**dumped)
    assert restored.overruled_by == entry.overruled_by
    assert restored.modified_by == entry.modified_by


def test_existing_precedent_stores_backward_compatible() -> None:
    """既存 store 全件が新フィールド既定値 (空リスト) 付きで valid に読めること."""
    store_files = sorted(_CASE_LAW_DIR.glob("*/precedents.jsonl"))
    assert store_files, f"no precedents.jsonl found under {_CASE_LAW_DIR}"
    total = 0
    for store_file in store_files:
        for line in store_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = PrecedentStoreEntry(**json.loads(line))
            assert entry.overruled_by == []
            assert entry.modified_by == []
            total += 1
    assert total > 0


def test_extra_forbid_regression() -> None:
    with pytest.raises(ValidationError):
        _store_entry(foo=1)

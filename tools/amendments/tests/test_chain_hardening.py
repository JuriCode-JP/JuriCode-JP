"""test_chain_hardening.py -- build_enforced_chain の corpus ソース版アンカー頑健化 (hermetic).

Why (改正履歴 横展開②・国税通則法・e-Gov 連結遅延対策・案A):
    改正 diff は corpus 本文と同一 point-in-time で終端しないと誤帰属になる。corpus は
    e-Gov law_data(現行) から生成されるので、その現行版 revision_id を改正チェーンの
    アンカーとし、そこでチェーンを打ち切る。e-Gov のメタデータ/本文連結遅延で新施行版が
    未連結 (CurrentEnforced=0・国税通則法 2026-06-24) でも、アンカー = law_data 現行を
    採用して整合を保つ。本 test はこのアンカーロジックを hermetic に固定する:
      - CurrentEnforced=0 でアンカー = law_data 現行 (後続の未連結施行版は打ち切り・WARNING)。
      - 通常法令: CurrentEnforced=1 == アンカー == 日付最大 一致 (従来と同一チェーン)。
      - 後方互換: アンカー未提供時は従来ロジック (CurrentEnforced ちょうど1件) にフォールバック
        = 既存4法令の unit test 無改変。
      - fail-loud 温存: (a) アンカーが施行済チェーンに無い / (b) アンカーが未来施行版 /
        (c) chain 非単調 / (d) CurrentEnforced がアンカーと不一致 (複数 or 別版)。
    合成 revision dict のみを用い e-Gov / cache / corpus には依存しない = hermetic。
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AMEND_SRC = _REPO_ROOT / "tools" / "amendments"
if str(_AMEND_SRC) not in sys.path:
    sys.path.insert(0, str(_AMEND_SRC))

_TODAY = date(2026, 7, 10)


def _rev(rid: str, enf: str, status: str) -> dict:
    return {
        "law_revision_id": rid,
        "amendment_enforcement_date": enf,
        "current_revision_status": status,
    }


def _descending(*revs: dict) -> list[dict]:
    """build_enforced_chain は reversed() で昇順化するので入力は施行日降順で渡す。"""
    return list(revs)


# ---- 正常系 --------------------------------------------------------------


def test_kokutsu_type_anchor_truncates_unconsolidated(caplog):
    """CurrentEnforced=0: アンカー = law_data 現行、後続の未連結施行版は打ち切り (WARNING)。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20260624_x", "2026-06-24", "PreviousEnforced"),  # e-Gov 未連結 (打ち切り対象)
        _rev("L_20260521_x", "2026-05-21", "PreviousEnforced"),  # law_data 現行 = アンカー
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),
    )
    with caplog.at_level(logging.WARNING, logger="juricode.amendments"):
        chain = ea.build_enforced_chain(revs, law_data_current_rid="L_20260521_x", today=_TODAY)
    assert [r["law_revision_id"] for r in chain] == ["L_20200401_x", "L_20260521_x"]
    assert chain[-1]["law_revision_id"] == "L_20260521_x"  # アンカーで終端
    assert "L_20260624_x" not in {r["law_revision_id"] for r in chain}  # 未連結版は除外
    assert any("consolidation lag" in rec.message for rec in caplog.records)


def test_normal_law_flag_and_anchor_agree():
    """通常法令: CurrentEnforced=1 == アンカー == 日付最大 → 従来と同一チェーン。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20250401_x", "2025-04-01", "CurrentEnforced"),
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),
    )
    chain = ea.build_enforced_chain(revs, law_data_current_rid="L_20250401_x", today=_TODAY)
    assert chain[-1]["law_revision_id"] == "L_20250401_x"
    assert chain[-1]["current_revision_status"] == "CurrentEnforced"


def test_backward_compat_no_anchor():
    """後方互換: アンカー未提供 → 従来ロジック (CurrentEnforced ちょうど1件・全チェーン)。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20250401_x", "2025-04-01", "CurrentEnforced"),
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),
    )
    chain = ea.build_enforced_chain(revs, today=_TODAY)  # law_data_current_rid 未指定
    assert [r["law_revision_id"] for r in chain] == ["L_20200401_x", "L_20250401_x"]


def test_backward_compat_no_anchor_zero_current_raises():
    """後方互換パス: アンカー未提供で CurrentEnforced=0 は従来どおり raise (フォールバック)。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20260624_x", "2026-06-24", "PreviousEnforced"),
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),
    )
    with pytest.raises(ValueError, match="expected exactly 1 CurrentEnforced"):
        ea.build_enforced_chain(revs, today=_TODAY)


# ---- fail-loud (a)-(d) ---------------------------------------------------


def test_fail_anchor_not_in_chain():
    """(a) law_data 現行が施行済チェーンに無い → raise。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20250401_x", "2025-04-01", "PreviousEnforced"),
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),
    )
    with pytest.raises(ValueError, match="not in enforced chain"):
        ea.build_enforced_chain(revs, law_data_current_rid="L_NOPE", today=_TODAY)


def test_fail_anchor_is_future_version():
    """(b) アンカーが未来施行版 (施行日 > 今日) → raise。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20270401_x", "2027-04-01", "PreviousEnforced"),  # 未来
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),
    )
    with pytest.raises(ValueError, match="future-enforced version"):
        ea.build_enforced_chain(revs, law_data_current_rid="L_20270401_x", today=_TODAY)


def test_fail_non_monotonic():
    """(c) chain が単調非減少でない (predecessor 欠落) → raise。"""
    import extract_amendments as ea

    # reversed 後の昇順が [2025, 2020] になる (降順でない) 入力で非単調を起こす。
    revs = [
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),
        _rev("L_20250401_x", "2025-04-01", "CurrentEnforced"),
    ]
    with pytest.raises(ValueError, match="not monotonic"):
        ea.build_enforced_chain(revs, law_data_current_rid="L_20250401_x", today=_TODAY)


def test_fail_current_flag_disagrees_with_anchor():
    """(d) CurrentEnforced が存在するのにアンカーと別版 → raise。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20250401_x", "2025-04-01", "CurrentEnforced"),  # フラグはこちら
        _rev("L_20200401_x", "2020-04-01", "PreviousEnforced"),  # アンカーはこちら
    )
    with pytest.raises(ValueError, match="disagrees with law_data current"):
        ea.build_enforced_chain(revs, law_data_current_rid="L_20200401_x", today=_TODAY)


def test_fail_two_current_enforced():
    """(d) CurrentEnforced が複数 → アンカーと一意一致にならず raise。"""
    import extract_amendments as ea

    revs = _descending(
        _rev("L_20250401_x", "2025-04-01", "CurrentEnforced"),
        _rev("L_20200401_x", "2020-04-01", "CurrentEnforced"),
    )
    with pytest.raises(ValueError, match="disagrees with law_data current"):
        ea.build_enforced_chain(revs, law_data_current_rid="L_20250401_x", today=_TODAY)


# ---- law_data パース -----------------------------------------------------


def test_current_revision_id_from_law_data():
    """law_data 応答 XML から現行版 law_revision_id を取り出す。"""
    import extract_amendments as ea

    xml = (
        "<law_data_response><law_info><law_id>337AC0000000066</law_id></law_info>"
        "<revision_info><law_revision_id>337AC0000000066_20260521_505AC0000000003</law_revision_id>"
        "<amendment_enforcement_date>2026-05-21</amendment_enforcement_date>"
        "</revision_info></law_data_response>"
    )
    assert ea.current_revision_id_from_law_data(xml) == "337AC0000000066_20260521_505AC0000000003"


def test_current_revision_id_from_law_data_missing():
    """revision_info 欠落時は None (アンカー未特定→フォールバック)。"""
    import extract_amendments as ea

    assert ea.current_revision_id_from_law_data("<law_data_response/>") is None

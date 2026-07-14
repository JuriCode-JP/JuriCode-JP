"""配布物 leak スキャナのテスト.

Why 負のコントロールが要るか:
    2026-07-15 に `internal-doc-number` パターンを絞った。絞る変更は、放っておくと
    「検出が消えた」と「検査が仕事をしなくなった」の区別がつかなくなる。
    ここでは **本物の内部 doc 連番を今も検出すること** を固定する。
    以降パターンを触る人は、このテストを通さない限り「絞ってよい」と言えない。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# numpy は CI の dev 依存に含まれない (テストの .npy fixture 生成専用)。モジュール
# トップで import するとコレクションごと落ちるため、使う関数内で importorskip する
# (tools/embed/tests/test_retrieve_dedup.py と同じ規約)。scan_artifacts.py 本体は
# numpy 非依存 (.npy ヘッダを byte で解析) なので、この skip で本番挙動は変わらない。

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("scan_artifacts", _HERE.parent / "scan_artifacts.py")
assert _SPEC and _SPEC.loader
scan_artifacts = importlib.util.module_from_spec(_SPEC)
sys.modules["scan_artifacts"] = scan_artifacts
_SPEC.loader.exec_module(scan_artifacts)


def _scan(tmp_path: Path, text: str) -> list[str]:
    p = tmp_path / "artifact.jsonl"
    p.write_text(text, encoding="utf-8", newline="\n")
    _n, hits = scan_artifacts.scan_file(p)
    return [name for name, _line, _excerpt in hits]


# --- 負のコントロール: これらは今も検出されなければならない -------------------


@pytest.mark.parametrize(
    "line",
    [
        '{"note": "147_ClaudeCode_pasted_prompt"}',
        '{"note": "137_査読反映"}',
        '{"src": "/144_plan.md"}',
        '{"src": "docs\\\\150_measure.md"}',
    ],
)
def test_internal_doc_number_is_still_detected(tmp_path: Path, line: str) -> None:
    """パターンを絞ったあとも、本物の内部 doc 連番は検出し続ける."""
    assert "internal-doc-number" in _scan(tmp_path, line + "\n")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (r'{"p": "C:\\Users\\someone\\Documents\\x"}', "windows-abs-path"),
        ('{"p": "/mnt/c/repo"}', "posix-local-path"),
        ('{"author": "MasahiroSato"}', "person-name"),
        ('{"note": "business/plan.md"}', "internal-path"),
        ('{"k": "AIzaSyA1234567890abcdefghijklmnop"}', "google-api-key"),
        ('{"k": "hf_abcdefghijklmnopqrstuvwxyz0123"}', "hf-token"),
        ('{"k": "sk-abcdefghijklmnopqrstuvwxyz0123"}', "openai-key"),
        ('{"k": "AKIAIOSFODNN7EXAMPLE"}', "aws-key"),
        ('{"cfg": "api_key = 0123456789abcdefgh"}', "generic-secret-assign"),
        ('{"m": "someone@example.com"}', "private-email"),
        ('{"tool": "Cowork"}', "internal-tool-name"),
    ],
)
def test_each_pattern_fires_on_a_real_positive(tmp_path: Path, line: str, expected: str) -> None:
    """13 パターンのうち、正例を作れるものは全部発火することを固定する."""
    assert expected in _scan(tmp_path, line + "\n")


# --- 正のコントロール: 配布物の正当な内容を漏洩と呼ばない ---------------------


@pytest.mark.parametrize(
    "chunk_id",
    [
        "chihou-zei-hou-art-294_2-tbl1",  # 地方税法 294 条の 2
        "keiji-soshou-hou-art-494_2-tbl1",  # 刑事訴訟法 494 条の 2
        "houjin-zei-hou-art-144_3-tbl1",  # 法人税法 144 条の 3
        "yakkihou-shikoukisoku-art-218_2_4-tbl1",  # 薬機法施行規則 218 条の 2 の 4
    ],
)
def test_branch_article_ids_are_not_flagged(tmp_path: Path, chunk_id: str) -> None:
    """法令の枝番条 (数字 _ 数字) は内部 doc 連番ではない."""
    line = '{"chunk_id": "' + chunk_id + '"}'
    assert "internal-doc-number" not in _scan(tmp_path, line + "\n")


def test_scan_npy_proves_absence_of_text_by_size(tmp_path: Path) -> None:
    """.npy は文字列走査ではなくサイズ整合で「テキストの隙間ゼロ」を証明する."""
    np = pytest.importorskip("numpy")
    p = tmp_path / "index.npy"
    np.save(p, np.zeros((7, 5), dtype=np.float32))
    rows, hits = scan_artifacts.scan_npy(p)
    assert rows == 7
    assert hits == []


def test_scan_npy_reports_extra_bytes(tmp_path: Path) -> None:
    """payload の後ろに余分なバイトがあれば、それは走査すべき領域として報告する."""
    np = pytest.importorskip("numpy")
    p = tmp_path / "index.npy"
    np.save(p, np.zeros((7, 5), dtype=np.float32))
    with p.open("ab") as fh:
        fh.write(b"C:\\Users\\someone\\secret")
    _rows, hits = scan_artifacts.scan_npy(p)
    assert [name for name, _i, _e in hits] == ["npy-extra-bytes"]

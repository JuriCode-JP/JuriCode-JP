"""CLI --help smoke test for Tier 1+2 scripts (FU-505)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

TIER12_SCRIPTS = [
    "tools/parse/parse-egov.py",
    "tools/parse/v0.2/segment_parser.py",
    "tools/parse/verify.py",
    "tools/validate/validate-all.py",
    # manifest/cli.py uses relative imports and must be invoked via
    # `python -m manifest.cli`, not as a direct script. Excluded from
    # direct --help smoke test (FU-505).
    "tools/parse/v0.2/extract_kou_from_xml.py",
    "tools/parse/v0.2/extract_supplproviso_from_xml.py",
    "tools/parse/v0.2/add_rollup_chunks.py",
    "tools/finetune/generate-training-data.py",
    "tools/finetune/train-reranker.py",
    "tools/embed/convert-lawqa-to-evalset.py",
    "tools/embed/run-ablation.py",
    "tools/fetch-egov/bulk-ingest.py",
    "tools/search-ui/server.py",
    "tools/search-ui/anonymize-batch.py",
]


@pytest.mark.parametrize("script", TIER12_SCRIPTS)
def test_help_runs_without_crash(script: str) -> None:
    """`--help` should exit 0 with non-empty stdout under cp932 encoding.

    Why: subprocess の env= を指定すると現在の環境変数が完全に置換される.
    PATH や PYTHONPATH を絞ると sys.executable の resolve や内部呼び出し
    コマンドの解決に失敗するため、os.environ.copy() を base にして
    PYTHONIOENCODING のみ上書きする (外部レビュー指摘 2026-05-27 反映).

    Note: heavy import (torch / sentence-transformers / google-generativeai 等)
    を持つ script は依存パッケージ未 install 環境で ModuleNotFoundError に
    なる可能性あり. 個別 skip で対処 (FU-506 で Lazy Import 化により構造的
    解決予定).
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp932"
    # Ensure juricode_shared is importable even without pip install -e
    shared_src = str(REPO_ROOT / "tools" / "shared" / "src")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{shared_src}{os.pathsep}{existing_pp}" if existing_pp else shared_src

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), "--help"],
        capture_output=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, (
        f"{script} --help exited with {result.returncode}\n"
        f"stderr: {result.stderr.decode('utf-8', errors='replace')}"
    )
    assert result.stdout, f"{script} --help produced no stdout"

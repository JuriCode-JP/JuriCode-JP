#!/usr/bin/env python3
"""run-ci.py -- CI 全 9 ステップ + optional parity をローカルで 1 コマンド再現.

Why:
    push 前の CI 再現を「9 ステップ手動実行」に頼ると漏れる (PR #14 が em-dash
    混入で CI 赤・ローカルは ruff+pytest のみで PASS と誤認した前例)。本 runner は
    .github/workflows/ci.yml と同一順序・同一コマンドで全ステップを回し、cache/laws
    があれば本則 table chunks の parity も追加実行する (cache/laws 不在なら parity は
    自身で SKIP)。cross-platform (Windows native 開発で make 不在でも動く)。

使い方:
    python tools/scripts/run-ci.py
    終了コード 0 = 全 green、1 = いずれか fail (末尾 SUMMARY に内訳)。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # tools/scripts/run-ci.py -> repo root
PY = sys.executable
PYENV = {"PYTHONPATH": str(ROOT / "tools" / "shared" / "src")}


def run(name: str, argv: list[str], env: dict[str, str] | None = None) -> bool:
    """1 ステップを実行し PASS/FAIL を表示して bool を返す."""
    print(f"\n=== [{name}] {' '.join(argv)} ===", flush=True)
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(argv, cwd=ROOT, env=full_env)
    ok = result.returncode == 0
    print(f"--- [{name}] {'PASS' if ok else 'FAIL'} (exit {result.returncode}) ---", flush=True)
    return ok


def schema_drift() -> bool:
    """schema を IR から再生成し git diff で drift を検知 (CI step 9 相当)."""
    print("\n=== [schema-drift] export-schema + git diff --exit-code ===", flush=True)
    gen = subprocess.run([PY, "tools/shared/scripts/export-schema.py"], cwd=ROOT)
    if gen.returncode != 0:
        print("--- [schema-drift] FAIL (export-schema error) ---", flush=True)
        return False
    ok = True
    for schema in (
        "schema/juricode-article.schema.json",
        "schema/juricode-taxanswer.schema.json",
    ):
        diff = subprocess.run(["git", "diff", "--exit-code", schema], cwd=ROOT)
        if diff.returncode != 0:
            print(
                f"::error:: {schema} is out of sync with the Pydantic IR. "
                "Re-run export-schema.py and commit the result.",
                flush=True,
            )
            ok = False
    print(f"--- [schema-drift] {'PASS' if ok else 'FAIL'} ---", flush=True)
    return ok


def main() -> int:
    results: list[tuple[str, bool]] = []

    results.append(("ruff-check", run("ruff-check", [PY, "-m", "ruff", "check", "tools/"])))
    results.append(
        ("ruff-format", run("ruff-format", [PY, "-m", "ruff", "format", "--check", "tools/"]))
    )
    results.append(
        (
            "pytest",
            run(
                "pytest",
                [
                    PY,
                    "-m",
                    "pytest",
                    "tools/shared/tests",
                    "tools/validate/tests",
                    "tools/parse/v0.2/tests",
                    "tools/parse/v0.2/manifest/tests",
                    "tools/search-ui/tests",
                    "-q",
                ],
                env=PYENV,
            ),
        )
    )
    results.append(
        ("validate-all", run("validate-all", [PY, "tools/validate/validate-all.py"], env=PYENV))
    )
    results.append(
        (
            "verify-manifest",
            run("verify-manifest", [PY, "tools/parse/verify.py", "--path", "data"], env=PYENV),
        )
    )
    results.append(
        (
            "phase-tags",
            run(
                "phase-tags",
                [PY, "tools/scripts/fix-phase-tags.py", "--path", "data/v0.2", "--check-only"],
                env=PYENV,
            ),
        )
    )
    results.append(
        (
            "corpus-mapping",
            run(
                "corpus-mapping",
                [PY, "tools/embed/build-v0.2-corpus.py", "--validate-only"],
                env=PYENV,
            ),
        )
    )
    results.append(
        (
            "cp932-safe",
            run("cp932-safe", [PY, "tools/scripts/check-cp932-safe.py", "--path", "tools"]),
        )
    )
    results.append(("schema-drift", schema_drift()))
    # optional: 本則 table parity (cache/laws 不在なら script 側で SKIP し exit 0)
    results.append(
        (
            "table-parity",
            run("table-parity", [PY, "tools/parse/v0.2/verify_table_parity.py"], env=PYENV),
        )
    )

    print("\n==================== SUMMARY ====================", flush=True)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}", flush=True)
    failed = [name for name, ok in results if not ok]
    if failed:
        print(f"\n{len(failed)} step(s) FAILED: {', '.join(failed)}", flush=True)
        return 1
    print("\nALL GREEN", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

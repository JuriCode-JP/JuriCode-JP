"""test_fix_phase_tags_cli — fix-phase-tags.py CLI の smoke test.

Why:
  FU-415 で fix-phase-tags.py の `if __name__ == "__main__"` ブロックが
  欠落したまま commit され (commit ea8c6752), `python <script>` 実行が
  silently exit 0 する false guarantee を 2026-05-26 (FU-502 調査) に発見.
  本テストは Phase A 修復 (FU-504, entry point 追加) 後の退行を防ぐため、
  subprocess で実 CLI 起動を verify する.

  pure functions (juricode_shared.phase_tag) の unit test は別途
  test_phase_tag.py が担保. 本ファイルは driver が CLI として起動可能で
  あることを担保する役割.

責務:
  - `--check-only` mode で main() が呼ばれ、サマリが stdout に出ること
  - clean な corpus 状態で exit code 0 を返すこと
  - `--dry-run` mode で完走し、idempotent state メッセージが出ること

参照:
  - business/fu-502-investigation-2026-05-26.md §1, §5 Phase B
  - business/planning-checklist.md §1 (call graph 追跡), §2 (post-merge dry-run 自動化)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# tools/shared/tests/ → repo root は parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "scripts" / "fix-phase-tags.py"
DATA_V02 = REPO_ROOT / "data" / "v0.2"


def test_check_only_exits_zero_when_corpus_clean() -> None:
    """--check-only が現状 v0.2 corpus で exit 0 + サマリ出力を返すこと.

    Why:
      退行検知の guard が動作することを担保. main() が呼ばれずに
      silently exit 0 する状態 (FU-415 遺漏, FU-504 で修復) の再発を防止.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--path", str(DATA_V02), "--check-only"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"--check-only should exit 0 on clean corpus, got {result.returncode}.\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    # main() が実際に呼ばれていることを stdout の summary marker で verify.
    # silently exit 0 (entry point 欠落) だと stdout が空になる.
    assert "=== fix-phase-tags.py sweep summary" in result.stdout, (
        f"summary marker not in stdout — main() may not have been called.\nstdout:\n{result.stdout}"
    )
    assert "Total in-spec (tags[0] matches path):" in result.stdout
    assert "Total mismatches (would rewrite):" in result.stdout


def test_dry_run_runs_to_completion() -> None:
    """--dry-run が完走し、idempotent state メッセージを返すこと.

    Why:
      Phase A 修復後、--dry-run も同様に動作することを担保. --check-only
      とは別 mode (mode 分岐の網羅) であり、両方の path で main() が
      呼ばれることを test する.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--path", str(DATA_V02), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "=== fix-phase-tags.py sweep summary (DRY RUN) ===" in result.stdout
    # FU-415 sweep が反映済なら idempotent state.
    assert "Nothing to rewrite. (idempotent state)" in result.stdout, (
        f"idempotent state message not found.\nstdout:\n{result.stdout}"
    )


def test_help_runs_without_crash() -> None:
    """--help が exit 0 で動作すること (entry point の最小限の sanity check).

    Why:
      mode 引数 (--dry-run / --apply / --check-only) のいずれも指定せず
      --help だけで argparse のヘルプ出力 + exit 0 を確認. --check-only
      / --dry-run より軽量で、FU-504 修復の最小 verification として有用.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "--check-only" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--apply" in result.stdout

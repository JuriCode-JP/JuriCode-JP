"""test_build_v02_corpus_cli -- build-v0.2-corpus.py CLI の smoke test.

Why:
  FU-503 (--validate-only mode 追加 + CI 統合) で、main() の全 code path
  で `return 0/1` を明示する必要が生じた. Python の sys.exit(None) は exit 0
  になる仕様のため、return 漏れがあると FU-502/504 と同型の false-green
  guarantee を再発させる. レビュアー指摘 (2026-05-26) を踏まえ、3 層防御の
  Layer 2 (runtime smoke test) として subprocess で実 CLI 起動を verify する.

  pure functions の unit test (test_phase_tag.py 等) は別途存在. 本ファイル
  は driver が CLI として起動可能であることと、各 mode の exit code を
  担保する役割.

責務 (5 件):
  - test_validate_only_exits_zero_on_clean_corpus:
      --validate-only の happy path (実 data/v0.2 で exit 0 + summary marker).
  - test_validate_only_no_output_file:
      --validate-only 時に --output 指定があっても出力ファイル不作成.
  - test_validate_only_exits_one_on_missing_data_dir:
      --validate-only error path で exit 1 (false-green 防御の本丸).
  - test_help_runs_without_crash:
      --help が exit 0 + --validate-only 等が argparse に登録済.
  - test_merge_mode_exits_zero_with_minimal_fixture:
      既存 merge mode の exit 0 を **初めて runtime verify** (レビュー指摘).

参照:
  - business/fu-503-investigation-2026-05-26.md §6 Phase B, §12.2 Layer 2, §13
  - business/planning-checklist.md (call graph 追跡 + post-merge dry-run 自動化)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# tools/shared/tests/ -> repo root は parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "embed" / "build-v0.2-corpus.py"
DATA_V02 = REPO_ROOT / "data" / "v0.2"


def test_validate_only_exits_zero_on_clean_corpus() -> None:
    """--validate-only が現状 v0.2 corpus で exit 0 + Validate OK marker を返すこと.

    Why:
      Core: --validate-only の happy path. main() が return 0 を明示することと、
      _run_validate_only() が完走することを runtime verify. FU-502/504 で踏んだ
      silently exit 0 (entry point 欠落) と同型の事故を、本テストで防御.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--validate-only"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"--validate-only should exit 0 on clean corpus, got {result.returncode}.\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    # main() が実際に呼ばれていることを stderr の Validate OK marker で verify.
    # silently exit 0 (return 漏れ) だと stderr が空になる.
    assert "=== Validate OK ===" in result.stderr, (
        f"Validate OK marker not in stderr -- main() may not have been called.\n"
        f"stderr:\n{result.stderr}"
    )
    # phase mapping の最低限の sanity check (43 laws / 8 phases を期待).
    assert "law -> phase mapping:" in result.stderr
    assert "caption mapping:" in result.stderr


def test_validate_only_no_output_file(tmp_path: Path) -> None:
    """--validate-only 時に --output 指定があっても出力ファイルが作成されないこと.

    Why:
      副: --validate-only は read-only check であり、副作用なしを担保.
      ユーザが誤って --output を併用しても、想定外のファイル汚染を防ぐ.
    """
    out = tmp_path / "should-not-exist.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--validate-only",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert not out.exists(), (
        f"--output file should not be created in --validate-only mode, but {out} exists"
    )


def test_validate_only_exits_one_on_missing_data_dir(tmp_path: Path) -> None:
    """--validate-only で data dir 不在時に exit 1 + error メッセージを返すこと.

    Why:
      Core: false-green 防御の本丸. main() の error path (return 1) が
      正しく exit code に伝達されることを runtime verify. RET503 (Layer 1)
      は静的検査だが、本テストは runtime 担保.
    """
    nonexistent = tmp_path / "definitely-does-not-exist-v0.2"
    assert not nonexistent.exists()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--validate-only",
            "--data-dir",
            str(nonexistent),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1, (
        f"--validate-only should exit 1 on missing data dir, got {result.returncode}.\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    assert "data dir not found" in result.stderr


def test_help_runs_without_crash() -> None:
    """--help が exit 0 で動作し、--validate-only が登録されていること.

    Why:
      副: argparse entry point sanity check. FU-504 の Windows --help crash
      事故と同型の罠を回避する最小限の verification.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "--validate-only" in result.stdout
    assert "--augment" in result.stdout
    assert "--data-dir" in result.stdout


@pytest.fixture
def minimal_merge_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Merge mode を最小限の data/v0.2 + build/chunks/ で起動可能にする fixture.

    Why fragile でも残す:
      レビュアー指摘 (2026-05-26) を踏まえ、既存 merge mode の exit 0 を
      CI で **初めて** 担保する Layer 2 の核. main() の merge path 末尾に
      追加した `return 0` が正しく動作することを runtime verify する.
      fragility は許容 (chunk JSONL schema 変更で broken の可能性ありだが、
      その broken は corpus 全体への影響範囲確認の trigger になる独立価値).

    Returns:
        (data_dir, chunks_dir, out_file) のタプル.
    """
    # data/v0.2/phase1-foundational/kenpou/kenpou-article-1.md を minimal 構築
    data_dir = tmp_path / "data" / "v0.2"
    law_dir = data_dir / "phase1-foundational" / "kenpou"
    law_dir.mkdir(parents=True)
    (law_dir / "kenpou-article-1.md").write_text(
        "---\n"
        "law_id: 321CONSTITUTION0000001\n"
        "law_name_ja: 日本国憲法\n"
        "article_id: kenpou-art-1\n"
        "article_number: '1'\n"
        "---\n"
        "# 日本国憲法 第1条 (主権在民)\n本文\n",
        encoding="utf-8",
    )

    # build/chunks/kenpou/ に 1 chunk file を配置
    chunks_dir = tmp_path / "build" / "chunks" / "kenpou"
    chunks_dir.mkdir(parents=True)
    chunk_file = chunks_dir / "kenpou-article-1.chunks.jsonl"
    chunk_file.write_text(
        '{"id": "kenpou-art-1-p1", "segment_type": "simple", '
        '"text": "本文", "article_id": "kenpou-art-1", '
        '"law_id": "321CONSTITUTION0000001", "law_name_ja": "日本国憲法", '
        '"article_number": "1"}\n',
        encoding="utf-8",
    )

    out_file = tmp_path / "out.jsonl"
    return data_dir, chunks_dir.parent, out_file


def test_merge_mode_exits_zero_with_minimal_fixture(
    minimal_merge_fixture: tuple[Path, Path, Path],
) -> None:
    """Merge mode が minimal fixture で exit 0 を返すこと.

    Why:
      Core (レビュー指摘 2026-05-26): merge mode は本 PR まで CI で smoke
      test されたことがなく、exit code が正しく 0 を返すかが未検証だった.
      本 test で existing merge code path の exit code を初めて担保する.
      Layer 1 (RET503) は静的検査、Layer 2 (本 test) は runtime 担保.
    """
    data_dir, chunks_dir, out_file = minimal_merge_fixture

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--data-dir",
            str(data_dir),
            "--chunks-dir",
            str(chunks_dir),
            "--output",
            str(out_file),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"merge mode should exit 0 on minimal fixture, got {result.returncode}.\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    assert out_file.exists(), "merge output file should be created"
    # main() の merge path が完走したことを stderr summary marker で verify.
    assert "=== Merge summary ===" in result.stderr
    assert "Total chunks: 1" in result.stderr

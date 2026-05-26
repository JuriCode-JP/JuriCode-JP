#!/usr/bin/env python3
"""fix-phase-tags.py -- v0.2 corpus の tags[0] を path-derived phase に揃える sweep driver.

FU-415 実装. FU-401 以前の parse-egov.py がハードコードしていた tags[0]
= "phase1-police" が、phase1-police 以外の phase ディレクトリ配下の 7,468
ファイルに残存している. 本 driver はそれを path から導出した正しい phase
に書き換える.

責務 (バイブコーディング 3 原則 #1):
  ファイル走査 / I/O / 統計集計 / CLI / 進捗ログ のみ. 純関数ロジック
  (phase 抽出 / regex 置換) は juricode_shared.phase_tag に委譲.

実行モード (相互排他、いずれか必須):
  --dry-run    : 変更点をサマリ出力するが書き込まない.
  --apply      : safe_write_text 経由で atomic に書き込む.
  --check-only : mismatch が 1 件でもあれば exit 1 (CI 用). 書き込みも diff
                 出力もしない.

使用例:
  # 計画書 §1.3 の 7,468 件検出を確認.
  python tools/scripts/fix-phase-tags.py --path data/v0.2 --dry-run

  # 適用.
  python tools/scripts/fix-phase-tags.py --path data/v0.2 --apply

  # CI で mismatch ガード.
  python tools/scripts/fix-phase-tags.py --path data/v0.2 --check-only

参照:
  - business/fu-415-phase-tag-sweep-plan-2026-05-26.md
  - tools/shared/src/juricode_shared/phase_tag.py
  - docs/follow-ups.md FU-415
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# tools/shared/src を sys.path に追加.
_SHARED_SRC = Path(__file__).resolve().parent.parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared.phase_tag import (  # noqa: E402  (sys.path tweak 後)
    DEPRECATED_PHASE_TAG,
    resolve_phase_from_path,
    rewrite_tags0_in_text,
)
from juricode_shared.safe_write import safe_write_text  # noqa: E402

# -------------------------------------------------------------------------
# Result aggregation
# -------------------------------------------------------------------------


@dataclass(frozen=True)
class FileResult:
    """1 ファイル走査の結果. frozen で immutability 保証 (バイブコーディング #2).

    Why frozen=True:
        走査結果は集計用 snapshot で、生成後に変更されない. 不変性が
        担保されると後続の集計コードでバグが減る.
    """

    md_path: Path
    phase: str
    status: str  # 'ok' | 'mismatch' | 'skip_bom' | 'error'
    current_tag0: str | None = None  # mismatch / ok の時に値あり
    error_message: str | None = None  # error の時のみ


@dataclass
class SweepReport:
    """sweep 全体の統計.

    Why dataclass (not frozen):
        集計は driver 内で逐次累積する必要があるため frozen 化しない.
        累積後は read-only で扱う運用にとどめる.
    """

    files_scanned: int = 0
    files_ok: int = 0
    files_mismatch: int = 0
    files_skipped_bom: int = 0
    files_error: int = 0
    files_written: int = 0
    # 内訳: (phase_dir, abbrev) -> count of mismatches
    mismatch_by_law: dict[tuple[str, str], int] = field(default_factory=dict)
    # 内訳: (phase_dir, abbrev) -> current tag0 value (sweep 後の new_phase 推定用)
    mismatch_tag0: dict[tuple[str, str], str] = field(default_factory=dict)
    error_details: list[FileResult] = field(default_factory=list)


# -------------------------------------------------------------------------
# File walking
# -------------------------------------------------------------------------


def _iter_md_files(path: Path) -> Iterable[Path]:
    """指定パス配下の *.md を走査.

    Args:
        path: ディレクトリまたは単一 .md ファイル.

    Yields:
        ソート済 .md ファイル絶対パス (deterministic 走査順).

    Why sorted:
        実行ごとに同じ順序で走査することで、dry-run と apply の出力
        diff が安定する. CI / レビュー時のノイズ削減.
    """
    if path.is_file():
        if path.suffix == ".md":
            yield path.resolve()
        return
    if not path.is_dir():
        raise FileNotFoundError(f"path not found or not a file/dir: {path}")
    # sorted + rglob で deterministic な順序.
    yield from sorted(p.resolve() for p in path.rglob("*.md") if p.is_file())


# -------------------------------------------------------------------------
# Per-file scan
# -------------------------------------------------------------------------


def scan_one_file(
    md_path: Path,
    data_root: Path,
) -> FileResult:
    """1 ファイルを走査して FileResult を返す. 書き込みは行わない.

    Args:
        md_path: 対象 .md の絶対パス.
        data_root: corpus ルート (resolve_phase_from_path の基準).

    Returns:
        FileResult. status は 'ok' | 'mismatch' | 'skip_bom' | 'error'.

    Why exceptions を内部で捕捉して FileResult にするか:
        sweep は 11,758 ファイルを走査するので、1 件で OS-level 例外が
        出ても残りの走査を継続したい (ただし mid-sweep abort の判断は
        driver 側で別途行う).
    """
    try:
        expected_phase = resolve_phase_from_path(md_path, data_root)
    except ValueError as e:
        return FileResult(
            md_path=md_path,
            phase="?",
            status="error",
            error_message=f"resolve_phase_from_path: {e}",
        )

    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return FileResult(
            md_path=md_path,
            phase=expected_phase,
            status="error",
            error_message=f"read_text: {e}",
        )

    # rewrite_tags0_in_text を「pretend」で呼んで現状判定. 実書き込みは
    # 別ステージで行う (apply モード). dry-run / check-only ではここで止める.
    # _new_text は scan フェーズでは破棄. apply で再計算する (scan/apply 分離原則).
    try:
        _new_text, changed = rewrite_tags0_in_text(text, expected_phase)
    except ValueError as e:
        msg = str(e)
        if msg.startswith("[BOM_DETECTED]"):
            return FileResult(
                md_path=md_path,
                phase=expected_phase,
                status="skip_bom",
                error_message=msg,
            )
        return FileResult(
            md_path=md_path,
            phase=expected_phase,
            status="error",
            error_message=msg,
        )

    # current tag0 の推定: changed=False なら現状で正しい (expected_phase).
    # changed=True なら DEPRECATED_PHASE_TAG が現在値.
    current_tag0 = DEPRECATED_PHASE_TAG if changed else expected_phase

    return FileResult(
        md_path=md_path,
        phase=expected_phase,
        status="mismatch" if changed else "ok",
        current_tag0=current_tag0,
    )


# -------------------------------------------------------------------------
# Apply (write) phase
# -------------------------------------------------------------------------


def apply_one_file(md_path: Path, data_root: Path) -> tuple[bool, str | None]:
    """1 ファイルを実際に書き換える. atomic write (safe_write_text).

    Args:
        md_path: 対象 .md.
        data_root: corpus ルート.

    Returns:
        (wrote, error_message) のタプル.
        - wrote=True: 書き込み発生.
        - wrote=False: 既に正しい phase で書き換え不要 (idempotent).
        - error_message: 不正フォーマット検出時の ValueError メッセージ.

    Why scan と apply を分離するか:
        apply 中の例外で sweep が途中停止しても、既書き込みファイルは
        atomic write 済で個別整合性あり. 残件は git diff で範囲が可視化される.
    """
    expected_phase = resolve_phase_from_path(md_path, data_root)
    text = md_path.read_text(encoding="utf-8")
    try:
        new_text, changed = rewrite_tags0_in_text(text, expected_phase)
    except ValueError as e:
        return False, str(e)
    if not changed:
        return False, None
    safe_write_text(md_path, new_text)
    return True, None


# -------------------------------------------------------------------------
# Reporting
# -------------------------------------------------------------------------


def _print_summary(report: SweepReport, mode: str, *, verbose: bool = False) -> None:
    """サマリを stdout に出力.

    Why phase/law レベルで集計、ファイル名は --verbose のみ:
        7,468 件のファイル名を逐一 print すると stderr が膨張して
        本物のエラーが埋もれる. 集計レベルが既知事故 (FU-410) 対策.
    """
    label = {
        "dry-run": "DRY RUN",
        "apply": "APPLY",
        "check-only": "CHECK ONLY",
    }.get(mode, mode.upper())

    print(f"\n=== fix-phase-tags.py sweep summary ({label}) ===")
    print(f"Scanned: {report.files_scanned:,} files.")
    print()

    if report.mismatch_by_law:
        print("Mismatches by (phase_dir, law_abbrev):")
        for phase, abbrev in sorted(report.mismatch_by_law):
            n = report.mismatch_by_law[(phase, abbrev)]
            current = report.mismatch_tag0.get((phase, abbrev), "?")
            print(f"  {phase}/{abbrev:<40s} {n:>5} files   {current!r} -> {phase!r}")
        print()

    print(f"Total in-spec (tags[0] matches path):   {report.files_ok:>6,}")
    print(f"Total mismatches (would rewrite):       {report.files_mismatch:>6,}")
    print(f"Total skipped (BOM, FU-317):            {report.files_skipped_bom:>6,}")
    print(f"Total errors (manual review):           {report.files_error:>6,}")
    if mode == "apply":
        print(f"Total written (this run):               {report.files_written:>6,}")
    print()

    if report.error_details:
        print("=== Errors (manual review required) ===")
        for fr in report.error_details[:20]:
            print(f"  [ERROR] {fr.md_path}")
            print(f"      {fr.error_message}")
        if len(report.error_details) > 20:
            print(f"  ... and {len(report.error_details) - 20} more (use --verbose for all)")
        print()

    if verbose and report.error_details and len(report.error_details) > 20:
        print("=== All errors (verbose) ===")
        for fr in report.error_details:
            print(f"  [ERROR] {fr.md_path}\n      {fr.error_message}")


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    """CLI 引数定義."""
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--path",
        type=Path,
        required=True,
        help="走査対象 (ディレクトリ or 単一 .md). data_root の subset で可.",
    )
    ap.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/v0.2"),
        help="corpus ルート (default: data/v0.2). phase 抽出の基準.",
    )

    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="変更を出力するが書き込まない.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="safe_write_text で atomic に書き込む.",
    )
    mode.add_argument(
        "--check-only",
        action="store_true",
        help="mismatch があれば exit 1 (CI 用). 書き込みも diff 出力もしない.",
    )

    ap.add_argument(
        "--max-errors",
        type=int,
        default=50,
        help="エラー件数のハードリミット. 超過時は immediate abort (default: 50).",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="エラー全件詳細出力.",
    )
    return ap


def _build_report_from_scan(
    results: list[FileResult],
) -> SweepReport:
    """走査結果のリストから SweepReport を集計.

    Why 関数として分離:
        scan と集計が混在すると test しづらい. 純関数として SweepReport
        を返すことで集計ロジック単体テストが書きやすくなる.
    """
    report = SweepReport()
    report.files_scanned = len(results)
    for r in results:
        if r.status == "ok":
            report.files_ok += 1
        elif r.status == "mismatch":
            report.files_mismatch += 1
            key = (r.phase, r.md_path.parent.name)
            report.mismatch_by_law[key] = report.mismatch_by_law.get(key, 0) + 1
            report.mismatch_tag0[key] = r.current_tag0 or "?"
        elif r.status == "skip_bom":
            report.files_skipped_bom += 1
            report.error_details.append(r)
        elif r.status == "error":
            report.files_error += 1
            report.error_details.append(r)
    return report


def main() -> int:
    """エントリポイント. 戻り値 = process exit code."""
    args = _build_argparser().parse_args()

    if not args.path.exists():
        print(f"ERROR: --path not found: {args.path}", file=sys.stderr)
        return 2
    if not args.data_root.exists():
        print(f"ERROR: --data-root not found: {args.data_root}", file=sys.stderr)
        return 2

    # Phase 1: walk + scan (read-only).
    results: list[FileResult] = []
    error_count = 0
    for md_path in _iter_md_files(args.path):
        result = scan_one_file(md_path, args.data_root)
        results.append(result)
        if result.status == "error":
            error_count += 1
            print(
                f"[ERROR] {result.md_path}\n  {result.error_message}",
                file=sys.stderr,
            )
            if error_count >= args.max_errors:
                print(
                    f"\nABORT: error count {error_count} reached --max-errors limit "
                    f"({args.max_errors}). Stopping scan.",
                    file=sys.stderr,
                )
                break

    report = _build_report_from_scan(results)
    mode = "dry-run" if args.dry_run else ("apply" if args.apply else "check-only")

    # check-only モードは集計だけして exit.
    if args.check_only:
        _print_summary(report, mode, verbose=args.verbose)
        if report.files_mismatch > 0 or report.files_error > 0:
            print(
                f"FAIL: {report.files_mismatch} mismatches + "
                f"{report.files_error} errors (--check-only).",
                file=sys.stderr,
            )
            return 1
        return 0

    # dry-run モードはサマリ出力して exit.
    if args.dry_run:
        _print_summary(report, mode, verbose=args.verbose)
        if report.files_mismatch == 0:
            print("Nothing to rewrite. (idempotent state)")
        else:
            print(f"Re-run with --apply to write {report.files_mismatch:,} files.")
        return 0

    # apply モード: 実際に書き換える.
    assert args.apply
    if report.files_error > 0:
        print(
            f"\nABORT: {report.files_error} error(s) detected during scan. "
            f"Fix manually before --apply.",
            file=sys.stderr,
        )
        _print_summary(report, mode, verbose=args.verbose)
        return 1

    # 書き換えループ.
    apply_errors = 0
    for r in results:
        if r.status != "mismatch":
            continue
        try:
            wrote, err = apply_one_file(r.md_path, args.data_root)
        except Exception as e:  # driver の最終境界、ここで catch しないと sweep 全停止
            print(
                f"[APPLY_FAIL] {r.md_path}\n  {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            apply_errors += 1
            if apply_errors >= args.max_errors:
                print(
                    f"\nABORT: apply error count {apply_errors} reached "
                    f"--max-errors limit ({args.max_errors}).",
                    file=sys.stderr,
                )
                break
            continue
        if err is not None:
            print(f"[APPLY_FAIL] {r.md_path}\n  {err}", file=sys.stderr)
            apply_errors += 1
            if apply_errors >= args.max_errors:
                break
            continue
        if wrote:
            report.files_written += 1

    _print_summary(report, mode, verbose=args.verbose)
    if apply_errors > 0:
        print(f"\nWARNING: {apply_errors} file(s) failed to apply.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

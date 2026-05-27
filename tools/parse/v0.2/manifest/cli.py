"""cli -- argparse + 全 law_dir 走査 + main エントリポイント.

責務 (バイブコーディング 3 原則 #1):
  「コマンドライン引数を parse して、data/v0.2 配下の全 law_dir に対して
  assemble_law_manifest + write_law_manifest を呼ぶ」driver のみ.
  Pydantic モデル定義や hash 計算ロジックは含めない (それぞれ別 module へ).

実行例:
    cd /path/to/JuriCode-JP
    python -m manifest.cli \\
        --data-dir data/v0.2 \\
        --cache-dir cache/laws \\
        --parser-version "tools/parse/v0.2/segment_parser.py@0.1.0"

    # 上記が動かない場合 (ドット入りディレクトリ問題)、tools/parse/v0.2/ に
    # cd してから直接実行:
    cd tools/parse/v0.2
    python -m manifest.cli ...

Why `python -m manifest.cli` 形式:
    本パッケージは relative import (`from .article_entry import ...`) を
    使っているので、`python manifest/cli.py` 直接実行ではなく
    `python -m manifest.cli` 形式が必要. tests も同じ pattern.

走査ロジック:
    data_dir/{phase}/{law}/ を全列挙し、各 law_dir に対して:
      1. assemble_law_manifest(law_dir, cache_dir/{law_id}.xml, parser_version)
      2. write_law_manifest(manifest, law_dir/_source-manifest.json)

    既に _source-manifest.json が存在する場合は --force でのみ上書き
    (デフォルトは skip). v0.1 manifest との衝突防止.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .law_manifest import assemble_law_manifest, write_law_manifest

# Phase ディレクトリ名 pattern. data/v0.2/phase1-*/, data/v0.2/phase2-*/ 等.
# bulk-ingest.py の PHASE_MAP と同じ命名規約.
_PHASE_DIR_PATTERN = "phase*"


def _find_law_dirs(data_dir: Path) -> list[Path]:
    """data_dir/{phase}/{law}/ を全列挙して law_dir の list を返す.

    Args:
        data_dir: v0.2 corpus ルート (e.g. data/v0.2).

    Returns:
        law_dir の list. 順序は (phase_dir, law_dir) の string sort で stable.

    Why string sort:
        manifest 生成順を deterministic にすることで CI の log diff が安定し、
        後続の review/debug が容易になる.
    """
    law_dirs: list[Path] = []
    for phase_dir in sorted(data_dir.glob(_PHASE_DIR_PATTERN)):
        if not phase_dir.is_dir():
            continue
        for law_dir in sorted(phase_dir.iterdir()):
            if not law_dir.is_dir():
                continue
            # *-article-*.md が 1 件以上ある dir のみ法令ディレクトリと判定.
            if not any(law_dir.glob("*-article-*.md")):
                continue
            law_dirs.append(law_dir)
    return law_dirs


def _build_argparser() -> argparse.ArgumentParser:
    """CLI argparse 定義."""
    ap = argparse.ArgumentParser(
        description=(
            "Generate _source-manifest.json for v0.2 corpus. "
            "Walks data-dir/{phase}/{law}/ and creates a manifest per law_dir."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="v0.2 corpus root (e.g. data/v0.2).",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("cache/laws"),
        help="e-Gov XML cache dir (default: cache/laws/). XML 不在時は WARN のみで処理続行.",
    )
    ap.add_argument(
        "--parser-version",
        type=str,
        required=True,
        help=(
            "Parser version string written to manifest "
            "(e.g. 'tools/parse/v0.2/segment_parser.py@0.1.0')."
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="既存 _source-manifest.json を上書きする (default: skip).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="manifest を組み立てるが write しない (検証用).",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    """CLI driver.

    Args:
        argv: テスト用. None なら sys.argv[1:].

    Returns:
        Exit code (0 = 全 law_dir 成功, 1 = 1 件以上失敗).
    """
    args = _build_argparser().parse_args(argv)

    if not args.data_dir.exists():
        print(f"ERROR: --data-dir not found: {args.data_dir}", file=sys.stderr)
        return 2

    law_dirs = _find_law_dirs(args.data_dir)
    print(f"Found {len(law_dirs)} law_dir(s) under {args.data_dir}", file=sys.stderr)

    successes: list[Path] = []
    skips: list[Path] = []
    failures: list[tuple[Path, str]] = []

    for law_dir in law_dirs:
        manifest_path = law_dir / "_source-manifest.json"
        if manifest_path.exists() and not args.force:
            print(f"SKIP existing: {manifest_path}", file=sys.stderr)
            skips.append(law_dir)
            continue

        try:
            # XML path は law_id を assemble_law_manifest が知る前に組み立てる必要があるが、
            # _detect_law_metadata が law_id を返してくれるので、ここでは
            # 「ありえる位置 = cache_dir/{law_id}.xml」を後で対応させる.
            # 簡易にするため、cache_dir 配下から「対応 XML を 1 つ選ぶ」step を
            # _resolve_xml_path() に分離.
            xml_path = _resolve_xml_path(law_dir, args.cache_dir)
            manifest = assemble_law_manifest(
                law_dir=law_dir,
                xml_path=xml_path,
                parser_version=args.parser_version,
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"FAIL {law_dir}: {e}", file=sys.stderr)
            failures.append((law_dir, str(e)))
            continue

        if args.dry_run:
            print(f"DRY-RUN would write: {manifest_path} ({manifest.article_count} articles)")
        else:
            write_law_manifest(manifest, manifest_path)
            print(f"WROTE {manifest_path} ({manifest.article_count} articles)", file=sys.stderr)

        successes.append(law_dir)

    print(file=sys.stderr)
    print(
        f"=== Summary: {len(successes)} ok, {len(skips)} skip, {len(failures)} fail "
        f"(total {len(law_dirs)} law_dir(s)) ===",
        file=sys.stderr,
    )
    if failures:
        print(file=sys.stderr)
        print("Failures:", file=sys.stderr)
        for d, err in failures:
            print(f"  {d}: {err}", file=sys.stderr)
        return 1
    return 0


def _resolve_xml_path(law_dir: Path, cache_dir: Path) -> Path:
    """law_dir から law_id を読んで cache_dir/{law_id}.xml を返す.

    Why _detect_law_metadata と二重 IO を許容するか:
        assemble_law_manifest は law_id を自前で再取得する設計だが、CLI 層で
        XML path を渡す必要があるため事前に 1 度読む.
        2 重 IO は性能 cost より、責務分離 (cli が IO 取りまとめ、
        law_manifest が pure assembly) の方を優先.

    Returns:
        Path. XML 不在の場合でも存在チェックはしない (_compute_xml_sha256
        側で WARN 出力する).
    """
    import yaml

    first_md = next(law_dir.glob("*-article-*.md"), None)
    if first_md is None:
        # _find_law_dirs で *.md 1 件以上を確認済なので発生しないはず
        raise FileNotFoundError(f"No *.md in {law_dir}")

    text = first_md.read_text(encoding="utf-8")
    end_idx = text.find("\n---\n", 4)
    if end_idx < 0:
        raise ValueError(f"{first_md}: missing frontmatter closing delimiter")
    fm = yaml.safe_load(text[4:end_idx]) or {}
    law_id = fm.get("law_id")
    if not law_id:
        raise ValueError(f"{first_md}: frontmatter missing law_id")
    return cache_dir / f"{law_id}.xml"


if __name__ == "__main__":
    sys.exit(main())

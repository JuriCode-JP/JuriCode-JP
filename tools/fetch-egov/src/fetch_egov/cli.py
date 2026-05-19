"""fetch-egov CLI.

使い方:
    uv run fetch-egov get-law keihou
    uv run fetch-egov get-law 140AC0000000045
    uv run fetch-egov get-law keihou --at-date 2020-01-01
    uv run fetch-egov list-cached
    uv run fetch-egov clear-cache
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from pathlib import Path

import click

from fetch_egov import __version__
from fetch_egov.cache import FileCache
from fetch_egov.client import EGovClient
from fetch_egov.law_id_map import LAW_ID_MAP, resolve_law_id


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group(help="e-Gov 法令API v2 クライアント — JuriCode-JP のデータ取得層")
@click.version_option(version=__version__, prog_name="fetch-egov")
@click.option(
    "--cache-dir",
    type=click.Path(path_type=Path),
    default=Path("cache"),
    show_default=True,
    help="キャッシュディレクトリ.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="詳細ログを表示.",
)
@click.pass_context
def cli(ctx: click.Context, cache_dir: Path, verbose: bool) -> None:
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["cache"] = FileCache(cache_dir)


@cli.command("get-law", help="法令 XML を取得してキャッシュに保存.")
@click.argument("name_or_id", type=str)
@click.option(
    "--at-date",
    type=str,
    default=None,
    help="特定時点の取得(YYYY-MM-DD).例: 2020-01-01",
)
@click.option(
    "--force-refresh",
    is_flag=True,
    help="キャッシュを無視して再取得.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="標準出力ではなくファイルに保存.",
)
@click.pass_context
def get_law(
    ctx: click.Context,
    name_or_id: str,
    at_date: str | None,
    force_refresh: bool,
    output: Path | None,
) -> None:
    as_of: date | None = None
    if at_date:
        try:
            as_of = datetime.strptime(at_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise click.BadParameter(f"--at-date は YYYY-MM-DD 形式で: {at_date}") from exc

    cache: FileCache = ctx.obj["cache"]
    with EGovClient(cache=cache) as client:
        xml = client.get_law(name_or_id, asof=as_of, force_refresh=force_refresh)

    if output:
        output.write_text(xml, encoding="utf-8")
        click.echo(f"✅ {len(xml):,} chars → {output}", err=True)
    else:
        click.echo(xml)


@cli.command("list-cached", help="キャッシュ済みの法令一覧.")
@click.pass_context
def list_cached(ctx: click.Context) -> None:
    cache: FileCache = ctx.obj["cache"]
    laws = cache.list_cached_laws()
    if not laws:
        click.echo("(キャッシュは空です)", err=True)
        return
    for law_id in laws:
        click.echo(law_id)


@cli.command("clear-cache", help="キャッシュを全削除.")
@click.option("--yes", is_flag=True, help="確認をスキップ.")
@click.pass_context
def clear_cache(ctx: click.Context, yes: bool) -> None:
    if not yes:
        click.confirm("キャッシュを全削除しますか?", abort=True)
    cache: FileCache = ctx.obj["cache"]
    count = cache.clear()
    click.echo(f"✅ {count} ファイルを削除しました.", err=True)


@cli.command("list-abbrev", help="登録されている略称一覧.")
def list_abbrev() -> None:
    """略称 ↔ 法令ID マップを表示."""
    # 重複した law_id を避けて整理
    seen: dict[str, list[str]] = {}
    for abbrev, law_id in LAW_ID_MAP.items():
        seen.setdefault(law_id, []).append(abbrev)

    for law_id, abbrevs in sorted(seen.items()):
        click.echo(f"{law_id}\t{', '.join(abbrevs)}")


@cli.command("resolve", help="略称を法令IDに解決.")
@click.argument("name_or_id", type=str)
def resolve(name_or_id: str) -> None:
    try:
        resolved = resolve_law_id(name_or_id)
        click.echo(resolved)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()

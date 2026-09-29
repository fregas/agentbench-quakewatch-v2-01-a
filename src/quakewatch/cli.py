"""The ``quakewatch`` command line interface."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import click
from click.decorators import FC

from quakewatch import __version__
from quakewatch.cache import DEFAULT_CACHE_DIR, DEFAULT_TTL_SECONDS, ResponseCache
from quakewatch.export import FORMATS, format_for_path, write
from quakewatch.http import FetchError, HttpFetcher
from quakewatch.models import Event, Source, Window
from quakewatch.render import Output, render_events
from quakewatch.service import fetch_events, merge, resolve_sources
from quakewatch.sources import Query

WINDOWS = tuple(w.value for w in Window)
SOURCE_SELECTORS = ("usgs", "emsc", "both")


class Context:
    """State shared by every subcommand."""

    def __init__(self, cache: ResponseCache, plain: bool) -> None:
        self.cache = cache
        self.out = Output(force_plain=plain)


def parse_near(value: str | None) -> tuple[float, float] | None:
    """Parse a ``LAT,LON`` pair, raising :class:`click.BadParameter` if malformed."""
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 2:
        raise click.BadParameter("expected LAT,LON (for example 35.7,139.7)")
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        raise click.BadParameter("latitude and longitude must be numbers") from None
    if not -90.0 <= lat <= 90.0:
        raise click.BadParameter(f"latitude {lat} is outside -90..90")
    if not -180.0 <= lon <= 180.0:
        raise click.BadParameter(f"longitude {lon} is outside -180..180")
    return lat, lon


def build_query(
    window: str,
    min_mag: float | None,
    near: str | None,
    radius_km: float | None,
) -> Query:
    """Turn the shared CLI filter options into a :class:`Query`."""
    location = parse_near(near)
    if location is not None and radius_km is None:
        raise click.UsageError("--near also requires --radius-km")
    if radius_km is not None:
        if location is None:
            raise click.UsageError("--radius-km also requires --near")
        if radius_km <= 0:
            raise click.BadParameter("--radius-km must be greater than 0")
    return Query(
        window=Window(window),
        min_mag=min_mag,
        near=location,
        radius_km=radius_km,
    )


def collect(ctx: Context, query: Query, selector: str) -> dict[Source, list[Event]]:
    """Fetch ``query`` from the catalogs named by ``selector``."""
    sources = resolve_sources(selector)
    with HttpFetcher(cache=ctx.cache) as fetcher:
        return fetch_events(fetcher, query, sources)


# Shared filter options, applied to more than one subcommand. click's FC type
# var covers both a bare function and an already-built Command, which is what a
# stack of option decorators may be handed.
def filter_options(command: FC) -> FC:
    """Attach the ``--window``/``--min-mag``/``--near``/``--radius-km`` options."""
    options = [
        click.option(
            "--window",
            type=click.Choice(WINDOWS),
            default=Window.DAY.value,
            show_default=True,
            help="Rolling time window to query.",
        ),
        click.option(
            "--min-mag",
            type=float,
            default=None,
            help="Discard events below this magnitude.",
        ),
        click.option(
            "--near",
            type=str,
            default=None,
            metavar="LAT,LON",
            help="Keep only events near this point; requires --radius-km.",
        ),
        click.option(
            "--radius-km",
            type=float,
            default=None,
            help="Radius in km to use with --near.",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="quakewatch")
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_CACHE_DIR,
    show_default=True,
    help="Directory holding cached API responses.",
)
@click.option(
    "--cache-ttl",
    type=float,
    default=DEFAULT_TTL_SECONDS,
    show_default=True,
    help="Seconds a cached response stays fresh.",
)
@click.option("--no-cache", is_flag=True, help="Bypass the cache and always fetch.")
@click.option(
    "--plain",
    is_flag=True,
    help="Force plain output even on a terminal (the default off a TTY).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    cache_dir: Path,
    cache_ttl: float,
    no_cache: bool,
    plain: bool,
) -> None:
    """Monitor recent earthquakes from the USGS and EMSC catalogs."""
    ctx.obj = Context(
        cache=ResponseCache(directory=cache_dir, ttl=cache_ttl, enabled=not no_cache),
        plain=plain,
    )


@cli.command("list")
@filter_options
@click.option(
    "--source",
    type=click.Choice(SOURCE_SELECTORS),
    default="usgs",
    show_default=True,
    help="Which catalog(s) to query.",
)
@click.option("--limit", type=int, default=None, help="Show at most this many events.")
@click.pass_obj
def list_command(
    ctx: Context,
    window: str,
    min_mag: float | None,
    near: str | None,
    radius_km: float | None,
    source: str,
    limit: int | None,
) -> None:
    """List recent earthquakes."""
    query = build_query(window, min_mag, near, radius_km)
    events = merge(collect(ctx, query, source))
    if limit is not None:
        if limit <= 0:
            raise click.BadParameter("--limit must be greater than 0")
        events = events[:limit]
    render_events(
        events,
        ctx.out,
        title=f"{len(events)} events, past {window}, source={source}",
    )


@cli.command("export")
@filter_options
@click.option(
    "--source",
    type=click.Choice(SOURCE_SELECTORS),
    default="usgs",
    show_default=True,
    help="Which catalog(s) to query.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="File to write.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(FORMATS),
    default=None,
    help="Output format; inferred from the output file's extension if omitted.",
)
@click.pass_obj
def export_command(
    ctx: Context,
    window: str,
    min_mag: float | None,
    near: str | None,
    radius_km: float | None,
    source: str,
    output: Path,
    fmt: str | None,
) -> None:
    """Export recent earthquakes to CSV, JSON or GeoJSON."""
    resolved = fmt or format_for_path(output)
    if resolved is None:
        raise click.UsageError(
            f"cannot infer a format from {output.name!r}; pass --format "
            f"({'/'.join(FORMATS)})"
        )
    query = build_query(window, min_mag, near, radius_km)
    events = merge(collect(ctx, query, source))
    written = write(events, output, resolved)
    ctx.out.line(
        f"wrote {len(events)} events as {resolved} to {output} ({written} bytes)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: run the CLI and map failures to an exit status."""
    try:
        cli.main(args=list(argv) if argv is not None else None, standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("aborted", err=True)
        return 130
    except FetchError as exc:
        click.echo(f"error: {exc}", err=True)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())

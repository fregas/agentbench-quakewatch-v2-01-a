"""Output rendering: rich tables on a terminal, plain text everywhere else."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from rich.console import Console
from rich.table import Table

from quakewatch.compare import ComparisonReport
from quakewatch.models import Event

EVENT_HEADERS = ("time (UTC)", "mag", "depth km", "lat", "lon", "place", "source")

MATCH_HEADERS = (
    "time (UTC)",
    "usgs mag",
    "emsc mag",
    "d mag",
    "dt s",
    "dist km",
    "place",
)

SEPARATOR = "\t"

RIGHT_ALIGNED = {
    "mag",
    "depth km",
    "lat",
    "lon",
    "usgs mag",
    "emsc mag",
    "d mag",
    "dt s",
    "dist km",
}


def is_tty(stream: TextIO | None = None) -> bool:
    """Whether ``stream`` (default stdout) is an interactive terminal."""
    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - detached stream
        return False


class Output:
    """Writes either rich tables or plain tab-separated text.

    Plain mode bypasses rich altogether rather than configuring it to look
    plain: rich expands tabs to spaces and wraps long lines, which would make
    piped output unparseable by ``cut``/``awk``.
    """

    def __init__(self, stream: TextIO | None = None, force_plain: bool = False) -> None:
        self.stream: TextIO = stream if stream is not None else sys.stdout
        self.plain = force_plain or not is_tty(self.stream)
        self.console: Console | None = None if self.plain else Console(file=self.stream)

    def line(self, text: str = "") -> None:
        """Write one line of unadorned text."""
        self.stream.write(text + "\n")

    def row(self, cells: Sequence[str]) -> None:
        """Write one tab-separated record (plain mode only)."""
        self.line(SEPARATOR.join(cells))

    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        title: str | None = None,
    ) -> None:
        """Render a table, as rich or as tab-separated text."""
        if self.plain:
            if title is not None:
                self.line(title)
            self.row(headers)
            for cells in rows:
                self.row(cells)
            return

        assert self.console is not None  # narrowed by self.plain
        table = Table(title=title, header_style="bold", title_justify="left")
        for header in headers:
            table.add_column(
                header,
                justify="right" if header in RIGHT_ALIGNED else "left",
                overflow="fold",
            )
        for cells in rows:
            table.add_row(*cells)
        self.console.print(table)


def _event_cells(event: Event) -> tuple[str, ...]:
    return (
        event.time.strftime("%Y-%m-%d %H:%M:%S"),
        event.mag_display,
        event.depth_display,
        f"{event.lat:.3f}",
        f"{event.lon:.3f}",
        event.place,
        event.source.value,
    )


def render_events(events: Sequence[Event], out: Output, title: str | None = None) -> None:
    """Print an event listing."""
    if not events:
        out.line("no events matched")
        return
    out.table(EVENT_HEADERS, [_event_cells(e) for e in events], title=title)


def _fmt(value: float | None, spec: str = "+.2f") -> str:
    return "-" if value is None else format(value, spec)


def render_comparison(report: ComparisonReport, out: Output, limit: int = 20) -> None:
    """Print a comparison report: counts, magnitude stats, then the matches."""
    summary = [
        ("usgs events", str(report.usgs_total)),
        ("emsc events", str(report.emsc_total)),
        ("matched", str(report.matched_count)),
        ("usgs only", str(len(report.usgs_only))),
        ("emsc only", str(len(report.emsc_only))),
        ("mean mag diff (emsc-usgs)", _fmt(report.mean_mag_diff)),
        ("mean abs mag diff", _fmt(report.mean_abs_mag_diff, ".2f")),
        ("max abs mag diff", _fmt(report.max_abs_mag_diff, ".2f")),
    ]
    tolerance = (
        f"matching within +/-{report.time_tolerance_s:g}s "
        f"and {report.distance_tolerance_km:g} km"
    )
    out.table(("metric", "value"), summary, title=tolerance)

    if not report.matches:
        return

    rows = [
        (
            m.usgs.time.strftime("%Y-%m-%d %H:%M:%S"),
            m.usgs.mag_display,
            m.emsc.mag_display,
            _fmt(m.mag_diff),
            f"{m.dt_seconds:+.1f}",
            f"{m.distance_km:.1f}",
            m.usgs.place,
        )
        for m in report.matches[:limit]
    ]
    if out.plain:
        out.line()
    out.table(
        MATCH_HEADERS,
        rows,
        title=f"matched events (showing {len(rows)} of {report.matched_count})",
    )

    if report.matched_count > len(rows):
        out.line(f"... {report.matched_count - len(rows)} more matches not shown")

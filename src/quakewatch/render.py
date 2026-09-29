"""Output rendering: rich tables on a terminal, plain text everywhere else."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from rich.console import Console
from rich.table import Table

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

RIGHT_ALIGNED = {"mag", "depth km", "lat", "lon"}


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

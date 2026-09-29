"""Fetching across one or both catalogs."""

from __future__ import annotations

from quakewatch.http import HttpFetcher
from quakewatch.models import Event, Source
from quakewatch.sources import EmscSource, EventSource, Query, UsgsSource

SOURCES_FOR_SELECTOR: dict[str, tuple[Source, ...]] = {
    "usgs": (Source.USGS,),
    "emsc": (Source.EMSC,),
    "both": (Source.USGS, Source.EMSC),
}


def build_source(source: Source) -> EventSource:
    """The adapter for ``source``."""
    return UsgsSource() if source is Source.USGS else EmscSource()


def resolve_sources(selector: str) -> tuple[Source, ...]:
    """Expand a ``--source`` selector into the catalogs it names."""
    try:
        return SOURCES_FOR_SELECTOR[selector.lower()]
    except KeyError:
        raise ValueError(f"unknown source selector {selector!r}") from None


def fetch_events(
    fetcher: HttpFetcher, query: Query, sources: tuple[Source, ...]
) -> dict[Source, list[Event]]:
    """Fetch ``query`` from each of ``sources``, keyed by catalog."""
    return {source: build_source(source).fetch(fetcher, query) for source in sources}


def merge(results: dict[Source, list[Event]]) -> list[Event]:
    """Flatten per-source results into one newest-first list."""
    merged = [event for events in results.values() for event in events]
    return sorted(merged, reverse=True)

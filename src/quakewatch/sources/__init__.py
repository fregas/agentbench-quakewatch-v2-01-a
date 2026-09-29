"""Adapters that turn upstream catalog payloads into :class:`~quakewatch.models.Event`."""

from __future__ import annotations

from quakewatch.sources.base import EventSource, Query
from quakewatch.sources.emsc import EmscSource
from quakewatch.sources.usgs import UsgsSource

__all__ = ["EmscSource", "EventSource", "Query", "UsgsSource", "get_source"]


def get_source(name: str) -> EventSource:
    """Return the adapter registered under ``name``."""
    sources: dict[str, type[EventSource]] = {
        "usgs": UsgsSource,
        "emsc": EmscSource,
    }
    try:
        return sources[name.lower()]()
    except KeyError:
        raise ValueError(f"unknown source {name!r}") from None

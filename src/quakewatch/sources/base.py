"""The contract every source adapter implements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from quakewatch.http import HttpFetcher
from quakewatch.models import Event, Source, Window


@dataclass(frozen=True)
class Query:
    """The filters a caller asked for, in source-independent terms."""

    window: Window = Window.DAY
    min_mag: float | None = None
    near: tuple[float, float] | None = None
    radius_km: float | None = None
    now: datetime | None = None

    def matches(self, event: Event) -> bool:
        """Whether ``event`` satisfies every filter in this query.

        Sources push what they can upstream, but the feeds differ in which
        filters they support, so every result is re-checked locally to keep
        ``usgs`` and ``emsc`` answering the same question.
        """
        if event.time < self.window.start(self.now):
            return False
        if self.min_mag is not None and (
            event.magnitude is None or event.magnitude < self.min_mag
        ):
            return False
        if self.near is None or self.radius_km is None:
            return True
        return event.distance_km(*self.near) <= self.radius_km


class EventSource(Protocol):
    """A catalog that can be queried for recent events."""

    name: Source

    def fetch(self, fetcher: HttpFetcher, query: Query) -> list[Event]:
        """Return the events matching ``query``, sorted newest first."""
        ...

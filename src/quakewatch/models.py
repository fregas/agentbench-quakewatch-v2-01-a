"""The normalized event model shared by every data source."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class Source(str, Enum):
    """A supported upstream catalog."""

    USGS = "usgs"
    EMSC = "emsc"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Window(str, Enum):
    """The rolling time window a query covers."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def delta(self) -> timedelta:
        """The window's length as a :class:`~datetime.timedelta`."""
        return {
            Window.HOUR: timedelta(hours=1),
            Window.DAY: timedelta(days=1),
            Window.WEEK: timedelta(days=7),
        }[self]

    def start(self, now: datetime | None = None) -> datetime:
        """The UTC instant this window begins, relative to ``now``."""
        return (now or utcnow()) - self.delta


def utcnow() -> datetime:
    """The current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, order=True)
class Event:
    """One seismic event, normalized across sources.

    Instances sort by ``time`` first so that merged result sets come out in
    chronological order without an explicit key.
    """

    time: datetime
    id: str
    magnitude: float | None
    depth_km: float | None
    lat: float
    lon: float
    place: str
    source: Source

    def __post_init__(self) -> None:
        if self.time.tzinfo is None:
            raise ValueError(f"event {self.id!r} has a naive timestamp")

    @property
    def mag_display(self) -> str:
        """The magnitude formatted for display, or ``"-"`` when unknown."""
        return "-" if self.magnitude is None else f"{self.magnitude:.1f}"

    @property
    def depth_display(self) -> str:
        """The depth formatted for display, or ``"-"`` when unknown."""
        return "-" if self.depth_km is None else f"{self.depth_km:.1f}"

    def distance_km(self, lat: float, lon: float) -> float:
        """Great-circle distance from this event's epicenter to ``lat``/``lon``."""
        return haversine_km(self.lat, self.lon, lat, lon)


EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))

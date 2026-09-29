"""Cross-matching the USGS and EMSC catalogs."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean

from quakewatch.models import Event, haversine_km

DEFAULT_TIME_TOLERANCE_S = 60.0
DEFAULT_DISTANCE_TOLERANCE_KM = 50.0


@dataclass(frozen=True)
class Match:
    """One event reported by both catalogs."""

    usgs: Event
    emsc: Event

    @property
    def dt_seconds(self) -> float:
        """Signed origin-time difference, EMSC minus USGS, in seconds."""
        return (self.emsc.time - self.usgs.time).total_seconds()

    @property
    def distance_km(self) -> float:
        """Epicenter separation between the two solutions."""
        return haversine_km(self.usgs.lat, self.usgs.lon, self.emsc.lat, self.emsc.lon)

    @property
    def mag_diff(self) -> float | None:
        """Signed magnitude difference, EMSC minus USGS, if both reported one."""
        if self.usgs.magnitude is None or self.emsc.magnitude is None:
            return None
        return self.emsc.magnitude - self.usgs.magnitude


@dataclass
class ComparisonReport:
    """The outcome of cross-matching two catalogs."""

    matches: list[Match] = field(default_factory=list)
    usgs_only: list[Event] = field(default_factory=list)
    emsc_only: list[Event] = field(default_factory=list)
    time_tolerance_s: float = DEFAULT_TIME_TOLERANCE_S
    distance_tolerance_km: float = DEFAULT_DISTANCE_TOLERANCE_KM

    @property
    def matched_count(self) -> int:
        """How many events both catalogs reported."""
        return len(self.matches)

    @property
    def usgs_total(self) -> int:
        """How many events USGS reported in the window."""
        return len(self.matches) + len(self.usgs_only)

    @property
    def emsc_total(self) -> int:
        """How many events EMSC reported in the window."""
        return len(self.matches) + len(self.emsc_only)

    @property
    def mag_diffs(self) -> list[float]:
        """Every signed magnitude difference among the matches."""
        return [m.mag_diff for m in self.matches if m.mag_diff is not None]

    @property
    def mean_mag_diff(self) -> float | None:
        """Mean signed magnitude difference (EMSC - USGS), if any exist."""
        diffs = self.mag_diffs
        return fmean(diffs) if diffs else None

    @property
    def mean_abs_mag_diff(self) -> float | None:
        """Mean absolute magnitude difference, if any exist."""
        diffs = self.mag_diffs
        return fmean(abs(d) for d in diffs) if diffs else None

    @property
    def max_abs_mag_diff(self) -> float | None:
        """The largest absolute magnitude disagreement, if any exist."""
        diffs = self.mag_diffs
        return max((abs(d) for d in diffs), default=None) if diffs else None


def compare(
    usgs_events: list[Event],
    emsc_events: list[Event],
    time_tolerance_s: float = DEFAULT_TIME_TOLERANCE_S,
    distance_tolerance_km: float = DEFAULT_DISTANCE_TOLERANCE_KM,
) -> ComparisonReport:
    """Match events reported by both catalogs.

    Two events pair up when their origin times are within ``time_tolerance_s``
    and their epicenters within ``distance_tolerance_km``. Candidates are
    considered nearest-first (by time, then distance) and each event is used at
    most once, so a dense sequence of aftershocks does not produce duplicate
    pairings.
    """
    candidates: list[tuple[float, float, int, int]] = []
    for i, usgs in enumerate(usgs_events):
        for j, emsc in enumerate(emsc_events):
            dt = abs((emsc.time - usgs.time).total_seconds())
            if dt > time_tolerance_s:
                continue
            distance = haversine_km(usgs.lat, usgs.lon, emsc.lat, emsc.lon)
            if distance > distance_tolerance_km:
                continue
            candidates.append((dt, distance, i, j))

    candidates.sort()
    used_usgs: set[int] = set()
    used_emsc: set[int] = set()
    matches: list[Match] = []
    for _dt, _distance, i, j in candidates:
        if i in used_usgs or j in used_emsc:
            continue
        used_usgs.add(i)
        used_emsc.add(j)
        matches.append(Match(usgs=usgs_events[i], emsc=emsc_events[j]))

    matches.sort(key=lambda m: m.usgs.time, reverse=True)
    return ComparisonReport(
        matches=matches,
        usgs_only=[e for i, e in enumerate(usgs_events) if i not in used_usgs],
        emsc_only=[e for j, e in enumerate(emsc_events) if j not in used_emsc],
        time_tolerance_s=time_tolerance_s,
        distance_tolerance_km=distance_tolerance_km,
    )

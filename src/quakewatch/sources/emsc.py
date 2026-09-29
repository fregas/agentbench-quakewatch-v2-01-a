"""The EMSC FDSN event service.

https://www.seismicportal.eu/fdsn-wsevent.html
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from quakewatch.http import FetchError, HttpFetcher
from quakewatch.models import Event, Source
from quakewatch.sources.base import Query
from quakewatch.sources.usgs import _as_float

QUERY_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"

# The service caps a single response; the summary-scale windows quakewatch
# offers stay well inside this, and the limit keeps a bad query bounded.
MAX_EVENTS = 1000


class EmscSource:
    """Reads the EMSC FDSN ``query`` endpoint in ``format=json`` mode."""

    name = Source.EMSC

    def params(self, query: Query) -> dict[str, Any]:
        """Build the FDSN query string for ``query``.

        Unlike USGS's fixed summary feeds, FDSN takes the filters directly, so
        the time window, magnitude floor and radius are all pushed upstream.
        """
        params: dict[str, Any] = {
            "format": "json",
            "starttime": _fdsn_time(query.window.start(query.now)),
            "limit": MAX_EVENTS,
            "orderby": "time",
        }
        if query.min_mag is not None:
            params["minmag"] = query.min_mag
        if query.near is not None and query.radius_km is not None:
            lat, lon = query.near
            params["lat"] = lat
            params["lon"] = lon
            # FDSN radii are in degrees; 1 degree of latitude is ~111.195 km.
            params["maxradius"] = query.radius_km / 111.195
        return params

    def fetch(self, fetcher: HttpFetcher, query: Query) -> list[Event]:
        """Fetch and normalize the events matching ``query``."""
        payload = fetcher.get_json(QUERY_URL, self.params(query))
        if payload is None:
            # EMSC answers an empty result set with 204 No Content.
            return []
        events = [e for e in self.parse(payload) if query.matches(e)]
        return sorted(events, reverse=True)

    def parse(self, payload: Any) -> list[Event]:
        """Normalize an EMSC FeatureCollection into events."""
        if not isinstance(payload, dict):
            raise FetchError("EMSC response was not a GeoJSON object")
        features = payload.get("features")
        if not isinstance(features, list):
            raise FetchError("EMSC response had no 'features' array")
        events = []
        for feature in features:
            event = self._parse_feature(feature)
            if event is not None:
                events.append(event)
        return events

    def _parse_feature(self, feature: Any) -> Event | None:
        if not isinstance(feature, dict):
            return None
        props = feature.get("properties")
        if not isinstance(props, dict):
            return None
        event_id = feature.get("id") or props.get("unid")
        time_raw = props.get("time")
        if not isinstance(event_id, str) or not isinstance(time_raw, str):
            return None
        when = _parse_time(time_raw)
        if when is None:
            return None

        lat, lon = _as_float(props.get("lat")), _as_float(props.get("lon"))
        if lat is None or lon is None:
            geometry = feature.get("geometry")
            if isinstance(geometry, dict):
                coords = geometry.get("coordinates")
                if isinstance(coords, list) and len(coords) >= 2:
                    lon, lat = _as_float(coords[0]), _as_float(coords[1])
        if lat is None or lon is None:
            return None

        # properties.depth is already positive-down km, whereas the geometry's
        # third coordinate is negative (metres below the datum, sign-flipped).
        depth = _as_float(props.get("depth"))
        if depth is not None:
            depth = abs(depth)

        return Event(
            id=f"emsc:{event_id}",
            time=when,
            magnitude=_as_float(props.get("mag")),
            depth_km=depth,
            lat=lat,
            lon=lon,
            place=str(props.get("flynn_region") or "unknown"),
            source=Source.EMSC,
        )


def _fdsn_time(value: datetime) -> str:
    """Format a datetime the way the FDSN spec wants it (UTC, no offset)."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


_FRACTION = re.compile(r"\.(\d+)")


def _parse_time(raw: str) -> datetime | None:
    """Parse an EMSC ISO-8601 timestamp.

    EMSC suffixes times with ``Z`` and emits fractional seconds at whatever
    precision it happens to have (``:40.0Z``, ``:51.496552Z``). Python 3.10's
    ``fromisoformat`` accepts only 3 or 6 fractional digits, so the fraction is
    padded to microseconds before parsing.
    """
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), text, count=1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # FDSN times are UTC by definition even when unsuffixed.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

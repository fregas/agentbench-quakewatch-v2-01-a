"""The USGS GeoJSON summary feeds.

https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from quakewatch.http import FetchError, HttpFetcher
from quakewatch.models import Event, Source, Window
from quakewatch.sources.base import Query

FEED_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"

# The summary feeds are pre-baked per window; there are no query parameters, so
# every filter other than the window is applied locally.
FEED_FOR_WINDOW = {
    Window.HOUR: "all_hour.geojson",
    Window.DAY: "all_day.geojson",
    Window.WEEK: "all_week.geojson",
}


class UsgsSource:
    """Reads the ``all_<window>`` USGS GeoJSON summary feed."""

    name = Source.USGS

    def feed_url(self, window: Window) -> str:
        """The summary feed URL covering ``window``."""
        return f"{FEED_BASE}/{FEED_FOR_WINDOW[window]}"

    def fetch(self, fetcher: HttpFetcher, query: Query) -> list[Event]:
        """Fetch and normalize the feed for ``query.window``."""
        payload = fetcher.get_json(self.feed_url(query.window))
        if payload is None:
            return []
        events = [e for e in self.parse(payload) if query.matches(e)]
        return sorted(events, reverse=True)

    def parse(self, payload: Any) -> list[Event]:
        """Normalize a USGS FeatureCollection into events."""
        if not isinstance(payload, dict):
            raise FetchError("USGS feed was not a GeoJSON object")
        features = payload.get("features")
        if not isinstance(features, list):
            raise FetchError("USGS feed had no 'features' array")
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
        geometry = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            return None
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            return None
        event_id = feature.get("id")
        epoch_ms = props.get("time")
        if not isinstance(event_id, str) or not isinstance(epoch_ms, (int, float)):
            return None

        lon, lat = _as_float(coords[0]), _as_float(coords[1])
        if lon is None or lat is None:
            return None
        # USGS reports depth as the third coordinate, positive-down, in km.
        depth = _as_float(coords[2]) if len(coords) > 2 else None

        return Event(
            id=f"usgs:{event_id}",
            time=datetime.fromtimestamp(float(epoch_ms) / 1000.0, tz=timezone.utc),
            magnitude=_as_float(props.get("mag")),
            depth_km=depth,
            lat=lat,
            lon=lon,
            place=str(props.get("place") or "unknown"),
            source=Source.USGS,
        )


def _as_float(value: Any) -> float | None:
    """Coerce a JSON scalar to ``float``, mapping anything unusable to ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None

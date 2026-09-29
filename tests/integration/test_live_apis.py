"""Integration tests that hit the real USGS and EMSC services.

Marked ``integration`` and deselected by default; run with ``pytest -m
integration``. They assert on shape and invariants rather than on specific
events, because the feeds change continuously.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timezone
from pathlib import Path

import pytest

from quakewatch.cache import ResponseCache
from quakewatch.export import render
from quakewatch.http import HttpFetcher
from quakewatch.models import Event, Source, Window, utcnow
from quakewatch.service import fetch_events, merge, resolve_sources
from quakewatch.sources import EmscSource, Query, UsgsSource

pytestmark = pytest.mark.integration


@pytest.fixture
def live_fetcher(tmp_path: Path) -> Iterator[HttpFetcher]:
    """A fetcher with a throwaway cache, so each run really hits the network."""
    with HttpFetcher(cache=ResponseCache(directory=tmp_path / "cache")) as fetcher:
        yield fetcher


def assert_sane(event: Event, source: Source) -> None:
    assert event.source is source
    assert event.id.startswith(f"{source.value}:")
    assert event.time.tzinfo is timezone.utc
    assert -90.0 <= event.lat <= 90.0
    assert -180.0 <= event.lon <= 180.0
    assert event.place
    if event.magnitude is not None:
        assert -2.0 <= event.magnitude <= 10.0
    if event.depth_km is not None:
        assert -5.0 <= event.depth_km <= 800.0


def test_usgs_day_feed_is_live(live_fetcher: HttpFetcher) -> None:
    events = UsgsSource().fetch(live_fetcher, Query(window=Window.DAY))
    assert events, "the USGS all_day feed is never empty in practice"
    for event in events:
        assert_sane(event, Source.USGS)


def test_usgs_events_fall_inside_the_requested_window(live_fetcher: HttpFetcher) -> None:
    now = utcnow()
    events = UsgsSource().fetch(live_fetcher, Query(window=Window.HOUR, now=now))
    for event in events:
        assert event.time >= Window.HOUR.start(now)


def test_emsc_week_feed_is_live(live_fetcher: HttpFetcher) -> None:
    events = EmscSource().fetch(live_fetcher, Query(window=Window.WEEK, min_mag=4.0))
    assert events, "there is always an M4+ event somewhere in a week"
    for event in events:
        assert_sane(event, Source.EMSC)
        assert event.magnitude is not None and event.magnitude >= 4.0


def test_emsc_204_on_an_impossible_filter(live_fetcher: HttpFetcher) -> None:
    """EMSC answers an empty result set with 204 No Content, not an empty feed."""
    events = EmscSource().fetch(live_fetcher, Query(window=Window.HOUR, min_mag=9.5))
    assert events == []


def test_radius_filter_against_a_live_query(live_fetcher: HttpFetcher) -> None:
    tokyo = (35.68, 139.69)
    events = EmscSource().fetch(
        live_fetcher, Query(window=Window.WEEK, near=tokyo, radius_km=500.0)
    )
    for event in events:
        assert event.distance_km(*tokyo) <= 500.0


def test_cache_prevents_a_second_request(tmp_path: Path) -> None:
    cache = ResponseCache(directory=tmp_path / "cache", ttl=600.0)
    url = UsgsSource().feed_url(Window.HOUR)
    with HttpFetcher(cache=cache) as fetcher:
        first = fetcher.get_json(url)
        assert cache.get(cache.key(url)) is not None
        assert fetcher.get_json(url) == first
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


def test_live_events_export_cleanly(live_fetcher: HttpFetcher) -> None:
    events = merge(
        fetch_events(
            live_fetcher, Query(window=Window.DAY, min_mag=4.5), resolve_sources("both")
        )
    )
    assert events
    assert json.loads(render(events, "geojson"))["type"] == "FeatureCollection"
    assert len(json.loads(render(events, "json"))) == len(events)
    assert len(render(events, "csv").strip().splitlines()) == len(events) + 1

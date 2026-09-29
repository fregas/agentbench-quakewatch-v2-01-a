from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from quakewatch.cache import ResponseCache
from quakewatch.http import HttpFetcher
from quakewatch.models import Event, Source
from quakewatch.sources.emsc import QUERY_URL
from quakewatch.sources.usgs import FEED_BASE

FIXTURES = Path(__file__).parent / "fixtures"

USGS_DAY_URL = f"{FEED_BASE}/all_day.geojson"
EMSC_URL = QUERY_URL


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def usgs_payload() -> Any:
    """The recorded USGS all_day summary feed."""
    return load_fixture("usgs_all_day.json")


@pytest.fixture
def emsc_payload() -> Any:
    """The recorded EMSC FDSN query response."""
    return load_fixture("emsc_query.json")


@pytest.fixture
def fixture_now(usgs_payload: Any) -> datetime:
    """A 'now' just after the newest event in the recorded fixtures.

    The fixtures are frozen in the past, so tests that exercise the rolling
    window filters pin the clock to the moment the fixtures were recorded.
    """
    newest = max(f["properties"]["time"] for f in usgs_payload["features"])
    return datetime.fromtimestamp(newest / 1000.0, tz=timezone.utc) + timedelta(minutes=1)


@pytest.fixture
def cache(tmp_path: Path) -> ResponseCache:
    """A cache rooted in a throwaway directory."""
    return ResponseCache(directory=tmp_path / "cache", ttl=300.0)


@pytest.fixture
def fetcher(cache: ResponseCache) -> HttpFetcher:
    """A fetcher whose cache is isolated per test."""
    return HttpFetcher(cache=cache)


def make_event(
    *,
    id: str = "test:1",
    time: datetime | None = None,
    magnitude: float | None = 5.0,
    depth_km: float | None = 10.0,
    lat: float = 0.0,
    lon: float = 0.0,
    place: str = "nowhere",
    source: Source = Source.USGS,
) -> Event:
    """Build an event, defaulting every field to something harmless."""
    return Event(
        id=id,
        time=time or datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc),
        magnitude=magnitude,
        depth_km=depth_km,
        lat=lat,
        lon=lon,
        place=place,
        source=source,
    )

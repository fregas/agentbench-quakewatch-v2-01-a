from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import respx

from quakewatch.http import FetchError, HttpFetcher
from quakewatch.models import Source, Window
from quakewatch.sources import EmscSource, Query, UsgsSource, get_source
from quakewatch.sources.emsc import _parse_time
from quakewatch.sources.usgs import _as_float
from tests.conftest import EMSC_URL, USGS_DAY_URL, make_event


def test_get_source_by_name() -> None:
    assert isinstance(get_source("usgs"), UsgsSource)
    assert isinstance(get_source("EMSC"), EmscSource)


def test_get_source_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        get_source("iris")


@pytest.mark.parametrize(
    ("window", "filename"),
    [
        (Window.HOUR, "all_hour.geojson"),
        (Window.DAY, "all_day.geojson"),
        (Window.WEEK, "all_week.geojson"),
    ],
)
def test_usgs_feed_url_per_window(window: Window, filename: str) -> None:
    assert UsgsSource().feed_url(window).endswith(filename)


# --- USGS parsing ---------------------------------------------------------


def test_usgs_parses_recorded_fixture(usgs_payload: Any) -> None:
    events = UsgsSource().parse(usgs_payload)
    assert len(events) == len(usgs_payload["features"])
    for event in events:
        assert event.source is Source.USGS
        assert event.id.startswith("usgs:")
        assert event.time.tzinfo is timezone.utc
        assert -90 <= event.lat <= 90
        assert -180 <= event.lon <= 180


def test_usgs_maps_fields_from_a_known_feature() -> None:
    payload = {
        "features": [
            {
                "id": "nc75444517",
                "properties": {
                    "mag": 0.67,
                    "place": "10 km WNW of The Geysers, CA",
                    "time": 1790712570030,
                },
                "geometry": {"type": "Point", "coordinates": [-122.83, 38.82, 2.1]},
            }
        ]
    }
    (event,) = UsgsSource().parse(payload)
    assert event.id == "usgs:nc75444517"
    assert event.magnitude == pytest.approx(0.67)
    assert event.depth_km == pytest.approx(2.1)
    assert event.lat == pytest.approx(38.82)
    assert event.lon == pytest.approx(-122.83)
    assert event.place == "10 km WNW of The Geysers, CA"
    assert event.time == datetime(2026, 9, 29, 20, 9, 30, 30000, tzinfo=timezone.utc)


def test_usgs_tolerates_null_magnitude_and_missing_place() -> None:
    payload = {
        "features": [
            {
                "id": "x1",
                "properties": {"mag": None, "place": None, "time": 0},
                "geometry": {"coordinates": [1.0, 2.0, 3.0]},
            }
        ]
    }
    (event,) = UsgsSource().parse(payload)
    assert event.magnitude is None
    assert event.place == "unknown"


def test_usgs_handles_two_element_coordinates() -> None:
    payload = {
        "features": [
            {
                "id": "x1",
                "properties": {"mag": 1.0, "place": "p", "time": 0},
                "geometry": {"coordinates": [1.0, 2.0]},
            }
        ]
    }
    (event,) = UsgsSource().parse(payload)
    assert event.depth_km is None


@pytest.mark.parametrize(
    "feature",
    [
        "not a dict",
        {"id": "x", "properties": {}, "geometry": {}},
        {"id": "x", "properties": "bad", "geometry": {"coordinates": [1, 2]}},
        {"id": "x", "properties": {"time": 0}, "geometry": "bad"},
        {"id": "x", "properties": {"time": 0}, "geometry": {"coordinates": [1]}},
        {"id": "x", "properties": {"time": 0}, "geometry": {"coordinates": "bad"}},
        {"id": 42, "properties": {"time": 0}, "geometry": {"coordinates": [1, 2]}},
        {"id": "x", "properties": {"time": "soon"}, "geometry": {"coordinates": [1, 2]}},
        {"id": "x", "properties": {"time": 0}, "geometry": {"coordinates": ["a", "b"]}},
    ],
)
def test_usgs_skips_unusable_features(feature: Any) -> None:
    assert UsgsSource().parse({"features": [feature]}) == []


def test_usgs_rejects_non_object_payload() -> None:
    with pytest.raises(FetchError, match="not a GeoJSON object"):
        UsgsSource().parse([1, 2, 3])


def test_usgs_rejects_payload_without_features() -> None:
    with pytest.raises(FetchError, match="no 'features' array"):
        UsgsSource().parse({"metadata": {}})


@respx.mock
def test_usgs_fetch_filters_and_sorts(
    fetcher: HttpFetcher, usgs_payload: Any, fixture_now: datetime
) -> None:
    respx.get(USGS_DAY_URL).mock(return_value=httpx.Response(200, json=usgs_payload))
    events = UsgsSource().fetch(
        fetcher, Query(window=Window.DAY, min_mag=4.5, now=fixture_now)
    )
    assert events
    assert all(e.magnitude is not None and e.magnitude >= 4.5 for e in events)
    assert events == sorted(events, reverse=True)


@respx.mock
def test_usgs_fetch_on_empty_response(fetcher: HttpFetcher) -> None:
    respx.get(USGS_DAY_URL).mock(return_value=httpx.Response(204))
    assert UsgsSource().fetch(fetcher, Query()) == []


# --- EMSC parsing ---------------------------------------------------------


def test_emsc_parses_recorded_fixture(emsc_payload: Any) -> None:
    events = EmscSource().parse(emsc_payload)
    assert len(events) == len(emsc_payload["features"])
    for event in events:
        assert event.source is Source.EMSC
        assert event.id.startswith("emsc:")
        assert event.time.tzinfo is timezone.utc
        assert event.depth_km is None or event.depth_km >= 0


def test_emsc_maps_fields_from_a_known_feature() -> None:
    payload = {
        "features": [
            {
                "id": "20260929_0000254",
                "geometry": {"coordinates": [-67.4021, -22.1531, -137.9]},
                "properties": {
                    "time": "2026-09-29T18:21:51.496552Z",
                    "lat": -22.1531,
                    "lon": -67.4021,
                    "depth": 137.9,
                    "mag": 4.5,
                    "flynn_region": "POTOSI, BOLIVIA",
                },
            }
        ]
    }
    (event,) = EmscSource().parse(payload)
    assert event.id == "emsc:20260929_0000254"
    assert event.magnitude == pytest.approx(4.5)
    assert event.depth_km == pytest.approx(137.9)
    assert event.lat == pytest.approx(-22.1531)
    assert event.place == "POTOSI, BOLIVIA"
    assert event.time == datetime(2026, 9, 29, 18, 21, 51, 496552, tzinfo=timezone.utc)


def test_emsc_negative_depth_is_normalized_positive_down() -> None:
    """EMSC's geometry z is sign-flipped; properties.depth is authoritative."""
    payload = {
        "features": [
            {
                "id": "x",
                "properties": {
                    "time": "2026-09-29T00:00:00Z",
                    "lat": 1.0,
                    "lon": 2.0,
                    "depth": -25.0,
                    "mag": 3.0,
                },
            }
        ]
    }
    (event,) = EmscSource().parse(payload)
    assert event.depth_km == pytest.approx(25.0)


def test_emsc_falls_back_to_unid_and_geometry() -> None:
    payload = {
        "features": [
            {
                "geometry": {"coordinates": [10.0, 20.0, -5.0]},
                "properties": {
                    "unid": "20260929_0000001",
                    "time": "2026-09-29T00:00:00Z",
                    "mag": 3.0,
                },
            }
        ]
    }
    (event,) = EmscSource().parse(payload)
    assert event.id == "emsc:20260929_0000001"
    assert event.lat == pytest.approx(20.0)
    assert event.lon == pytest.approx(10.0)
    assert event.place == "unknown"


@pytest.mark.parametrize(
    "feature",
    [
        "not a dict",
        {"id": "x", "properties": "bad"},
        {"properties": {"time": "2026-09-29T00:00:00Z"}},
        {"id": "x", "properties": {"time": 12345}},
        {"id": "x", "properties": {"time": "not a time"}},
        {"id": "x", "properties": {"time": "2026-09-29T00:00:00Z"}},
        {
            "id": "x",
            "properties": {"time": "2026-09-29T00:00:00Z"},
            "geometry": {"coordinates": [1.0]},
        },
        {
            "id": "x",
            "properties": {"time": "2026-09-29T00:00:00Z"},
            "geometry": "bad",
        },
    ],
)
def test_emsc_skips_unusable_features(feature: Any) -> None:
    assert EmscSource().parse({"features": [feature]}) == []


def test_emsc_rejects_non_object_payload() -> None:
    with pytest.raises(FetchError, match="not a GeoJSON object"):
        EmscSource().parse("nope")


def test_emsc_rejects_payload_without_features() -> None:
    with pytest.raises(FetchError, match="no 'features' array"):
        EmscSource().parse({"metadata": {}})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "2026-09-29T19:59:40.0Z",
            datetime(2026, 9, 29, 19, 59, 40, tzinfo=timezone.utc),
        ),
        (
            "2026-09-29T18:21:51.496552Z",
            datetime(2026, 9, 29, 18, 21, 51, 496552, tzinfo=timezone.utc),
        ),
        ("2026-09-29T00:00:00Z", datetime(2026, 9, 29, tzinfo=timezone.utc)),
        ("2026-09-29T00:00:00", datetime(2026, 9, 29, tzinfo=timezone.utc)),
        ("  2026-09-29T00:00:00z  ", datetime(2026, 9, 29, tzinfo=timezone.utc)),
        (
            "2026-09-29T01:00:00+01:00",
            datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc),
        ),
        (
            "2026-09-29T19:59:40.1234567Z",
            datetime(2026, 9, 29, 19, 59, 40, 123456, tzinfo=timezone.utc),
        ),
        ("garbage", None),
    ],
)
def test_emsc_time_parsing(raw: str, expected: Any) -> None:
    """Covers the 1-digit fraction Python 3.10's fromisoformat would reject."""
    assert _parse_time(raw) == expected


def test_emsc_params_push_filters_upstream() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    params = EmscSource().params(
        Query(
            window=Window.DAY,
            min_mag=4.5,
            near=(35.0, 139.0),
            radius_km=222.39,
            now=now,
        )
    )
    assert params["format"] == "json"
    assert params["starttime"] == "2026-09-28T12:00:00"
    assert params["minmag"] == 4.5
    assert params["lat"] == 35.0
    assert params["lon"] == 139.0
    assert params["maxradius"] == pytest.approx(2.0, rel=0.01)


def test_emsc_params_omit_absent_filters() -> None:
    params = EmscSource().params(Query(window=Window.HOUR))
    assert "minmag" not in params
    assert "maxradius" not in params


def test_emsc_params_ignore_near_without_radius() -> None:
    params = EmscSource().params(Query(near=(1.0, 2.0)))
    assert "lat" not in params


@respx.mock
def test_emsc_fetch_filters_and_sorts(
    fetcher: HttpFetcher, emsc_payload: Any, fixture_now: datetime
) -> None:
    respx.get(EMSC_URL).mock(return_value=httpx.Response(200, json=emsc_payload))
    events = EmscSource().fetch(
        fetcher, Query(window=Window.DAY, min_mag=3.0, now=fixture_now)
    )
    assert events
    assert all(e.magnitude is not None and e.magnitude >= 3.0 for e in events)
    assert events == sorted(events, reverse=True)


@respx.mock
def test_emsc_fetch_on_204(fetcher: HttpFetcher) -> None:
    respx.get(EMSC_URL).mock(return_value=httpx.Response(204))
    assert EmscSource().fetch(fetcher, Query()) == []


# --- Query filtering -----------------------------------------------------


def test_query_rejects_events_outside_window() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    query = Query(window=Window.HOUR, now=now)
    assert query.matches(make_event(time=now - timedelta(minutes=30)))
    assert not query.matches(make_event(time=now - timedelta(hours=2)))


def test_query_min_mag_excludes_unknown_magnitudes() -> None:
    query = Query(min_mag=2.0)
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert not Query(min_mag=2.0, now=now).matches(make_event(magnitude=None, time=now))
    assert query.matches(make_event(magnitude=5.0, time=None))


def test_query_radius_filter() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    query = Query(near=(35.68, 139.69), radius_km=100.0, now=now)
    near = make_event(lat=35.7, lon=139.7, time=now)
    far = make_event(lat=34.69, lon=135.50, time=now)
    assert query.matches(near)
    assert not query.matches(far)


def test_query_radius_needs_both_parts() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    far = make_event(lat=-80.0, lon=170.0, time=now)
    assert Query(near=(35.0, 139.0), now=now).matches(far)
    assert Query(radius_km=1.0, now=now).matches(far)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1.0),
        (1.5, 1.5),
        ("2.5", 2.5),
        ("nope", None),
        (None, None),
        (True, None),
        ([], None),
        ({}, None),
    ],
)
def test_as_float(value: Any, expected: Any) -> None:
    assert _as_float(value) == expected

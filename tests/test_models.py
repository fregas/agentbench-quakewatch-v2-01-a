from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quakewatch.models import Event, Source, Window, haversine_km, utcnow
from tests.conftest import make_event


def test_window_deltas() -> None:
    assert Window.HOUR.delta == timedelta(hours=1)
    assert Window.DAY.delta == timedelta(days=1)
    assert Window.WEEK.delta == timedelta(days=7)


def test_window_start_is_relative_to_now() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert Window.DAY.start(now) == datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def test_window_start_defaults_to_current_time() -> None:
    before = utcnow()
    start = Window.HOUR.start()
    assert before - timedelta(hours=1, seconds=5) <= start <= utcnow()


def test_enum_values_are_strings() -> None:
    assert str(Source.USGS) == "usgs"
    assert str(Window.WEEK) == "week"
    assert Source("emsc") is Source.EMSC


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="naive timestamp"):
        Event(
            id="x",
            time=datetime(2026, 1, 1),
            magnitude=1.0,
            depth_km=1.0,
            lat=0.0,
            lon=0.0,
            place="p",
            source=Source.USGS,
        )


def test_display_helpers_handle_missing_values() -> None:
    known = make_event(magnitude=4.25, depth_km=12.34)
    assert known.mag_display == "4.2"
    assert known.depth_display == "12.3"
    unknown = make_event(magnitude=None, depth_km=None)
    assert unknown.mag_display == "-"
    assert unknown.depth_display == "-"


def test_events_sort_chronologically() -> None:
    old = make_event(id="old", time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = make_event(id="new", time=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert sorted([new, old]) == [old, new]
    assert sorted([old, new], reverse=True) == [new, old]


def test_events_are_frozen() -> None:
    with pytest.raises(AttributeError):
        make_event().magnitude = 9.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("a", "b", "expected_km"),
    [
        ((0.0, 0.0), (0.0, 0.0), 0.0),
        ((0.0, 0.0), (0.0, 1.0), 111.2),
        ((0.0, 0.0), (1.0, 0.0), 111.2),
        ((35.68, 139.69), (34.69, 135.50), 396.3),
        ((90.0, 0.0), (-90.0, 0.0), 20015.1),
    ],
)
def test_haversine_km(
    a: tuple[float, float], b: tuple[float, float], expected_km: float
) -> None:
    assert haversine_km(a[0], a[1], b[0], b[1]) == pytest.approx(expected_km, rel=0.01)


def test_haversine_is_symmetric() -> None:
    forward = haversine_km(10.0, 20.0, -30.0, 100.0)
    backward = haversine_km(-30.0, 100.0, 10.0, 20.0)
    assert forward == pytest.approx(backward)


def test_distance_km_from_event() -> None:
    event = make_event(lat=35.68, lon=139.69)
    assert event.distance_km(35.68, 139.69) == pytest.approx(0.0)
    assert event.distance_km(34.69, 135.50) == pytest.approx(396.3, rel=0.01)


def test_utcnow_is_aware() -> None:
    assert utcnow().tzinfo is timezone.utc

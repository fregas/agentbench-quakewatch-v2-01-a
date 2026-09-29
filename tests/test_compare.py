from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from quakewatch.compare import (
    DEFAULT_DISTANCE_TOLERANCE_KM,
    DEFAULT_TIME_TOLERANCE_S,
    ComparisonReport,
    Match,
    compare,
)
from quakewatch.models import Event, Source
from tests.conftest import make_event

T0 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def usgs(**kwargs: Any) -> Event:
    """A USGS-sourced event at T0 unless overridden."""
    kwargs.setdefault("source", Source.USGS)
    kwargs.setdefault("time", T0)
    return make_event(**kwargs)


def emsc(**kwargs: Any) -> Event:
    """An EMSC-sourced event at T0 unless overridden."""
    kwargs.setdefault("source", Source.EMSC)
    kwargs.setdefault("time", T0)
    return make_event(**kwargs)


def test_defaults_are_the_documented_tolerances() -> None:
    assert DEFAULT_TIME_TOLERANCE_S == 60.0
    assert DEFAULT_DISTANCE_TOLERANCE_KM == 50.0


def test_identical_events_match() -> None:
    report = compare([usgs(id="u1")], [emsc(id="e1")])
    assert report.matched_count == 1
    assert report.usgs_only == []
    assert report.emsc_only == []
    assert report.usgs_total == 1
    assert report.emsc_total == 1


def test_event_just_inside_time_tolerance_matches() -> None:
    report = compare([usgs()], [emsc(time=T0 + timedelta(seconds=59))])
    assert report.matched_count == 1


def test_event_just_outside_time_tolerance_does_not_match() -> None:
    report = compare([usgs()], [emsc(time=T0 + timedelta(seconds=61))])
    assert report.matched_count == 0
    assert len(report.usgs_only) == 1
    assert len(report.emsc_only) == 1


def test_time_tolerance_boundary_is_inclusive() -> None:
    assert compare([usgs()], [emsc(time=T0 + timedelta(seconds=60))]).matched_count == 1


def test_time_tolerance_is_symmetric() -> None:
    assert compare([usgs()], [emsc(time=T0 - timedelta(seconds=59))]).matched_count == 1


def test_event_just_inside_distance_tolerance_matches() -> None:
    # ~44.5 km apart at the equator.
    report = compare([usgs(lat=0.0, lon=0.0)], [emsc(lat=0.0, lon=0.4)])
    assert report.matched_count == 1


def test_event_outside_distance_tolerance_does_not_match() -> None:
    # ~111 km apart.
    report = compare([usgs(lat=0.0, lon=0.0)], [emsc(lat=0.0, lon=1.0)])
    assert report.matched_count == 0


def test_tolerances_are_configurable() -> None:
    far = [emsc(lat=0.0, lon=1.0, time=T0 + timedelta(seconds=120))]
    assert compare([usgs()], far).matched_count == 0
    assert (
        compare(
            [usgs()], far, time_tolerance_s=300.0, distance_tolerance_km=200.0
        ).matched_count
        == 1
    )


def test_each_event_is_matched_at_most_once() -> None:
    """Two USGS solutions near one EMSC event must not both claim it."""
    report = compare(
        [usgs(id="u1", lat=0.0), usgs(id="u2", lat=0.05)],
        [emsc(id="e1", lat=0.01)],
    )
    assert report.matched_count == 1
    # u1 sits 1.1 km from e1 and u2 sits 4.4 km away, so u1 takes the pairing.
    assert report.matches[0].usgs.id == "u1"
    assert [e.id for e in report.usgs_only] == ["u2"]


def test_nearest_candidate_wins() -> None:
    close = emsc(id="close", time=T0 + timedelta(seconds=1))
    report = compare(
        [usgs(id="u1")],
        [emsc(id="far", time=T0 + timedelta(seconds=50)), close],
    )
    assert report.matches[0].emsc.id == "close"


def test_greedy_matching_pairs_an_aftershock_sequence_one_to_one() -> None:
    usgs_events = [
        usgs(id=f"u{i}", time=T0 + timedelta(seconds=i * 30)) for i in range(3)
    ]
    emsc_events = [
        emsc(id=f"e{i}", time=T0 + timedelta(seconds=i * 30 + 2)) for i in range(3)
    ]
    report = compare(usgs_events, emsc_events)
    assert report.matched_count == 3
    assert {(m.usgs.id, m.emsc.id) for m in report.matches} == {
        ("u0", "e0"),
        ("u1", "e1"),
        ("u2", "e2"),
    }


def test_matches_are_newest_first() -> None:
    usgs_events = [usgs(id="old", time=T0), usgs(id="new", time=T0 + timedelta(hours=1))]
    emsc_events = [emsc(id="eo", time=T0), emsc(id="en", time=T0 + timedelta(hours=1))]
    report = compare(usgs_events, emsc_events)
    assert [m.usgs.id for m in report.matches] == ["new", "old"]


def test_unmatched_events_are_reported_per_catalog() -> None:
    report = compare(
        [usgs(id="u1"), usgs(id="u2", lat=40.0, lon=40.0)],
        [emsc(id="e1"), emsc(id="e2", lat=-40.0, lon=-40.0)],
    )
    assert report.matched_count == 1
    assert [e.id for e in report.usgs_only] == ["u2"]
    assert [e.id for e in report.emsc_only] == ["e2"]
    assert report.usgs_total == 2
    assert report.emsc_total == 2


def test_empty_inputs() -> None:
    report = compare([], [])
    assert report.matched_count == 0
    assert report.mean_mag_diff is None
    assert report.mean_abs_mag_diff is None
    assert report.max_abs_mag_diff is None
    assert report.mag_diffs == []


def test_one_empty_catalog() -> None:
    report = compare([usgs(id="u1")], [])
    assert report.matched_count == 0
    assert len(report.usgs_only) == 1
    assert report.emsc_total == 0


# --- Match arithmetic -----------------------------------------------------


def test_match_dt_is_signed_emsc_minus_usgs() -> None:
    match = Match(usgs=usgs(), emsc=emsc(time=T0 + timedelta(seconds=12)))
    assert match.dt_seconds == pytest.approx(12.0)
    assert Match(usgs=usgs(), emsc=emsc(time=T0 - timedelta(seconds=12))).dt_seconds == (
        pytest.approx(-12.0)
    )


def test_match_distance() -> None:
    match = Match(usgs=usgs(lat=0.0, lon=0.0), emsc=emsc(lat=0.0, lon=0.1))
    assert match.distance_km == pytest.approx(11.1, rel=0.01)


def test_match_mag_diff_is_signed_emsc_minus_usgs() -> None:
    match = Match(usgs=usgs(magnitude=4.5), emsc=emsc(magnitude=4.8))
    assert match.mag_diff == pytest.approx(0.3)


def test_match_mag_diff_is_none_when_either_is_unknown() -> None:
    assert Match(usgs=usgs(magnitude=None), emsc=emsc(magnitude=4.0)).mag_diff is None
    assert Match(usgs=usgs(magnitude=4.0), emsc=emsc(magnitude=None)).mag_diff is None


def test_magnitude_statistics() -> None:
    report = compare(
        [
            usgs(id="u1", magnitude=4.0),
            usgs(id="u2", magnitude=5.0, lat=20.0, lon=20.0),
            usgs(id="u3", magnitude=None, lat=-20.0, lon=-20.0),
        ],
        [
            emsc(id="e1", magnitude=4.2),
            emsc(id="e2", magnitude=4.4, lat=20.0, lon=20.0),
            emsc(id="e3", magnitude=6.0, lat=-20.0, lon=-20.0),
        ],
    )
    assert report.matched_count == 3
    # The pair with an unknown USGS magnitude contributes no difference.
    assert sorted(report.mag_diffs) == pytest.approx([-0.6, 0.2])
    assert report.mean_mag_diff == pytest.approx(-0.2)
    assert report.mean_abs_mag_diff == pytest.approx(0.4)
    assert report.max_abs_mag_diff == pytest.approx(0.6)


def test_statistics_when_no_match_has_both_magnitudes() -> None:
    report = compare([usgs(magnitude=None)], [emsc(magnitude=None)])
    assert report.matched_count == 1
    assert report.mean_mag_diff is None
    assert report.max_abs_mag_diff is None


def test_report_records_the_tolerances_used() -> None:
    report = compare([], [], time_tolerance_s=30.0, distance_tolerance_km=25.0)
    assert report.time_tolerance_s == 30.0
    assert report.distance_tolerance_km == 25.0


def test_empty_report_defaults() -> None:
    report = ComparisonReport()
    assert report.matched_count == 0
    assert report.usgs_total == 0
    assert report.emsc_total == 0

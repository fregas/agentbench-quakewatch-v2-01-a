from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from quakewatch.compare import ComparisonReport, Match, compare
from quakewatch.models import Source
from quakewatch.render import (
    EVENT_HEADERS,
    MATCH_HEADERS,
    Output,
    is_tty,
    render_comparison,
    render_events,
)
from tests.conftest import make_event

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

EVENTS = [
    make_event(
        id="usgs:a",
        time=T0,
        magnitude=5.42,
        depth_km=12.55,
        lat=35.681,
        lon=139.692,
        place="Tokyo, Japan",
    ),
    make_event(
        id="emsc:b",
        time=T0 - timedelta(hours=1),
        magnitude=None,
        depth_km=None,
        place="somewhere else",
        source=Source.EMSC,
    ),
]


class FakeStream(io.StringIO):
    """A StringIO that can claim to be a TTY."""

    def __init__(self, tty: bool = False) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def out_for(plain: bool) -> Output:
    """An Output writing to an in-memory stream that fakes TTY-ness."""
    return Output(stream=FakeStream(tty=not plain))


def text(out: Output) -> str:
    """Everything written to a FakeStream-backed Output."""
    stream = out.stream
    assert isinstance(stream, FakeStream)
    return stream.getvalue()


def rows_of(body: str) -> list[list[str]]:
    return [line.split("\t") for line in body.splitlines() if line.strip()]


def test_is_tty_detection() -> None:
    assert is_tty(FakeStream(tty=True)) is True
    assert is_tty(FakeStream(tty=False)) is False


def test_is_tty_on_a_stream_without_isatty() -> None:
    class Bare:
        pass

    assert is_tty(Bare()) is False  # type: ignore[arg-type]


def test_is_tty_defaults_to_stdout() -> None:
    assert isinstance(is_tty(), bool)


def test_output_is_plain_off_a_tty() -> None:
    assert Output(stream=FakeStream(tty=False)).plain is True
    assert Output(stream=FakeStream(tty=False)).console is None


def test_output_is_rich_on_a_tty() -> None:
    out = Output(stream=FakeStream(tty=True))
    assert out.plain is False
    assert out.console is not None


def test_plain_can_be_forced_on_a_tty() -> None:
    assert Output(stream=FakeStream(tty=True), force_plain=True).plain is True


def test_output_defaults_to_stdout() -> None:
    assert Output().stream is not None


# --- event listings -------------------------------------------------------


def test_plain_listing_is_really_tab_separated() -> None:
    """Plain output must survive `cut -f`, so tabs may not become spaces."""
    out = out_for(plain=True)
    render_events(EVENTS, out)
    rows = rows_of(text(out))
    assert rows[0] == list(EVENT_HEADERS)
    assert rows[1] == [
        "2026-09-29 12:00:00",
        "5.4",
        "12.6",
        "35.681",
        "139.692",
        "Tokyo, Japan",
        "usgs",
    ]
    assert len(rows) == 1 + len(EVENTS)


def test_plain_listing_renders_unknown_values_as_dashes() -> None:
    out = out_for(plain=True)
    render_events(EVENTS, out)
    assert rows_of(text(out))[2][1:3] == ["-", "-"]


def test_plain_listing_prints_the_title_on_its_own_line() -> None:
    out = out_for(plain=True)
    render_events(EVENTS, out, title="my title")
    assert text(out).splitlines()[0] == "my title"


def test_rich_listing_draws_a_table() -> None:
    out = out_for(plain=False)
    render_events(EVENTS, out, title="my title")
    body = text(out)
    assert "my title" in body
    assert "Tokyo, Japan" in body
    # Box-drawing characters mean the rich renderer ran.
    assert any(ch in body for ch in "─━┃│")
    assert "\t" not in body


@pytest.mark.parametrize("plain", [True, False])
def test_empty_listing_says_so(plain: bool) -> None:
    out = out_for(plain=plain)
    render_events([], out)
    assert "no events matched" in text(out)


# --- comparison reports ---------------------------------------------------


def build_report() -> ComparisonReport:
    return compare(
        [make_event(id="u1", time=T0, magnitude=4.5, place="Tokyo, Japan")],
        [
            make_event(
                id="e1",
                time=T0 + timedelta(seconds=8),
                magnitude=4.8,
                lat=0.05,
                source=Source.EMSC,
            ),
            make_event(
                id="e2", time=T0, magnitude=3.0, lat=40.0, lon=40.0, source=Source.EMSC
            ),
        ],
    )


def test_plain_comparison_reports_counts_and_stats() -> None:
    out = out_for(plain=True)
    render_comparison(build_report(), out)
    body = text(out)
    assert "matching within +/-60s and 50 km" in body
    for expected in (
        "usgs events\t1",
        "emsc events\t2",
        "matched\t1",
        "usgs only\t0",
        "emsc only\t1",
        "mean mag diff (emsc-usgs)\t+0.30",
        "mean abs mag diff\t0.30",
        "max abs mag diff\t0.30",
    ):
        assert expected in body


def test_plain_comparison_lists_matched_pairs() -> None:
    out = out_for(plain=True)
    render_comparison(build_report(), out)
    rows = rows_of(text(out))
    header_idx = next(i for i, r in enumerate(rows) if r[0] == "time (UTC)")
    assert rows[header_idx] == list(MATCH_HEADERS)
    assert rows[header_idx + 1] == [
        "2026-09-29 12:00:00",
        "4.5",
        "4.8",
        "+0.30",
        "+8.0",
        "5.6",
        "Tokyo, Japan",
    ]


def test_rich_comparison_draws_tables() -> None:
    out = out_for(plain=False)
    render_comparison(build_report(), out)
    body = text(out)
    assert "matched events (showing 1 of 1)" in body
    assert any(ch in body for ch in "─━┃│")


@pytest.mark.parametrize("plain", [True, False])
def test_comparison_with_no_matches_prints_only_the_summary(plain: bool) -> None:
    out = out_for(plain=plain)
    render_comparison(compare([make_event(id="u1")], []), out)
    body = text(out)
    assert "matched" in body
    assert "usgs mag" not in body


def test_unknown_statistics_render_as_dashes() -> None:
    out = out_for(plain=True)
    render_comparison(ComparisonReport(), out)
    assert "mean mag diff (emsc-usgs)\t-" in text(out)


def test_match_list_is_limited_and_says_how_many_were_hidden() -> None:
    matches = [
        Match(
            usgs=make_event(id=f"u{i}", time=T0 + timedelta(hours=i), magnitude=4.0),
            emsc=make_event(
                id=f"e{i}",
                time=T0 + timedelta(hours=i),
                magnitude=4.1,
                source=Source.EMSC,
            ),
        )
        for i in range(5)
    ]
    out = out_for(plain=True)
    render_comparison(ComparisonReport(matches=matches), out, limit=2)
    body = text(out)
    assert "showing 2 of 5" in body
    assert "... 3 more matches not shown" in body


@pytest.mark.parametrize("plain", [True, False])
def test_comparison_tolerances_are_echoed(plain: bool) -> None:
    out = out_for(plain=plain)
    render_comparison(
        compare([], [], time_tolerance_s=30.0, distance_tolerance_km=25.0), out
    )
    assert "+/-30s and 25 km" in text(out)

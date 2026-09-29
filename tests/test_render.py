from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from quakewatch.models import Source
from quakewatch.render import (
    EVENT_HEADERS,
    Output,
    is_tty,
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

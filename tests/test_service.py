from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
import respx

from quakewatch.http import HttpFetcher
from quakewatch.models import Source, Window
from quakewatch.service import (
    build_source,
    fetch_events,
    merge,
    resolve_sources,
)
from quakewatch.sources import EmscSource, Query, UsgsSource
from tests.conftest import EMSC_URL, USGS_DAY_URL, make_event


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("usgs", (Source.USGS,)),
        ("emsc", (Source.EMSC,)),
        ("both", (Source.USGS, Source.EMSC)),
        ("BOTH", (Source.USGS, Source.EMSC)),
    ],
)
def test_resolve_sources(selector: str, expected: Any) -> None:
    assert resolve_sources(selector) == expected


def test_resolve_sources_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown source selector"):
        resolve_sources("iris")


def test_build_source() -> None:
    assert isinstance(build_source(Source.USGS), UsgsSource)
    assert isinstance(build_source(Source.EMSC), EmscSource)


@respx.mock
def test_fetch_events_from_both(
    fetcher: HttpFetcher, usgs_payload: Any, emsc_payload: Any, fixture_now: datetime
) -> None:
    respx.get(USGS_DAY_URL).mock(return_value=httpx.Response(200, json=usgs_payload))
    respx.get(EMSC_URL).mock(return_value=httpx.Response(200, json=emsc_payload))
    results = fetch_events(
        fetcher, Query(window=Window.DAY, now=fixture_now), resolve_sources("both")
    )
    assert set(results) == {Source.USGS, Source.EMSC}
    assert results[Source.USGS] and results[Source.EMSC]


@respx.mock
def test_fetch_events_single_source_hits_only_that_api(
    fetcher: HttpFetcher, usgs_payload: Any
) -> None:
    usgs = respx.get(USGS_DAY_URL).mock(
        return_value=httpx.Response(200, json=usgs_payload)
    )
    emsc = respx.get(EMSC_URL).mock(return_value=httpx.Response(200, json={}))
    fetch_events(fetcher, Query(), resolve_sources("usgs"))
    assert usgs.call_count == 1
    assert emsc.call_count == 0


def test_merge_sorts_newest_first() -> None:
    a = make_event(id="a", time=datetime.fromisoformat("2026-09-29T10:00:00+00:00"))
    b = make_event(id="b", time=datetime.fromisoformat("2026-09-29T12:00:00+00:00"))
    c = make_event(id="c", time=datetime.fromisoformat("2026-09-29T11:00:00+00:00"))
    merged = merge({Source.USGS: [a, b], Source.EMSC: [c]})
    assert [e.id for e in merged] == ["b", "c", "a"]


def test_merge_of_nothing() -> None:
    assert merge({}) == []
    assert merge({Source.USGS: []}) == []

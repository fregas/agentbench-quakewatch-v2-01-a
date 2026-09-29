from __future__ import annotations

import httpx
import pytest
import respx

from quakewatch.cache import ResponseCache
from quakewatch.http import FetchError, HttpFetcher

URL = "https://example.test/feed.json"


@respx.mock
def test_get_json_returns_decoded_body(fetcher: HttpFetcher) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"a": 1}))
    assert fetcher.get_json(URL) == {"a": 1}
    assert route.call_count == 1


@respx.mock
def test_second_call_is_served_from_cache(fetcher: HttpFetcher) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"a": 1}))
    assert fetcher.get_json(URL) == {"a": 1}
    assert fetcher.get_json(URL) == {"a": 1}
    assert route.call_count == 1


@respx.mock
def test_disabled_cache_refetches(cache: ResponseCache) -> None:
    cache.enabled = False
    fetcher = HttpFetcher(cache=cache)
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"a": 1}))
    fetcher.get_json(URL)
    fetcher.get_json(URL)
    assert route.call_count == 2


@respx.mock
def test_differing_params_are_cached_separately(fetcher: HttpFetcher) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"a": 1}))
    fetcher.get_json(URL, {"x": 1})
    fetcher.get_json(URL, {"x": 2})
    fetcher.get_json(URL, {"x": 1})
    assert route.call_count == 2


@respx.mock
def test_params_are_sent_upstream(fetcher: HttpFetcher) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    fetcher.get_json(URL, {"format": "json", "minmag": 4.5})
    request = route.calls[0].request
    assert request.url.params["format"] == "json"
    assert request.url.params["minmag"] == "4.5"


@respx.mock
def test_user_agent_is_sent(fetcher: HttpFetcher) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    fetcher.get_json(URL)
    assert route.calls[0].request.headers["user-agent"].startswith("quakewatch/")


@respx.mock
def test_204_is_reported_as_empty(fetcher: HttpFetcher) -> None:
    """EMSC uses 204 No Content to mean 'no matching events'."""
    respx.get(URL).mock(return_value=httpx.Response(204))
    assert fetcher.get_json(URL) is None


@respx.mock
def test_empty_body_is_reported_as_empty(fetcher: HttpFetcher) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"   "))
    assert fetcher.get_json(URL) is None


@respx.mock
def test_empty_result_is_cached(fetcher: HttpFetcher) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(204))
    assert fetcher.get_json(URL) is None
    assert fetcher.get_json(URL) is None
    assert route.call_count == 1


@respx.mock
def test_http_error_status_raises(fetcher: HttpFetcher) -> None:
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(FetchError, match="HTTP 503"):
        fetcher.get_json(URL)


@respx.mock
def test_transport_error_raises(fetcher: HttpFetcher) -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(FetchError, match="could not be reached"):
        fetcher.get_json(URL)


@respx.mock
def test_non_json_body_raises(fetcher: HttpFetcher) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"<html>nope</html>"))
    with pytest.raises(FetchError, match="non-JSON"):
        fetcher.get_json(URL)


@respx.mock
def test_failures_are_not_cached(fetcher: HttpFetcher) -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(FetchError):
        fetcher.get_json(URL)
    assert fetcher.cache.get(fetcher.cache.key(URL)) is None


def test_default_cache_is_created_when_omitted() -> None:
    assert HttpFetcher().cache.enabled is True


@respx.mock
def test_context_manager_closes_client(cache: ResponseCache) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    with HttpFetcher(cache=cache) as fetcher:
        fetcher.get_json(URL)
        assert fetcher._client is not None
    assert fetcher._client is None


def test_close_is_idempotent(fetcher: HttpFetcher) -> None:
    fetcher.close()
    fetcher.close()


@respx.mock
def test_injected_client_is_reused(cache: ResponseCache) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"a": 1}))
    client = httpx.Client()
    fetcher = HttpFetcher(cache=cache, client=client)
    assert fetcher.get_json(URL) == {"a": 1}
    assert fetcher._client is client
    client.close()

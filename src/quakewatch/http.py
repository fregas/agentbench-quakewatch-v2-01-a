"""The HTTP layer: one thin client that all sources share."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from quakewatch import __version__
from quakewatch.cache import JsonValue, ResponseCache

USER_AGENT = (
    f"quakewatch/{__version__} (+https://github.com/fregas/agentbench-quakewatch-v2-01-a)"
)
DEFAULT_TIMEOUT = 30.0


class FetchError(RuntimeError):
    """An upstream feed could not be fetched or returned unusable content."""


class HttpFetcher:
    """Fetches JSON over HTTPS, consulting a :class:`ResponseCache` first."""

    def __init__(
        self,
        cache: ResponseCache | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache = cache if cache is not None else ResponseCache()
        self.timeout = timeout
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
        return self._client

    def get_json(
        self, url: str, params: Mapping[str, Any] | None = None
    ) -> JsonValue | None:
        """Return the decoded body of ``url``, or ``None`` for an empty response.

        A ``204 No Content`` -- which EMSC uses to mean "no matching events" --
        is reported as ``None`` rather than an error, and is cached like any
        other answer so that an empty window does not re-hit the API.
        """
        key = self.cache.key(url, params)
        cached = self.cache.get(key)
        if cached is not None:
            return None if cached == {"__empty__": True} else cached

        try:
            response = self._get_client().get(url, params=dict(params or {}))
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"{url} returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"{url} could not be reached: {exc}") from exc

        if response.status_code == 204 or not response.content.strip():
            self.cache.set(key, {"__empty__": True})
            return None

        try:
            payload: JsonValue = response.json()
        except ValueError as exc:
            raise FetchError(f"{url} returned a non-JSON body") from exc

        self.cache.set(key, payload)
        return payload

    def close(self) -> None:
        """Release the underlying connection pool."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> HttpFetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

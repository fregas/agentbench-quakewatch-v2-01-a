"""A small on-disk response cache with a per-entry TTL."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = Path(".cache/quakewatch")
DEFAULT_TTL_SECONDS = 300.0

JsonValue = Any


@dataclass
class ResponseCache:
    """Caches decoded JSON payloads as files under ``directory``.

    A cache entry is a JSON document holding the payload plus the epoch second
    it was stored at, so the TTL is evaluated on read and can be changed
    between runs without invalidating anything.
    """

    directory: Path = DEFAULT_CACHE_DIR
    ttl: float = DEFAULT_TTL_SECONDS
    enabled: bool = True

    @staticmethod
    def key(url: str, params: Mapping[str, Any] | None = None) -> str:
        """A stable filename-safe digest for a request."""
        canonical = json.dumps(
            {"url": url, "params": dict(sorted((params or {}).items()))},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def path_for(self, key: str) -> Path:
        """The file an entry with ``key`` is stored at."""
        return self.directory / f"{key}.json"

    def get(self, key: str) -> JsonValue | None:
        """The cached payload for ``key``, or ``None`` if absent or stale."""
        if not self.enabled or self.ttl <= 0:
            return None
        path = self.path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            # A truncated or hand-edited entry is treated as a miss, not an error.
            return None
        if not isinstance(entry, dict) or "stored_at" not in entry:
            return None
        stored_at = entry["stored_at"]
        if not isinstance(stored_at, (int, float)):
            return None
        if time.time() - float(stored_at) > self.ttl:
            return None
        return entry.get("payload")

    def set(self, key: str, payload: JsonValue) -> None:
        """Store ``payload`` under ``key``, ignoring an unwritable cache dir."""
        if not self.enabled:
            return
        path = self.path_for(key)
        entry = {"stored_at": time.time(), "payload": payload}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entry), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            # A read-only filesystem must not break an otherwise fine request.
            return

    def clear(self) -> int:
        """Delete every entry, returning how many files were removed."""
        removed = 0
        if not self.directory.is_dir():
            return removed
        for path in self.directory.glob("*.json"):
            try:
                path.unlink()
            except OSError:  # pragma: no cover - racing another process
                continue
            removed += 1
        return removed

from __future__ import annotations

import json
import time
from pathlib import Path

from quakewatch.cache import ResponseCache


def test_key_is_stable_and_order_independent() -> None:
    a = ResponseCache.key("https://x/y", {"b": 2, "a": 1})
    b = ResponseCache.key("https://x/y", {"a": 1, "b": 2})
    assert a == b
    assert len(a) == 32


def test_key_varies_with_url_and_params() -> None:
    base = ResponseCache.key("https://x/y")
    assert base != ResponseCache.key("https://x/z")
    assert base != ResponseCache.key("https://x/y", {"a": 1})
    assert ResponseCache.key("https://x/y", {}) == base


def test_roundtrip(cache: ResponseCache) -> None:
    cache.set("k", {"hello": "world"})
    assert cache.get("k") == {"hello": "world"}
    assert cache.path_for("k").is_file()


def test_miss_on_absent_key(cache: ResponseCache) -> None:
    assert cache.get("nope") is None


def test_entry_expires_after_ttl(cache: ResponseCache) -> None:
    cache.ttl = 0.05
    cache.set("k", [1, 2, 3])
    assert cache.get("k") == [1, 2, 3]
    time.sleep(0.08)
    assert cache.get("k") is None


def test_ttl_is_evaluated_on_read(cache: ResponseCache) -> None:
    cache.set("k", "v")
    cache.ttl = -1.0
    assert cache.get("k") is None
    cache.ttl = 300.0
    assert cache.get("k") == "v"


def test_disabled_cache_neither_reads_nor_writes(cache: ResponseCache) -> None:
    cache.set("k", "v")
    cache.enabled = False
    assert cache.get("k") is None
    cache.set("k2", "v2")
    assert not cache.path_for("k2").exists()


def test_corrupt_entry_is_a_miss(cache: ResponseCache) -> None:
    cache.set("k", "v")
    cache.path_for("k").write_text("{not json", encoding="utf-8")
    assert cache.get("k") is None


def test_entry_without_timestamp_is_a_miss(cache: ResponseCache) -> None:
    cache.directory.mkdir(parents=True, exist_ok=True)
    cache.path_for("k").write_text(json.dumps({"payload": 1}), encoding="utf-8")
    assert cache.get("k") is None


def test_entry_with_non_numeric_timestamp_is_a_miss(cache: ResponseCache) -> None:
    cache.directory.mkdir(parents=True, exist_ok=True)
    cache.path_for("k").write_text(
        json.dumps({"stored_at": "yesterday", "payload": 1}), encoding="utf-8"
    )
    assert cache.get("k") is None


def test_non_object_entry_is_a_miss(cache: ResponseCache) -> None:
    cache.directory.mkdir(parents=True, exist_ok=True)
    cache.path_for("k").write_text(json.dumps([1, 2]), encoding="utf-8")
    assert cache.get("k") is None


def test_falsey_payloads_roundtrip(cache: ResponseCache) -> None:
    cache.set("empty-list", [])
    cache.set("empty-dict", {})
    assert cache.get("empty-list") == []
    assert cache.get("empty-dict") == {}


def test_set_tolerates_unwritable_directory(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    cache = ResponseCache(directory=blocker / "cache")
    cache.set("k", "v")  # must not raise
    assert cache.get("k") is None


def test_clear_removes_entries(cache: ResponseCache) -> None:
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.clear() == 2
    assert cache.get("a") is None


def test_clear_on_missing_directory(cache: ResponseCache) -> None:
    assert cache.clear() == 0


def test_no_temp_files_left_behind(cache: ResponseCache) -> None:
    cache.set("k", "v")
    assert [p.name for p in cache.directory.iterdir()] == ["k.json"]

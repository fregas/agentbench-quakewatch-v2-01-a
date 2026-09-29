from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from quakewatch.export import (
    CSV_COLUMNS,
    FORMATS,
    format_for_path,
    render,
    to_csv,
    to_geojson,
    to_json,
    to_row,
    write,
)
from quakewatch.models import Source
from tests.conftest import make_event

EVENTS = [
    make_event(
        id="usgs:a",
        time=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
        magnitude=5.4,
        depth_km=12.5,
        lat=35.68,
        lon=139.69,
        place="Tokyo, Japan",
        source=Source.USGS,
    ),
    make_event(
        id="emsc:b",
        time=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
        magnitude=None,
        depth_km=None,
        lat=-22.15,
        lon=-67.40,
        place='Potosi, "Bolivia"',
        source=Source.EMSC,
    ),
]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("out.csv", "csv"),
        ("out.json", "json"),
        ("out.geojson", "geojson"),
        ("OUT.CSV", "csv"),
        ("out.txt", None),
        ("out", None),
    ],
)
def test_format_for_path(name: str, expected: Any) -> None:
    assert format_for_path(Path(name)) == expected


def test_to_row_uses_a_z_suffixed_timestamp() -> None:
    row = to_row(EVENTS[0])
    assert row["time"] == "2026-09-29T12:00:00Z"
    assert row["source"] == "usgs"
    assert set(row) == set(CSV_COLUMNS)


def test_csv_has_a_header_and_one_row_per_event() -> None:
    rows = list(csv.DictReader(io.StringIO(to_csv(EVENTS))))
    assert len(rows) == 2
    assert list(rows[0]) == list(CSV_COLUMNS)
    assert rows[0]["magnitude"] == "5.4"
    assert rows[0]["place"] == "Tokyo, Japan"


def test_csv_renders_missing_values_as_empty_and_quotes_correctly() -> None:
    rows = list(csv.DictReader(io.StringIO(to_csv(EVENTS))))
    assert rows[1]["magnitude"] == ""
    assert rows[1]["depth_km"] == ""
    assert rows[1]["place"] == 'Potosi, "Bolivia"'


def test_csv_of_nothing_is_just_a_header() -> None:
    assert to_csv([]).strip() == ",".join(CSV_COLUMNS)


def test_json_is_an_array_of_flat_objects() -> None:
    parsed = json.loads(to_json(EVENTS))
    assert [e["id"] for e in parsed] == ["usgs:a", "emsc:b"]
    assert parsed[1]["magnitude"] is None


def test_json_of_nothing() -> None:
    assert json.loads(to_json([])) == []


def test_geojson_is_a_feature_collection() -> None:
    parsed = json.loads(to_geojson(EVENTS))
    assert parsed["type"] == "FeatureCollection"
    assert len(parsed["features"]) == 2
    feature = parsed["features"][0]
    assert feature["type"] == "Feature"
    assert feature["id"] == "usgs:a"
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["place"] == "Tokyo, Japan"


def test_geojson_coordinates_are_lon_lat_and_depth_is_negated() -> None:
    feature = json.loads(to_geojson(EVENTS))["features"][0]
    assert feature["geometry"]["coordinates"] == [139.69, 35.68, -12.5]


def test_geojson_omits_elevation_when_depth_is_unknown() -> None:
    feature = json.loads(to_geojson(EVENTS))["features"][1]
    assert feature["geometry"]["coordinates"] == [-67.40, -22.15]


def test_geojson_of_nothing() -> None:
    assert json.loads(to_geojson([]))["features"] == []


@pytest.mark.parametrize("fmt", FORMATS)
def test_render_dispatches_to_every_format(fmt: str) -> None:
    assert render(EVENTS, fmt)


def test_render_is_case_insensitive() -> None:
    assert render(EVENTS, "CSV") == to_csv(EVENTS)


def test_render_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="unknown export format"):
        render(EVENTS, "xml")


@pytest.mark.parametrize("fmt", FORMATS)
def test_write_roundtrips_to_disk(tmp_path: Path, fmt: str) -> None:
    path = tmp_path / f"out.{fmt}"
    written = write(EVENTS, path, fmt)
    assert written == len(path.read_bytes())
    assert path.read_text(encoding="utf-8") == render(EVENTS, fmt)


def test_write_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "out.json"
    write(EVENTS, path, "json")
    assert path.is_file()


def test_write_to_a_bare_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write(EVENTS, Path("out.csv"), "csv")
    assert (tmp_path / "out.csv").is_file()


def test_write_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    path.write_text("stale", encoding="utf-8")
    write(EVENTS, path, "json")
    assert "stale" not in path.read_text(encoding="utf-8")

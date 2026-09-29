"""Writing events out as CSV, JSON or GeoJSON."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from quakewatch.models import Event

CSV_COLUMNS = (
    "id",
    "time",
    "magnitude",
    "depth_km",
    "lat",
    "lon",
    "place",
    "source",
)

FORMATS = ("csv", "json", "geojson")

EXTENSION_FORMATS = {
    ".csv": "csv",
    ".json": "json",
    ".geojson": "geojson",
}


def format_for_path(path: Path) -> str | None:
    """Guess the export format from ``path``'s extension."""
    return EXTENSION_FORMATS.get(path.suffix.lower())


def to_row(event: Event) -> dict[str, Any]:
    """A flat, JSON-safe mapping for one event."""
    return {
        "id": event.id,
        "time": event.time.isoformat().replace("+00:00", "Z"),
        "magnitude": event.magnitude,
        "depth_km": event.depth_km,
        "lat": event.lat,
        "lon": event.lon,
        "place": event.place,
        "source": event.source.value,
    }


def to_csv(events: Iterable[Event]) -> str:
    """Render events as CSV with a header row."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for event in events:
        row = to_row(event)
        writer.writerow({k: "" if row[k] is None else row[k] for k in CSV_COLUMNS})
    return buffer.getvalue()


def to_json(events: Iterable[Event]) -> str:
    """Render events as a JSON array of flat objects."""
    return json.dumps([to_row(e) for e in events], indent=2) + "\n"


def to_geojson(events: Iterable[Event]) -> str:
    """Render events as a GeoJSON FeatureCollection.

    Coordinates follow the GeoJSON convention of ``[lon, lat, elevation]``, so
    depth is emitted negated as an elevation below the datum.
    """
    features = []
    for event in events:
        row = to_row(event)
        coordinates: list[float] = [event.lon, event.lat]
        if event.depth_km is not None:
            coordinates.append(-event.depth_km)
        features.append(
            {
                "type": "Feature",
                "id": event.id,
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": row,
            }
        )
    return (
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2) + "\n"
    )


def render(events: Sequence[Event], fmt: str) -> str:
    """Render events in ``fmt``."""
    renderers = {"csv": to_csv, "json": to_json, "geojson": to_geojson}
    try:
        renderer = renderers[fmt.lower()]
    except KeyError:
        raise ValueError(
            f"unknown export format {fmt!r}; expected one of {', '.join(FORMATS)}"
        ) from None
    return renderer(events)


def write(events: Sequence[Event], path: Path, fmt: str) -> int:
    """Write events to ``path`` in ``fmt``, returning the byte count."""
    text = render(events, fmt)
    parent = path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))

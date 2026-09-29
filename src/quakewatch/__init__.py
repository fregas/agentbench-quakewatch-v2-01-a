"""quakewatch -- monitor recent earthquakes from the USGS and EMSC feeds."""

from __future__ import annotations

from quakewatch.models import Event, Source, Window

__all__ = ["Event", "Source", "Window", "__version__"]

__version__ = "0.1.0"

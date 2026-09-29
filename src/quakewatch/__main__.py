"""Support ``python -m quakewatch``."""

from __future__ import annotations

import sys

from quakewatch.cli import main

if __name__ == "__main__":
    sys.exit(main())

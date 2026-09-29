# quakewatch

A Python CLI and library for monitoring recent earthquakes, reading from two
independent catalogs and normalizing them into a single event model:

- **USGS** — the [GeoJSON summary feeds](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php)
- **EMSC** — the [FDSN `event` web service](https://www.seismicportal.eu/fdsn-wsevent.html) (`format=json`)

Responses are cached on disk with a configurable TTL, so repeated calls during a
session do not re-hit the upstream APIs.

## Install

From a checkout:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

With the development toolchain (pytest, mypy, ruff):

```bash
pip install -e ".[dev]"
```

Requires Python 3.10 or newer. `quakewatch --version` confirms the install.

### Docker

```bash
docker build -t agentbench-quakewatch-v2-01-a:local .
docker run --rm agentbench-quakewatch-v2-01-a:local list --window day --min-mag 5
```

The image runs as a non-root user and takes the same arguments as the CLI.

## Usage

Global options come before the subcommand:

| Option | Meaning |
| --- | --- |
| `--cache-dir PATH` | Where cached responses live (default `.cache/quakewatch`) |
| `--cache-ttl SECONDS` | How long a cached response stays fresh (default `300`) |
| `--no-cache` | Bypass the cache entirely and always fetch |
| `--plain` | Force plain output even on a terminal |

### `quakewatch list`

List recent events, with optional magnitude, source and radius filters.

```bash
# Everything USGS saw in the past hour
quakewatch list --window hour

# M4.5+ in the past day, from both catalogs
quakewatch list --window day --min-mag 4.5 --source both

# Within 300 km of Tokyo over the past week, EMSC only
quakewatch list --window week --source emsc --near 35.68,139.69 --radius-km 300

# Ten strongest-reported recent events, ignoring any cached response
quakewatch --no-cache list --window day --min-mag 5 --limit 10
```

```
                     14 events, past day, source=usgs
 time (UTC)             mag   depth km      lat       lon   place
 2026-09-29 18:21:51    4.5      137.9  -22.153   -67.402   Potosi, Bolivia
 2026-09-29 15:02:04    5.1       35.0   -6.221   130.118   Banda Sea
```

`--near` and `--radius-km` must be given together. On a terminal the output is a
rich table; when stdout is redirected or piped it becomes tab-separated plain
text, so `quakewatch list ... | cut -f2` works as expected.

### `quakewatch compare`

Cross-match the two catalogs over the same window. Two events are considered the
same earthquake when their origin times are within **±60 s** and their epicenters
within **50 km**; both tolerances are adjustable. Candidate pairs are consumed
nearest-first and each event is matched at most once, so a dense aftershock
sequence does not produce duplicate pairings.

```bash
quakewatch compare --window day --min-mag 4.5
quakewatch compare --window hour --time-tolerance 30 --distance-tolerance 25
```

```
 matching within +/-60s and 50 km
 metric                       value
 usgs events                     38
 emsc events                     51
 matched                         31
 usgs only                        7
 emsc only                       20
 mean mag diff (emsc-usgs)    +0.06
 mean abs mag diff             0.16
 max abs mag diff              0.60
```

The report prints matched and unmatched counts per catalog, then the signed
magnitude differences (EMSC minus USGS) for each matched pair.

### `quakewatch export`

Write the same filtered event set to a file as CSV, JSON or GeoJSON. The format
is inferred from the extension, or set explicitly with `--format`.

```bash
quakewatch export --window day --min-mag 4 -o quakes.csv
quakewatch export --window week --source both -o quakes.geojson
quakewatch export --window hour -o /tmp/out.txt --format json
```

CSV columns are `id,time,magnitude,depth_km,lat,lon,place,source`. GeoJSON
follows the `[lon, lat, elevation]` convention, so depth is emitted negated as
an elevation below the datum.

## Library use

```python
from quakewatch.http import HttpFetcher
from quakewatch.models import Window
from quakewatch.sources import Query, UsgsSource

with HttpFetcher() as fetcher:
    events = UsgsSource().fetch(fetcher, Query(window=Window.DAY, min_mag=5.0))

for event in events:
    print(event.time, event.magnitude, event.place)
```

Every event is a frozen `quakewatch.models.Event` with `id`, timezone-aware UTC
`time`, `magnitude`, `depth_km`, `lat`, `lon`, `place` and `source`. The package
ships a `py.typed` marker.

## Known differences between USGS and EMSC

The two catalogs are independent, so `compare` will never report a perfect
overlap. The differences that matter in practice:

- **Regional completeness.** USGS's `all_*` feeds include very small local
  events from US regional networks (M0–M2 in California, Alaska, Hawaii,
  Oklahoma), which EMSC does not carry. EMSC is correspondingly denser for small
  Euro-Mediterranean events. Below roughly M4.5 the two catalogs are mostly
  *disjoint*, not disagreeing; a fair comparison uses `--min-mag 4.5` or higher.
- **Magnitude scale.** Neither feed is restricted to one magnitude type: USGS
  mixes `md`, `ml`, `mb` and `mww` depending on network and size, EMSC mixes
  `ml`, `mb` and `mw`. Differences of 0.1–0.3 between the two solutions for the
  same event are routine and reflect the scale used, not an error. The event
  model keeps only the preferred magnitude value, not its type.
- **Revision timing.** Both catalogs publish automatic solutions within minutes
  and revise them later after review. For the most recent hour the two can
  disagree on magnitude, depth and epicenter more than they will an hour later,
  and one may list an event the other has not yet published.
- **Depth.** USGS carries depth as the third GeoJSON coordinate, positive-down
  in km. EMSC reports positive-down km in `properties.depth`, but its geometry's
  third coordinate is sign-flipped; quakewatch reads `properties.depth` and
  normalizes to positive-down km. EMSC also pins poorly constrained depths to
  fixed values (often 10 km), so depth disagreements are common.
- **Place naming.** USGS uses a distance-and-bearing description relative to the
  nearest settlement ("10 km WNW of The Geysers, CA"); EMSC uses coarser
  Flynn–Engdahl region names ("Potosi, Bolivia"). The strings are not
  comparable, which is why `compare` matches on time and distance only.
- **Filtering fidelity.** The USGS summary feeds take no query parameters, so
  quakewatch filters them client-side. EMSC's FDSN service applies magnitude and
  radius filters upstream. Every result is re-checked locally against the same
  `Query`, so both sources answer the same question regardless.
- **Empty results.** EMSC signals "no matching events" with `HTTP 204 No
  Content` and an empty body rather than an empty feature collection; USGS
  always returns a `FeatureCollection`.
- **IDs.** Event IDs are namespaced (`usgs:nc75444517`, `emsc:20260929_0000254`)
  because the two catalogs' identifier schemes overlap in neither form nor
  meaning.

## Development

```bash
pip install -e ".[dev]"

ruff check . && ruff format --check .
mypy
pytest                              # unit tests only
pytest -m integration               # hits the real APIs
pytest --cov=quakewatch --cov-report=term-missing
```

The unit suite mocks all HTTP through `respx` against recorded fixtures in
`tests/fixtures/` and is held to a minimum of 85% coverage. The integration
tests are marked `integration`, deselected by default, and run against the live
USGS and EMSC services.

## License

MIT

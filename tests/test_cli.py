from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import click
import httpx
import pytest
import respx
from click.testing import CliRunner

from quakewatch import __version__
from quakewatch.cli import build_query, cli, main, parse_near
from quakewatch.models import Window
from tests.conftest import EMSC_URL, USGS_DAY_URL


@pytest.fixture
def runner(tmp_path: Path) -> CliRunner:
    return CliRunner()


@pytest.fixture
def base_args(tmp_path: Path) -> list[str]:
    """Global options that keep every test off the shared cache directory."""
    return ["--cache-dir", str(tmp_path / "cache")]


@pytest.fixture
def mocked_apis(usgs_payload: Any, emsc_payload: Any) -> Iterator[dict[str, respx.Route]]:
    with respx.mock(assert_all_called=False) as mock:
        usgs = mock.get(USGS_DAY_URL).mock(
            return_value=httpx.Response(200, json=usgs_payload)
        )
        emsc = mock.get(EMSC_URL).mock(
            return_value=httpx.Response(200, json=emsc_payload)
        )
        yield {"usgs": usgs, "emsc": emsc}


# --- option parsing -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("35.68,139.69", (35.68, 139.69)),
        (" 35.68 , 139.69 ", (35.68, 139.69)),
        ("-22,-67.4", (-22.0, -67.4)),
        ("0,0", (0.0, 0.0)),
        (None, None),
    ],
)
def test_parse_near(value: Any, expected: Any) -> None:
    assert parse_near(value) == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("35.68", "expected LAT,LON"),
        ("1,2,3", "expected LAT,LON"),
        ("a,b", "must be numbers"),
        ("91,0", "outside -90..90"),
        ("-91,0", "outside -90..90"),
        ("0,181", "outside -180..180"),
    ],
)
def test_parse_near_rejects_bad_input(value: Any, message: str) -> None:
    with pytest.raises(click.BadParameter, match=message):
        parse_near(value)


def test_build_query_maps_options() -> None:
    query = build_query("week", 4.5, "35.0,139.0", 100.0)
    assert query.window is Window.WEEK
    assert query.min_mag == 4.5
    assert query.near == (35.0, 139.0)
    assert query.radius_km == 100.0


def test_build_query_defaults() -> None:
    query = build_query("day", None, None, None)
    assert query.min_mag is None
    assert query.near is None


@pytest.mark.parametrize(
    ("near", "radius", "message"),
    [
        ("35,139", None, "--near also requires --radius-km"),
        (None, 100.0, "--radius-km also requires --near"),
    ],
)
def test_build_query_requires_near_and_radius_together(
    near: str | None, radius: float | None, message: str
) -> None:
    with pytest.raises(click.UsageError, match=message):
        build_query("day", None, near, radius)


def test_build_query_rejects_non_positive_radius() -> None:
    with pytest.raises(click.BadParameter, match="greater than 0"):
        build_query("day", None, "35,139", 0.0)


# --- top-level CLI --------------------------------------------------------


def test_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_lists_every_command(runner: CliRunner, flag: str) -> None:
    result = runner.invoke(cli, [flag])
    assert result.exit_code == 0
    for command in ("list", "compare", "export"):
        assert command in result.output


def test_no_arguments_shows_usage(runner: CliRunner) -> None:
    """A bare invocation prints help and exits 2, as click groups do."""
    result = runner.invoke(cli, [])
    assert result.exit_code == 2
    assert "Usage:" in result.output


# --- list -----------------------------------------------------------------


def test_list_prints_events(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--window", "day"])
    assert result.exit_code == 0, result.output
    assert "time (UTC)" in result.output
    assert mocked_apis["usgs"].call_count == 1


def test_list_output_is_plain_when_not_a_tty(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--limit", "1"])
    assert "\t" in result.output


def test_list_min_mag_filters(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--min-mag", "9.5"])
    assert result.exit_code == 0
    assert "no events matched" in result.output


def test_list_limit_caps_the_output(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--limit", "3"])
    rows = [line for line in result.output.splitlines() if line.strip()]
    # title + header + 3 events
    assert len(rows) == 5


def test_list_rejects_a_non_positive_limit(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--limit", "0"])
    assert result.exit_code == 2
    assert "greater than 0" in result.output


def test_list_source_emsc_hits_only_emsc(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--source", "emsc"])
    assert result.exit_code == 0
    assert mocked_apis["emsc"].call_count == 1
    assert mocked_apis["usgs"].call_count == 0


def test_list_source_both_hits_both(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--source", "both"])
    assert result.exit_code == 0
    assert mocked_apis["usgs"].call_count == 1
    assert mocked_apis["emsc"].call_count == 1
    assert "usgs" in result.output
    assert "emsc" in result.output


def test_list_rejects_an_unknown_source(runner: CliRunner, base_args: list[str]) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--source", "iris"])
    assert result.exit_code == 2


def test_list_rejects_an_unknown_window(runner: CliRunner, base_args: list[str]) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--window", "year"])
    assert result.exit_code == 2


def test_list_near_filters_by_radius(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    wide = runner.invoke(
        cli, [*base_args, "list", "--near", "0,0", "--radius-km", "20000"]
    )
    narrow = runner.invoke(cli, [*base_args, "list", "--near", "0,0", "--radius-km", "1"])
    assert wide.exit_code == 0 and narrow.exit_code == 0
    assert len(narrow.output) < len(wide.output)


def test_list_near_without_radius_is_a_usage_error(
    runner: CliRunner, base_args: list[str]
) -> None:
    result = runner.invoke(cli, [*base_args, "list", "--near", "35,139"])
    assert result.exit_code == 2
    assert "requires --radius-km" in result.output


def test_list_rejects_a_malformed_near(runner: CliRunner, base_args: list[str]) -> None:
    result = runner.invoke(
        cli, [*base_args, "list", "--near", "nope", "--radius-km", "5"]
    )
    assert result.exit_code == 2


# --- caching --------------------------------------------------------------


def test_repeated_calls_reuse_the_cache(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    runner.invoke(cli, [*base_args, "list"])
    runner.invoke(cli, [*base_args, "list"])
    assert mocked_apis["usgs"].call_count == 1


def test_no_cache_always_refetches(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    runner.invoke(cli, [*base_args, "--no-cache", "list"])
    runner.invoke(cli, [*base_args, "--no-cache", "list"])
    assert mocked_apis["usgs"].call_count == 2


def test_zero_ttl_refetches(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    runner.invoke(cli, [*base_args, "--cache-ttl", "0", "list"])
    runner.invoke(cli, [*base_args, "--cache-ttl", "0", "list"])
    assert mocked_apis["usgs"].call_count == 2


def test_cache_files_land_in_the_requested_directory(
    runner: CliRunner, tmp_path: Path, mocked_apis: dict[str, respx.Route]
) -> None:
    cache_dir = tmp_path / "custom"
    runner.invoke(cli, ["--cache-dir", str(cache_dir), "list"])
    assert list(cache_dir.glob("*.json"))


# --- compare --------------------------------------------------------------


def test_compare_prints_a_report(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "compare", "--window", "day"])
    assert result.exit_code == 0, result.output
    assert "matched" in result.output
    assert "usgs events" in result.output
    assert "emsc events" in result.output


def test_compare_always_queries_both_sources(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    runner.invoke(cli, [*base_args, "compare"])
    assert mocked_apis["usgs"].call_count == 1
    assert mocked_apis["emsc"].call_count == 1


def test_compare_echoes_custom_tolerances(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(
        cli,
        [*base_args, "compare", "--time-tolerance", "30", "--distance-tolerance", "25"],
    )
    assert result.exit_code == 0
    assert "+/-30s and 25 km" in result.output


def test_compare_respects_min_mag(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "compare", "--min-mag", "9.9"])
    assert result.exit_code == 0
    assert "matched\t0" in result.output


def test_compare_limit_is_honoured(
    runner: CliRunner, base_args: list[str], mocked_apis: dict[str, respx.Route]
) -> None:
    result = runner.invoke(cli, [*base_args, "compare", "--limit", "1"])
    assert result.exit_code == 0
    assert "showing 1 of" in result.output or "matched\t0" in result.output


# --- export ---------------------------------------------------------------


def test_export_csv(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    out = tmp_path / "events.csv"
    result = runner.invoke(cli, [*base_args, "export", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output and "csv" in result.output
    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert rows and rows[0]["source"] == "usgs"


def test_export_json(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    out = tmp_path / "events.json"
    assert runner.invoke(cli, [*base_args, "export", "-o", str(out)]).exit_code == 0
    assert isinstance(json.loads(out.read_text(encoding="utf-8")), list)


def test_export_geojson(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    out = tmp_path / "events.geojson"
    assert runner.invoke(cli, [*base_args, "export", "-o", str(out)]).exit_code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["type"] == "FeatureCollection"


def test_export_format_overrides_the_extension(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    out = tmp_path / "events.csv"
    result = runner.invoke(
        cli, [*base_args, "export", "-o", str(out), "--format", "json"]
    )
    assert result.exit_code == 0
    assert isinstance(json.loads(out.read_text(encoding="utf-8")), list)


def test_export_to_an_unknown_extension_needs_an_explicit_format(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    result = runner.invoke(cli, [*base_args, "export", "-o", str(tmp_path / "x.txt")])
    assert result.exit_code == 2
    assert "cannot infer a format" in result.output


def test_export_with_explicit_format_to_any_extension(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    out = tmp_path / "x.txt"
    result = runner.invoke(
        cli, [*base_args, "export", "-o", str(out), "--format", "geojson"]
    )
    assert result.exit_code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["type"] == "FeatureCollection"


def test_export_requires_an_output_path(runner: CliRunner, base_args: list[str]) -> None:
    result = runner.invoke(cli, [*base_args, "export"])
    assert result.exit_code == 2
    assert "--output" in result.output


def test_export_rejects_an_unknown_format(
    runner: CliRunner, base_args: list[str], tmp_path: Path
) -> None:
    result = runner.invoke(
        cli, [*base_args, "export", "-o", str(tmp_path / "x.csv"), "--format", "xml"]
    )
    assert result.exit_code == 2


def test_export_applies_filters(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    out = tmp_path / "events.json"
    runner.invoke(cli, [*base_args, "export", "--min-mag", "9.9", "-o", str(out)])
    assert json.loads(out.read_text(encoding="utf-8")) == []


def test_export_both_sources(
    runner: CliRunner,
    base_args: list[str],
    tmp_path: Path,
    mocked_apis: dict[str, respx.Route],
) -> None:
    out = tmp_path / "events.json"
    runner.invoke(cli, [*base_args, "export", "--source", "both", "-o", str(out)])
    sources = {e["source"] for e in json.loads(out.read_text(encoding="utf-8"))}
    assert sources == {"usgs", "emsc"}


# --- main() exit statuses -------------------------------------------------


def test_main_returns_zero_on_success(
    tmp_path: Path, mocked_apis: dict[str, respx.Route]
) -> None:
    assert main(["--cache-dir", str(tmp_path / "c"), "list", "--limit", "1"]) == 0


def test_main_maps_usage_errors_to_exit_2(tmp_path: Path) -> None:
    assert main(["list", "--window", "decade"]) == 2


def test_main_reports_a_fetch_failure_as_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with respx.mock:
        respx.get(USGS_DAY_URL).mock(return_value=httpx.Response(503))
        status = main(["--cache-dir", str(tmp_path / "c"), "list"])
    assert status == 1
    assert "error:" in capsys.readouterr().err


def test_main_handles_an_abort(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise click.exceptions.Abort()

    monkeypatch.setattr(cli, "main", boom)
    assert main(["list"]) == 130
    assert "aborted" in capsys.readouterr().err


def test_main_with_no_argv_shows_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["quakewatch", "--help"])
    assert main() == 0

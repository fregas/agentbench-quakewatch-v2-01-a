from __future__ import annotations

import subprocess
import sys


def test_runs_as_a_module() -> None:
    """`python -m quakewatch` must work as an alternative to the entry point."""
    result = subprocess.run(
        [sys.executable, "-m", "quakewatch", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "list" in result.stdout


def test_module_reports_its_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "quakewatch", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    assert "quakewatch" in result.stdout

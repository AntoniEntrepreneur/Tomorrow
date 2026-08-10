from pathlib import Path

import pytest

from tomorrow.defaults import DayBounds, load_defaults


def test_load_defaults_reads_wake_and_sleep_from_repo_file(tmp_path: Path) -> None:
    defaults_file = tmp_path / "defaults.toml"
    defaults_file.write_text('wake = "07:00"\nsleep = "22:30"\n', encoding="utf-8")

    bounds = load_defaults(defaults_file)

    assert bounds == DayBounds(wake="07:00", sleep="22:30")

from datetime import date
from pathlib import Path

from tomorrow.cli import run_wizard


def test_wizard_accepts_defaults_and_writes_stub_plan(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()

    inputs = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))

    assert path == plans_dir / "2026-08-11.html"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Tuesday, 11 August 2026" in content
    assert "Wake 06:30" in content
    assert "Sleep 23:00" in content


def test_wizard_custom_wake_and_sleep_are_written(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )
    (tmp_path / "plans").mkdir()

    inputs = iter(["07:15", "22:00"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Wake 07:15" in content
    assert "Sleep 22:00" in content

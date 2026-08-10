from datetime import date
from pathlib import Path

import pytest

from tomorrow.cli import run_wizard
from tomorrow.domain import PlanBlockedError


def _write_defaults(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )
    (tmp_path / "plans").mkdir()


def test_wizard_accepts_defaults_and_writes_plan_with_no_drafts(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    plans_dir = tmp_path / "plans"

    # wake, sleep, draft capture (blank finishes with no Drafts)
    inputs = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))

    assert path == plans_dir / "2026-08-11.html"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Tuesday, 11 August 2026" in content
    assert "Wake 06:30" in content
    assert "Sleep 23:00" in content


def test_wizard_custom_wake_and_sleep_are_written(tmp_path: Path, monkeypatch) -> None:
    _write_defaults(tmp_path)

    inputs = iter(["07:15", "22:00", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Wake 07:15" in content
    assert "Sleep 22:00" in content


def test_wizard_promotes_draft_to_anchor_using_end_time(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Standup",  # capture a Draft
            "",  # finish capturing Drafts
            "07:00",  # Standup start
            "07:15",  # Standup end
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Standup" in content
    assert "07:00" in content
    assert "07:15" in content


def test_wizard_uses_library_default_duration_when_present(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    (tmp_path / "data" / "anchor_defaults.toml").write_text(
        "gym = 60\n", encoding="utf-8"
    )

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Gym",  # capture a Draft
            "",  # finish capturing Drafts
            "07:00",  # Gym start
            "",  # Gym end blank -> duration
            "",  # duration blank -> fall through to library default
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Gym" in content
    assert "07:00" in content
    assert "08:00" in content


def test_wizard_raises_and_writes_nothing_when_finalize_is_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    # Smoke-checks the adapter wiring to finalize_plan; finalization rules
    # themselves (overlap, out-of-bounds, etc.) are covered in test_domain.py.
    _write_defaults(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Early flight",  # capture a Draft
            "",  # finish capturing Drafts
            "05:00",  # starts before wake -> out of bounds
            "05:30",  # end
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    with pytest.raises(PlanBlockedError):
        run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))

    assert list((tmp_path / "plans").iterdir()) == []

from datetime import date
from pathlib import Path

import pytest

from tomorrow.cli import main, run_wizard
from tomorrow.domain import PlanBlockedError


def _write_defaults(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )
    (tmp_path / "plans").mkdir()


def _write_tuesday_template(tmp_path: Path) -> None:
    templates_dir = tmp_path / "data" / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "tuesday.toml").write_text(
        """
[[anchor]]
name = "Standup"
start = "07:00"
duration = 15

[[flex]]
name = "Sauna"
duration = 30
checklist = "sauna-kit"
""".strip(),
        encoding="utf-8",
    )


def _write_sauna_checklist(tmp_path: Path) -> None:
    checklists_dir = tmp_path / "data" / "checklists"
    checklists_dir.mkdir(parents=True)
    (checklists_dir / "sauna-kit.toml").write_text(
        'name = "Sauna kit"\nitems = ["Towel", "Flip-flops"]\n',
        encoding="utf-8",
    )


def _write_gym_checklist(tmp_path: Path) -> None:
    checklists_dir = tmp_path / "data" / "checklists"
    checklists_dir.mkdir(parents=True)
    (checklists_dir / "gym-bag.toml").write_text(
        'name = "Gym bag"\nitems = ["Towel", "Lock"]\n',
        encoding="utf-8",
    )


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
            "",  # Anchor (default)
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
            "",  # Anchor (default)
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


def test_wizard_places_flex_with_snap_and_writes_timeline(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Sauna",  # capture a Draft
            "",  # finish capturing Drafts
            "f",  # promote to Flex
            "30",  # duration
            "p",  # place
            "y",  # snap to gap start
            "1",  # first gap (wake to sleep)
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Sauna" in content
    assert 'class="block flex"' in content
    assert "06:30" in content
    assert "07:00" in content


def test_wizard_shrinks_flex_then_places_it(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Standup",  # capture a Draft
            "Lunch",  # capture a Draft
            "Deep work",  # capture a Draft
            "",  # finish capturing Drafts
            "",  # Standup -> Anchor
            "07:00",
            "07:15",
            "",  # Lunch -> Anchor
            "12:00",
            "13:00",
            "f",  # Deep work -> Flex
            "300",  # too long for 07:15–12:00 gap
            "s",  # shrink
            "60",
            "p",  # place
            "y",  # snap
            "2",  # gap after standup
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Deep work" in content
    assert "07:15" in content
    assert "08:15" in content


def test_wizard_drops_flex_and_finishes_without_timeline_footprint(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Maybe sauna",  # capture a Draft
            "",  # finish capturing Drafts
            "f",  # promote to Flex
            "30",  # duration
            "d",  # drop
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Maybe sauna" not in content
    assert 'class="block flex"' not in content


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
            "",  # Anchor (default)
            "05:00",  # starts before wake -> out of bounds
            "05:30",  # end
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    with pytest.raises(PlanBlockedError):
        run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))

    assert list((tmp_path / "plans").iterdir()) == []


def test_wizard_declining_weekday_template_leaves_empty_session(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "n",  # decline Tuesday template
            "",  # finish draft capture with no Drafts
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Standup" not in content
    assert "Sauna" not in content


def test_wizard_accepts_weekday_template_and_seeds_unplaced_flex(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "",  # accept Tuesday template (default yes)
            "",  # finish draft capture with no Drafts
            "p",  # place seeded Sauna flex
            "y",  # snap to gap start
            "2",  # gap after standup
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Standup" in content
    assert "07:00" in content
    assert "07:15" in content
    assert "Sauna" in content
    assert "07:15" in content
    assert "07:45" in content


def test_wizard_suggests_and_attaches_checklist_when_name_resembles_library(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    _write_gym_checklist(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Gym",  # capture a Draft
            "",  # finish capturing Drafts
            "",  # Anchor (default)
            "18:00",  # Gym start
            "19:00",  # Gym end
            "",  # accept suggested Checklist attach (default yes)
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Gym" in content
    assert 'checklistId: "gym-bag"' in content
    assert '"Gym bag"' in content
    assert '"Towel"' in content


def test_wizard_leaves_checklist_unattached_when_suggestion_is_declined(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    _write_gym_checklist(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "Gym",  # capture a Draft
            "",  # finish capturing Drafts
            "",  # Anchor (default)
            "18:00",  # Gym start
            "19:00",  # Gym end
            "n",  # decline suggested Checklist attach
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert "Gym" in content
    assert 'checklistId: "gym-bag"' not in content


def test_wizard_keeps_template_attached_checklist_without_reprompt(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    _write_sauna_checklist(tmp_path)

    inputs = iter(
        [
            "",  # wake default
            "",  # sleep default
            "",  # accept Tuesday template (default yes)
            "",  # finish draft capture with no Drafts
            "p",  # place seeded Sauna flex
            "y",  # snap to gap start
            "2",  # gap after standup
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")

    assert 'checklistId: "sauna-kit"' in content
    assert '"Sauna kit"' in content
    assert '"Flip-flops"' in content


def test_wizard_shows_weather_early_and_writes_one_liner_to_plan(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _write_defaults(tmp_path)

    def fake_weather(_data_dir, _plan_date, *, opener=None):
        return "18° / 24° · partly cloudy"

    monkeypatch.setattr("tomorrow.cli.try_fetch_weather", fake_weather)
    inputs = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")
    output = capsys.readouterr().out

    assert "Weather: 18° / 24° · partly cloudy" in output
    assert '<div class="plan-weather">18° / 24° · partly cloudy</div>' in content


def test_wizard_omits_weather_quietly_when_fetch_fails(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _write_defaults(tmp_path)
    monkeypatch.setattr("tomorrow.cli.try_fetch_weather", lambda *_args, **_kwargs: None)
    inputs = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))
    content = path.read_text(encoding="utf-8")
    output = capsys.readouterr().out

    assert "Weather:" not in output
    assert '<div class="plan-weather">' not in content
    assert path.exists()


def test_wizard_continues_when_weather_location_file_is_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    _write_defaults(tmp_path)
    data_dir = tmp_path / "data"
    (data_dir / "weather.toml").write_text("broken\n", encoding="utf-8")

    inputs = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    path = run_wizard(repo_root=tmp_path, today=date(2026, 8, 10))

    assert path.exists()
    assert '<div class="plan-weather">' not in path.read_text(encoding="utf-8")


def test_main_finds_clone_data_when_cwd_is_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    seen: dict[str, Path] = {}

    def fake_run_wizard(*, repo_root: Path, today=None) -> Path:
        seen["repo_root"] = repo_root
        return repo_root / "plans" / "unused.html"

    monkeypatch.setattr("tomorrow.cli.run_wizard", fake_run_wizard)
    main()

    assert (seen["repo_root"] / "data" / "defaults.toml").is_file()

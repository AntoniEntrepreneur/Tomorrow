from datetime import date, time, timedelta
from pathlib import Path

from tomorrow.domain import Anchor, Flex
from tomorrow.weekday_template import TemplateSeed, load_weekday_template, weekday_template_path


def test_weekday_template_path_uses_lowercase_weekday_name() -> None:
    path = weekday_template_path(Path("/repo/data"), date(2026, 8, 11))

    assert path == Path("/repo/data/templates/tuesday.toml")


def test_load_weekday_template_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert load_weekday_template(tmp_path / "missing.toml") is None


def test_load_weekday_template_parses_anchors_and_unplaced_flex(tmp_path: Path) -> None:
    template_file = tmp_path / "tuesday.toml"
    template_file.write_text(
        """
[[anchor]]
name = "Standup"
start = "07:00"
duration = 15

[[flex]]
name = "Sauna"
duration = 30
""".strip(),
        encoding="utf-8",
    )

    seed = load_weekday_template(template_file)

    assert seed == TemplateSeed(
        anchors=(
            Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15)),
        ),
        flexes=(Flex(name="Sauna", duration=timedelta(minutes=30)),),
    )


def test_load_weekday_template_preserves_optional_checklist_names(tmp_path: Path) -> None:
    template_file = tmp_path / "tuesday.toml"
    template_file.write_text(
        """
[[anchor]]
name = "Gym"
start = "18:00"
duration = 60
checklist = "gym-bag"

[[flex]]
name = "Sauna"
duration = 30
checklist = "sauna-kit"
""".strip(),
        encoding="utf-8",
    )

    seed = load_weekday_template(template_file)

    assert seed is not None
    assert seed.anchors[0].checklist == "gym-bag"
    assert seed.flexes[0].checklist == "sauna-kit"
    assert seed.flexes[0].start is None

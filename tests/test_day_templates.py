from datetime import date, time, timedelta
from pathlib import Path

from tomorrow.activity_templates import ActivityTemplate
from tomorrow.domain import Anchor, Flex
from tomorrow.day_templates import (
    TemplateSeed,
    day_template_path,
    default_day_template_path,
    load_day_template,
    load_day_template_name,
)


def test_day_template_path_uses_lowercase_weekday_name() -> None:
    path = day_template_path(Path("/repo/data"), date(2026, 8, 11))

    assert path == Path("/repo/data/templates/tuesday.toml")


def test_load_day_template_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert load_day_template(tmp_path / "missing.toml") is None


def test_load_day_template_parses_anchors_and_unplaced_flex(tmp_path: Path) -> None:
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

    seed = load_day_template(template_file)

    assert seed == TemplateSeed(
        anchors=(
            Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15)),
        ),
        flexes=(Flex(name="Sauna", duration=timedelta(minutes=30)),),
    )


def test_load_day_template_preserves_optional_checklist_names(tmp_path: Path) -> None:
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

    seed = load_day_template(template_file)

    assert seed is not None
    assert seed.anchors[0].checklist == "gym-bag"
    assert seed.flexes[0].checklist == "sauna-kit"
    assert seed.flexes[0].start is None


def test_load_day_template_resolves_activity_reference(tmp_path: Path) -> None:
    template_file = tmp_path / "tuesday.toml"
    template_file.write_text(
        """
[[anchor]]
activity = "therapy"

[[flex]]
activity = "deep-work"
""".strip(),
        encoding="utf-8",
    )
    library = {
        "therapy": ActivityTemplate(
            name="Therapy", duration=timedelta(minutes=50), start=time(16, 0)
        ),
        "deep-work": ActivityTemplate(
            name="Deep work", duration=timedelta(minutes=90), checklist="focus-kit"
        ),
    }

    seed = load_day_template(template_file, library)

    assert seed == TemplateSeed(
        anchors=(
            Anchor(name="Therapy", start=time(16, 0), duration=timedelta(minutes=50)),
        ),
        flexes=(
            Flex(
                name="Deep work",
                duration=timedelta(minutes=90),
                checklist="focus-kit",
            ),
        ),
    )


def test_load_day_template_drops_stale_activity_reference(tmp_path: Path) -> None:
    template_file = tmp_path / "tuesday.toml"
    template_file.write_text(
        """
[[anchor]]
activity = "deleted-activity"

[[flex]]
name = "Sauna"
duration = 30
""".strip(),
        encoding="utf-8",
    )

    seed = load_day_template(template_file, {})

    assert seed == TemplateSeed(
        anchors=(),
        flexes=(Flex(name="Sauna", duration=timedelta(minutes=30)),),
    )


def test_load_day_template_name_reads_name_field(tmp_path: Path) -> None:
    template_file = tmp_path / "usual-tuesday.toml"
    template_file.write_text('name = "Usual Tuesday"\n', encoding="utf-8")

    assert load_day_template_name(template_file) == "Usual Tuesday"


def test_load_day_template_name_falls_back_to_filename_stem(tmp_path: Path) -> None:
    template_file = tmp_path / "tuesday.toml"
    template_file.write_text(
        """
[[anchor]]
name = "Standup"
start = "07:00"
duration = 15
""".strip(),
        encoding="utf-8",
    )

    assert load_day_template_name(template_file) == "tuesday"


def test_load_day_template_name_falls_back_to_stem_when_file_missing(
    tmp_path: Path,
) -> None:
    assert load_day_template_name(tmp_path / "missing.toml") == "missing"


def test_default_day_template_path_falls_back_to_legacy_weekday_filename(
    tmp_path: Path,
) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tuesday.toml").write_text('name = "Tuesday"\n', encoding="utf-8")

    path = default_day_template_path(tmp_path, date(2026, 8, 11))

    assert path == templates / "tuesday.toml"


def test_default_day_template_path_prefers_weekday_field_over_filename(
    tmp_path: Path,
) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "usual-tuesday.toml").write_text(
        'name = "Usual Tuesday"\nweekday = "tuesday"\n', encoding="utf-8"
    )

    path = default_day_template_path(tmp_path, date(2026, 8, 11))

    assert path == templates / "usual-tuesday.toml"

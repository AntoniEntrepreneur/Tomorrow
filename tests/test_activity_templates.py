from datetime import time, timedelta
from pathlib import Path

from tomorrow.activity_templates import (
    ActivityTemplate,
    load_activity_template_library,
    suggest_activity_template,
)


def test_load_activity_template_library_reads_anchor_and_flex_shaped_entries(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "activity-templates"
    directory.mkdir()
    (directory / "therapy.toml").write_text(
        """
name = "Therapy"
start = "16:00"
duration = 50
""".strip(),
        encoding="utf-8",
    )
    (directory / "deep-work.toml").write_text(
        """
name = "Deep work"
duration = 90
checklist = "focus-kit"
""".strip(),
        encoding="utf-8",
    )

    library = load_activity_template_library(tmp_path)

    assert library == {
        "therapy": ActivityTemplate(
            name="Therapy", start=time(16, 0), duration=timedelta(minutes=50)
        ),
        "deep-work": ActivityTemplate(
            name="Deep work",
            duration=timedelta(minutes=90),
            checklist="focus-kit",
        ),
    }


def test_load_activity_template_library_returns_empty_when_dir_missing(
    tmp_path: Path,
) -> None:
    assert load_activity_template_library(tmp_path) == {}


def test_suggest_activity_template_matches_item_name_to_library_id(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "activity-templates"
    directory.mkdir()
    (directory / "deep-work.toml").write_text(
        'name = "Deep work"\nduration = 90\n', encoding="utf-8"
    )
    library = load_activity_template_library(tmp_path)

    assert suggest_activity_template("Deep work", library) == "deep-work"


def test_suggest_activity_template_returns_none_when_no_resemblance() -> None:
    assert suggest_activity_template("Gym", {}) is None

from pathlib import Path

from tomorrow.checklists import Checklist, load_checklist_library, suggest_checklist


def test_load_checklist_library_reads_named_lists_from_data_dir(tmp_path: Path) -> None:
    checklists_dir = tmp_path / "checklists"
    checklists_dir.mkdir()
    (checklists_dir / "gym-bag.toml").write_text(
        """
name = "Gym bag"
items = ["Water bottle", "Towel", "Lock"]
""".strip(),
        encoding="utf-8",
    )
    (checklists_dir / "sauna-kit.toml").write_text(
        """
name = "Sauna kit"
items = ["Towel", "Flip-flops"]
""".strip(),
        encoding="utf-8",
    )

    library = load_checklist_library(tmp_path)

    assert library == {
        "gym-bag": Checklist(name="Gym bag", items=("Water bottle", "Towel", "Lock")),
        "sauna-kit": Checklist(name="Sauna kit", items=("Towel", "Flip-flops")),
    }


def test_load_checklist_library_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    assert load_checklist_library(tmp_path) == {}


def test_suggest_checklist_matches_item_name_to_library_id(tmp_path: Path) -> None:
    checklists_dir = tmp_path / "checklists"
    checklists_dir.mkdir()
    (checklists_dir / "gym-bag.toml").write_text(
        'name = "Gym bag"\nitems = ["Towel"]\n', encoding="utf-8"
    )
    library = load_checklist_library(tmp_path)

    assert suggest_checklist("Gym", library) == "gym-bag"


def test_suggest_checklist_returns_none_when_no_resemblance(tmp_path: Path) -> None:
    checklists_dir = tmp_path / "checklists"
    checklists_dir.mkdir()
    (checklists_dir / "gym-bag.toml").write_text(
        'name = "Gym bag"\nitems = ["Towel"]\n', encoding="utf-8"
    )
    library = load_checklist_library(tmp_path)

    assert suggest_checklist("Standup", library) is None


def test_suggest_checklist_returns_none_for_empty_library() -> None:
    assert suggest_checklist("Gym", {}) is None

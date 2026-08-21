import argparse
from pathlib import Path
from typing import Sequence

from tomorrow.icloud import list_available_calendars
from tomorrow.session import run_session


def discover_repo_root(*starts: Path) -> Path:
    """Locate the clone that holds data/ and plans/, independent of cwd."""
    if not starts:
        starts = (Path(__file__).resolve().parent, Path.cwd())
    seen: set[Path] = set()
    for start in starts:
        resolved = start.resolve()
        for candidate in (resolved, *resolved.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            if (candidate / "data" / "defaults.toml").is_file():
                return candidate
    raise FileNotFoundError(
        "Could not find Tomorrow's data/defaults.toml. "
        "This tool expects the git clone that holds data/ next to the package."
    )


def _print_calendars() -> None:
    result = list_available_calendars()
    if result is None:
        print(
            "Calendar/Reminders access is not available. "
            "Grant access in System Settings and try again."
        )
        return
    calendars, reminder_lists = result
    print("Calendars:")
    for name in calendars:
        print(f"  {name}")
    print("Reminder lists:")
    for name in reminder_lists:
        print(f"  {name}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tomorrow")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "calendars", help="List calendars and reminder lists EventKit can see"
    )
    args = parser.parse_args(argv)

    if args.command == "calendars":
        _print_calendars()
        return

    repo_root = discover_repo_root()
    run_session(repo_root)


if __name__ == "__main__":
    main()

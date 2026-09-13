import argparse
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence
from urllib.request import Request
import webbrowser

from tomorrow.defaults import (
    DayBounds,
    DefaultsError,
    load_defaults,
    parse_time_of_day,
    save_defaults,
)
from tomorrow.icloud import list_available_calendars
from tomorrow.plan import default_plan_date, find_plan_to_open
from tomorrow.session import (
    _default_opener,
    run_library,
    run_session,
    session_exists_for_plan_date,
)


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


def _defaults_path(repo_root: Path) -> Path:
    return repo_root / "data" / "defaults.toml"


def _print_defaults(repo_root: Path) -> None:
    defaults = load_defaults(_defaults_path(repo_root))
    print(f"wake {defaults.wake} · sleep {defaults.sleep}")


def _session_keeps_bounds_until_reset(
    repo_root: Path, *, now: datetime | None, previous: DayBounds
) -> bool:
    plan_date = default_plan_date(now, wake=previous.wake)
    return session_exists_for_plan_date(repo_root, plan_date)


def _set_defaults(
    repo_root: Path, *, wake: str | None, sleep: str | None, now: datetime | None
) -> int:
    if wake is None and sleep is None:
        print("Pass --wake, --sleep, or both.")
        return 1

    path = _defaults_path(repo_root)
    previous = load_defaults(path)
    try:
        new_wake = parse_time_of_day(wake) if wake is not None else previous.wake
        new_sleep = parse_time_of_day(sleep) if sleep is not None else previous.sleep
        updated = DayBounds(wake=new_wake, sleep=new_sleep)
        save_defaults(path, updated)
    except DefaultsError as exc:
        print(str(exc))
        return 1

    if _session_keeps_bounds_until_reset(repo_root, now=now, previous=previous):
        print("Tonight's Session keeps its day bounds until Reset.")
    return 0


def _open_plan(repo_root: Path, *, now: datetime | None) -> None:
    plan_path = find_plan_to_open(repo_root, now=now)
    if plan_path is None:
        print("No Plan for today or tomorrow — run `tomorrow` to build one.")
        return
    webbrowser.open(plan_path.as_uri())
    print(plan_path)


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="tomorrow",
        description="With no command, bare `tomorrow` starts tonight's Session.",
    )
    subparsers = parser.add_subparsers(dest="command")
    commands: dict[str, argparse.ArgumentParser] = {}

    commands["calendars"] = subparsers.add_parser(
        "calendars", help="List calendars and reminder lists EventKit can see"
    )
    commands["library"] = subparsers.add_parser(
        "library",
        help="Open the Day Template, Activity Template and Checklist library",
    )
    defaults_parser = subparsers.add_parser(
        "defaults", help="Show or change your wake and sleep Defaults"
    )
    commands["defaults"] = defaults_parser
    defaults_subparsers = defaults_parser.add_subparsers(dest="defaults_command")
    set_parser = defaults_subparsers.add_parser(
        "set", help="Change your wake and/or sleep Defaults"
    )
    set_parser.add_argument("--wake", help="New wake time, as H:MM or HH:MM")
    set_parser.add_argument("--sleep", help="New sleep time, as H:MM or HH:MM")
    commands["plan"] = subparsers.add_parser(
        "plan", help="Open the newest Plan that isn't in the past"
    )
    help_parser = subparsers.add_parser(
        "help", help="Show help, the same as --help"
    )
    help_parser.add_argument(
        "topic", nargs="?", choices=list(commands), help="A command to show help for"
    )
    commands["help"] = help_parser
    return parser, commands


def main(
    argv: Sequence[str] | None = None,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> None:
    parser, commands = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "help":
        if args.topic is None:
            parser.print_help()
        else:
            commands[args.topic].print_help()
        return

    if args.command == "calendars":
        _print_calendars()
        return

    repo_root = discover_repo_root()

    if args.command == "library":
        run_library(repo_root, now=now, opener=opener)
        return

    if args.command == "defaults":
        if args.defaults_command == "set":
            exit_code = _set_defaults(
                repo_root, wake=args.wake, sleep=args.sleep, now=now
            )
            if exit_code != 0:
                raise SystemExit(exit_code)
            return
        _print_defaults(repo_root)
        return

    if args.command == "plan":
        _open_plan(repo_root, now=now)
        return

    run_session(repo_root, now=now, opener=opener)


if __name__ == "__main__":
    main()

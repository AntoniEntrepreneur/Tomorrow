from datetime import date, timedelta
from pathlib import Path

from tomorrow.defaults import DayBounds, load_anchor_default_minutes, load_defaults
from tomorrow.domain import (
    Anchor,
    Draft,
    PlanBlockedError,
    describe_blocker,
    finalize_plan,
    minutes_between,
    parse_clock,
)
from tomorrow.plan import default_plan_date, format_plan_date, write_finalized_plan


def _prompt_with_default(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def _capture_drafts() -> list[Draft]:
    print("Capture Drafts (blank to finish):")
    drafts: list[Draft] = []
    while True:
        name = input("Draft: ").strip()
        if not name:
            return drafts
        drafts.append(Draft(name=name))


def _prompt_required_duration_minutes(label: str) -> int:
    while True:
        raw = input(f"{label}: ").strip()
        try:
            minutes = int(raw)
        except ValueError:
            minutes = -1
        if minutes > 0:
            return minutes
        print("Duration is required as whole minutes, e.g. 30.")


def _promote_draft(draft: Draft, *, default_minutes_by_name: dict[str, int]) -> Anchor:
    print(f"\nPromote Draft '{draft.name}' to an Anchor")
    start = parse_clock(input("  Start time (HH:MM): ").strip())

    end_raw = input("  End time (blank to give a duration instead): ").strip()
    if end_raw:
        duration_minutes = minutes_between(start, parse_clock(end_raw))
    else:
        duration_raw = input("  Duration in minutes (blank to use default): ").strip()
        if duration_raw:
            duration_minutes = int(duration_raw)
        else:
            default_minutes = default_minutes_by_name.get(draft.name.lower())
            if default_minutes is not None:
                print(f"  Using default duration: {default_minutes} min")
                duration_minutes = default_minutes
            else:
                duration_minutes = _prompt_required_duration_minutes(
                    "  Duration in minutes (no default on file)"
                )

    return Anchor(name=draft.name, start=start, duration=timedelta(minutes=duration_minutes))


def run_wizard(*, repo_root: Path, today: date | None = None) -> Path:
    defaults_path = repo_root / "data" / "defaults.toml"
    defaults = load_defaults(defaults_path)
    default_minutes_by_name = load_anchor_default_minutes(
        repo_root / "data" / "anchor_defaults.toml"
    )

    plan_date = default_plan_date(today)
    print("Tomorrow — night-before planning\n")
    print(f"Plan date: {format_plan_date(plan_date)}\n")
    wake = _prompt_with_default("Wake time", defaults.wake)
    sleep = _prompt_with_default("Sleep time", defaults.sleep)
    bounds = DayBounds(wake=wake, sleep=sleep)

    drafts = _capture_drafts()
    anchors = [
        _promote_draft(draft, default_minutes_by_name=default_minutes_by_name)
        for draft in drafts
    ]

    result = finalize_plan(bounds=bounds, drafts=[], anchors=anchors)
    if not result.ok:
        print("\nPlan is blocked:")
        for blocker in result.blockers:
            print(f"  - {describe_blocker(blocker)}")
        raise PlanBlockedError(result.blockers)

    assert result.plan is not None
    path = write_finalized_plan(repo_root=repo_root, plan_date=plan_date, plan=result.plan)
    print(f"\nPlan written to {path}")
    return path


def main() -> None:
    repo_root = Path.cwd()
    try:
        run_wizard(repo_root=repo_root)
    except PlanBlockedError:
        pass


if __name__ == "__main__":
    main()

from datetime import date, time, timedelta
from pathlib import Path

from tomorrow.checklists import Checklist, load_checklist_library, suggest_checklist
from tomorrow.defaults import DayBounds, load_anchor_default_minutes, load_defaults
from tomorrow.domain import (
    Anchor,
    Draft,
    Flex,
    Gap,
    PlanBlockedError,
    compute_gaps,
    describe_blocker,
    finalize_plan,
    minutes_between,
    parse_clock,
    snap_flex_to_gap_start,
    validate_flex_placement,
)
from tomorrow.plan import default_plan_date, format_plan_date, write_finalized_plan
from tomorrow.weather import try_fetch_weather
from tomorrow.weekday_template import load_weekday_template, weekday_template_path


def _prompt_clock(label: str, *, default: str | None = None) -> time:
    while True:
        if default is not None:
            raw = input(f"{label} [{default}]: ").strip() or default
        else:
            raw = input(f"{label}: ").strip()
        try:
            return parse_clock(raw)
        except ValueError:
            print("Enter a clock time as HH:MM, e.g. 07:15.")


def _prompt_optional_clock(label: str) -> time | None:
    while True:
        raw = input(f"{label}: ").strip()
        if not raw:
            return None
        try:
            return parse_clock(raw)
        except ValueError:
            print("Enter a clock time as HH:MM, e.g. 07:15.")


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


def _prompt_yes_no(label: str, *, default_yes: bool = False) -> bool:
    suffix = "Y/n" if default_yes else "y/N"
    raw = input(f"{label} [{suffix}]: ").strip().lower()
    if not raw:
        return default_yes
    return raw in {"y", "yes"}


def _promote_draft_to_anchor(
    draft: Draft, *, default_minutes_by_name: dict[str, int]
) -> Anchor:
    print(f"\nPromote Draft '{draft.name}' to an Anchor")
    start = _prompt_clock("  Start time (HH:MM)")

    end = _prompt_optional_clock("  End time (blank to give a duration instead)")
    if end is not None:
        duration_minutes = minutes_between(start, end)
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


def _promote_draft_to_flex(
    draft: Draft, *, default_minutes_by_name: dict[str, int]
) -> Flex:
    print(f"\nPromote Draft '{draft.name}' to Flex")
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
    return Flex(name=draft.name, duration=timedelta(minutes=duration_minutes))


def _attach_checklist(item: Anchor | Flex, checklist_id: str) -> Anchor | Flex:
    if isinstance(item, Anchor):
        return Anchor(
            name=item.name,
            start=item.start,
            duration=item.duration,
            checklist=checklist_id,
        )
    return Flex(
        name=item.name,
        duration=item.duration,
        start=item.start,
        checklist=checklist_id,
    )


def _maybe_attach_checklist(
    item: Anchor | Flex,
    *,
    library: dict[str, Checklist],
) -> Anchor | Flex:
    if item.checklist is not None or not library:
        return item

    suggestion = suggest_checklist(item.name, library)
    if suggestion is None:
        return item

    checklist = library[suggestion]
    if _prompt_yes_no(
        f"  Attach Checklist '{checklist.name}' ({suggestion})?",
        default_yes=True,
    ):
        return _attach_checklist(item, suggestion)
    return item


def _promote_draft(
    draft: Draft,
    *,
    default_minutes_by_name: dict[str, int],
    library: dict[str, Checklist],
) -> Anchor | Flex:
    print(f"\nPromote Draft '{draft.name}'")
    while True:
        kind = input("  Anchor or Flex? [A/f]: ").strip().lower()
        if kind in {"", "a", "anchor"}:
            promoted = _promote_draft_to_anchor(
                draft, default_minutes_by_name=default_minutes_by_name
            )
            return _maybe_attach_checklist(promoted, library=library)
        if kind in {"f", "flex"}:
            promoted = _promote_draft_to_flex(
                draft, default_minutes_by_name=default_minutes_by_name
            )
            return _maybe_attach_checklist(promoted, library=library)
        print("  Enter A for Anchor or F for Flex.")


def _format_gap(gap_index: int, gap: Gap) -> str:
    return f"  {gap_index + 1}. {gap.start:%H:%M}–{gap.end:%H:%M}"


def _resolve_flexes(
    flexes: list[Flex],
    *,
    bounds: DayBounds,
    anchors: list[Anchor],
) -> list[Flex]:
    placed: list[Flex] = []
    pending = list(flexes)

    while pending:
        gaps = compute_gaps(bounds=bounds, anchors=anchors)
        flex = pending[0]
        duration_minutes = int(flex.duration.total_seconds() // 60)
        print(f"\nPlace Flex '{flex.name}' ({duration_minutes} min)")
        if gaps:
            print("Gaps:")
            for index, gap in enumerate(gaps):
                print(_format_gap(index, gap))
        else:
            print("No Gaps available.")

        action = input("  [P]lace / [S]hrink / [D]rop: ").strip().lower()
        if action in {"d", "drop"}:
            pending.pop(0)
            continue

        if action in {"s", "shrink"}:
            new_minutes = _prompt_required_duration_minutes("  New duration in minutes")
            flex = flex.with_duration(timedelta(minutes=new_minutes))
            pending[0] = flex
            continue

        if gaps and _prompt_yes_no("  Snap to a Gap start?", default_yes=False):
            while True:
                raw = input("  Gap number: ").strip()
                try:
                    gap_index = int(raw) - 1
                except ValueError:
                    gap_index = -1
                if 0 <= gap_index < len(gaps):
                    candidate = snap_flex_to_gap_start(flex, gaps[gap_index])
                    break
                print("  Enter a Gap number from the list.")
        else:
            candidate = flex.with_start(_prompt_clock("  Start time (HH:MM)"))

        if validate_flex_placement(
            candidate,
            gaps=gaps,
            anchors=anchors,
            other_flexes=placed,
        ):
            placed.append(candidate)
            pending.pop(0)
            continue

        print("  That placement does not fit. Try another start, shrink, or Drop.")

    return placed


def _seed_from_weekday_template(
    *,
    repo_root: Path,
    plan_date: date,
) -> tuple[list[Anchor], list[Flex]]:
    template_path = weekday_template_path(repo_root / "data", plan_date)
    template = load_weekday_template(template_path)
    if template is None:
        return [], []

    weekday = plan_date.strftime("%A")
    if not _prompt_yes_no(f"Use {weekday} Template?", default_yes=True):
        return [], []

    if template.anchors:
        print("Seeded Anchors:")
        for anchor in template.anchors:
            print(f"  - {anchor.name} ({anchor.start:%H:%M}, {int(anchor.duration.total_seconds() // 60)} min)")
    if template.flexes:
        print("Seeded Flex (not yet placed):")
        for flex in template.flexes:
            print(f"  - {flex.name} ({int(flex.duration.total_seconds() // 60)} min)")

    return list(template.anchors), list(template.flexes)


def run_wizard(*, repo_root: Path, today: date | None = None) -> Path:
    defaults_path = repo_root / "data" / "defaults.toml"
    defaults = load_defaults(defaults_path)
    default_minutes_by_name = load_anchor_default_minutes(
        repo_root / "data" / "anchor_defaults.toml"
    )
    checklist_library = load_checklist_library(repo_root / "data")

    plan_date = default_plan_date(today)
    print("Tomorrow — night-before planning\n")
    print(f"Plan date: {format_plan_date(plan_date)}\n")
    wake = _prompt_clock("Wake time", default=defaults.wake)
    sleep = _prompt_clock("Sleep time", default=defaults.sleep)
    bounds = DayBounds(wake=f"{wake:%H:%M}", sleep=f"{sleep:%H:%M}")

    weather = try_fetch_weather(repo_root / "data", plan_date)
    if weather:
        print(f"Weather: {weather}\n")

    anchors, flexes = _seed_from_weekday_template(repo_root=repo_root, plan_date=plan_date)

    drafts = _capture_drafts()
    for draft in drafts:
        promoted = _promote_draft(
            draft,
            default_minutes_by_name=default_minutes_by_name,
            library=checklist_library,
        )
        if isinstance(promoted, Anchor):
            anchors.append(promoted)
        else:
            flexes.append(promoted)

    flexes = _resolve_flexes(flexes, bounds=bounds, anchors=anchors)

    result = finalize_plan(bounds=bounds, drafts=[], anchors=anchors, flexes=flexes)
    if not result.ok:
        print("\nPlan is blocked:")
        for blocker in result.blockers:
            print(f"  - {describe_blocker(blocker)}")
        raise PlanBlockedError(result.blockers)

    assert result.plan is not None
    path = write_finalized_plan(
        repo_root=repo_root,
        plan_date=plan_date,
        plan=result.plan,
        weather=weather,
    )
    print(f"\nPlan written to {path}")
    return path


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


def main() -> None:
    repo_root = discover_repo_root()
    try:
        run_wizard(repo_root=repo_root)
    except PlanBlockedError:
        pass


if __name__ == "__main__":
    main()

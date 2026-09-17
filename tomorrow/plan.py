from datetime import date, datetime, time, timedelta
from pathlib import Path
import re
from typing import Mapping, Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tomorrow.checklists import Checklist, load_checklist_library
from tomorrow.defaults import DayBounds
from tomorrow.domain import (
    Anchor,
    FinalizedPlan,
    Flex,
    ToDo,
    is_next_day,
    minutes_since_wake,
    parse_clock,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

PLAN_FILENAME = "🌅 Tomorrow Plan.html"

_MARKER_PATTERN = re.compile(r'<meta name="tomorrow-plan" content="(\d{4}-\d{2}-\d{2})">')


class ForeignPlanFileError(Exception):
    """Raised when the Desktop Plan file exists but Tomorrow didn't write it."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"'{path.name}' is already on your Desktop and Tomorrow didn't write "
            "it. Move or rename it, then try again."
        )
        self.path = path


def default_plan_date(now: datetime | None = None, *, wake: str) -> date:
    current = now if now is not None else datetime.now()
    if current.time() < parse_clock(wake):
        return current.date()
    return current.date() + timedelta(days=1)


def format_plan_date(plan_date: date) -> str:
    # Portable long English date (strftime %-d is platform-specific).
    return f"{plan_date.strftime('%A')}, {plan_date.day} {plan_date.strftime('%B %Y')}"


def _plan_file_marker(path: Path) -> date | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _MARKER_PATTERN.search(text)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _is_foreign(path: Path) -> bool:
    return path.is_file() and _plan_file_marker(path) is None


def ensure_plan_file_not_foreign(*, output_dir: Path) -> None:
    path = output_dir / PLAN_FILENAME
    if _is_foreign(path):
        raise ForeignPlanFileError(path)


def describe_foreign_plan_file(*, output_dir: Path) -> str | None:
    """Return the refusal message if the Desktop Plan file is foreign, else None."""

    path = output_dir / PLAN_FILENAME
    if _is_foreign(path):
        return str(ForeignPlanFileError(path))
    return None


def discard_past_plans(*, output_dir: Path, now: datetime | None = None) -> None:
    today = (now if now is not None else datetime.now()).date()
    path = output_dir / PLAN_FILENAME
    marker = _plan_file_marker(path)
    if marker is not None and marker < today:
        path.unlink()


def find_plan_to_open(*, output_dir: Path, now: datetime | None = None) -> Path | None:
    """Return the Desktop Plan if its Plan date is today or tomorrow, else None."""

    discard_past_plans(output_dir=output_dir, now=now)
    path = output_dir / PLAN_FILENAME
    marker = _plan_file_marker(path)
    if marker is None:
        return None
    today = (now if now is not None else datetime.now()).date()
    if marker < today:
        return None
    return path


def _format_clock(value: time) -> str:
    return value.strftime("%H:%M")


def _clock_label(value: time, *, wake: time) -> str:
    label = _format_clock(value)
    if is_next_day(value, wake=wake):
        return f"{label} +1"
    return label


def _format_duration(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours}h"
    if minutes >= 60:
        hours = minutes // 60
        remainder = minutes % 60
        return f"{hours}h {remainder}m"
    return f"{minutes}m"


def _item_slug(name: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"
    return f"{slug}-{index}"


def _prep_bundles(
    *,
    anchors: Sequence[Anchor],
    flexes: Sequence[Flex],
    checklists: Mapping[str, Checklist],
    wake: time,
) -> list[dict[str, object]]:
    attached: list[tuple[Anchor | Flex, time]] = []
    for anchor in anchors:
        if anchor.checklist or anchor.checklist_items:
            attached.append((anchor, anchor.start))
    for flex in flexes:
        if (flex.checklist or flex.checklist_items) and flex.start is not None:
            attached.append((flex, flex.start))
    attached.sort(key=lambda entry: minutes_since_wake(entry[1], wake=wake))

    bundles: list[dict[str, object]] = []
    for index, (item, _) in enumerate(attached):
        if item.checklist_items:
            bundles.append(
                {
                    "item_id": _item_slug(item.name, index),
                    "item_name": item.name,
                    "checklist_id": None,
                    "checklist_name": None,
                    "rows": [{"label": label} for label in item.checklist_items],
                }
            )
            continue
        checklist_id = item.checklist
        assert checklist_id is not None
        checklist = checklists.get(checklist_id)
        if checklist is None:
            continue
        bundles.append(
            {
                "item_id": _item_slug(item.name, index),
                "item_name": item.name,
                "checklist_id": checklist_id,
                "checklist_name": checklist.name,
                "rows": [{"label": label} for label in checklist.items],
            }
        )
    return bundles


def _timeline_views(
    *,
    bounds: DayBounds,
    anchors: Sequence[Anchor],
    flexes: Sequence[Flex] = (),
) -> list[dict[str, str | int]]:
    wake = parse_clock(bounds.wake)
    sleep = parse_clock(bounds.sleep)
    total_minutes = minutes_since_wake(sleep, wake=wake)
    total_height = 420

    items: list[tuple[str, Anchor | Flex]] = [
        ("anchor", anchor) for anchor in anchors
    ] + [("flex", flex) for flex in flexes if flex.start is not None]
    items.sort(key=lambda entry: minutes_since_wake(entry[1].start, wake=wake))

    views: list[dict[str, str | int]] = []
    cursor = wake
    for kind, item in items:
        start = item.start
        assert start is not None
        if minutes_since_wake(start, wake=wake) > minutes_since_wake(cursor, wake=wake):
            gap_minutes = minutes_since_wake(start, wake=wake) - minutes_since_wake(
                cursor, wake=wake
            )
            views.append(
                {
                    "kind": "gap",
                    "label": f"Gap · {_format_duration(gap_minutes)}",
                    "min_height_px": max(20, int((gap_minutes / total_minutes) * total_height)),
                }
            )
        duration_minutes = int(item.duration.total_seconds() // 60)
        views.append(
            {
                "kind": kind,
                "name": item.name,
                "start_label": _clock_label(start, wake=wake),
                "end_label": _clock_label(item.end, wake=wake),
                "min_height_px": max(52, int((duration_minutes / total_minutes) * total_height)),
            }
        )
        cursor = item.end

    if minutes_since_wake(sleep, wake=wake) > minutes_since_wake(cursor, wake=wake):
        gap_minutes = minutes_since_wake(sleep, wake=wake) - minutes_since_wake(
            cursor, wake=wake
        )
        views.append(
            {
                "kind": "gap",
                "label": f"Gap · {_format_duration(gap_minutes)}",
                "min_height_px": max(20, int((gap_minutes / total_minutes) * total_height)),
            }
        )

    return views


def _todo_views(*, todos: Sequence[ToDo]) -> list[dict[str, str]]:
    return [
        {"slug": _item_slug(todo.name, index), "name": todo.name, "note": todo.note}
        for index, todo in enumerate(todos)
    ]


def render_plan(
    *,
    plan_date: date,
    bounds: DayBounds,
    anchors: Sequence[Anchor] = (),
    flexes: Sequence[Flex] = (),
    todos: Sequence[ToDo] = (),
    checklists: Mapping[str, Checklist] | None = None,
    weather: str | None = None,
) -> str:
    library = dict(checklists or ())
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("plan.html.j2")
    wake = parse_clock(bounds.wake)
    sleep = parse_clock(bounds.sleep)
    return template.render(
        plan_date_label=format_plan_date(plan_date),
        plan_date_key=plan_date.isoformat(),
        wake=bounds.wake,
        sleep=_clock_label(sleep, wake=wake),
        weather=weather,
        timeline=_timeline_views(bounds=bounds, anchors=anchors, flexes=flexes),
        prep_bundles=_prep_bundles(
            anchors=anchors, flexes=flexes, checklists=library, wake=wake
        ),
        todos=_todo_views(todos=todos),
    )


def write_plan(
    *,
    repo_root: Path,
    output_dir: Path,
    plan_date: date,
    bounds: DayBounds,
    anchors: Sequence[Anchor] = (),
    flexes: Sequence[Flex] = (),
    todos: Sequence[ToDo] = (),
    checklists: Mapping[str, Checklist] | None = None,
    weather: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / PLAN_FILENAME
    ensure_plan_file_not_foreign(output_dir=output_dir)
    library = dict(checklists or load_checklist_library(repo_root / "data"))
    path.write_text(
        render_plan(
            plan_date=plan_date,
            bounds=bounds,
            anchors=anchors,
            flexes=flexes,
            todos=todos,
            checklists=library,
            weather=weather,
        ),
        encoding="utf-8",
    )
    return path


def write_finalized_plan(
    *,
    repo_root: Path,
    output_dir: Path,
    plan_date: date,
    plan: FinalizedPlan,
    weather: str | None = None,
) -> Path:
    return write_plan(
        repo_root=repo_root,
        output_dir=output_dir,
        plan_date=plan_date,
        bounds=plan.bounds,
        anchors=plan.anchors,
        flexes=plan.flexes,
        todos=plan.todos,
        weather=weather,
    )

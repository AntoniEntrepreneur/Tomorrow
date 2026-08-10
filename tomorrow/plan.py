from datetime import date, time, timedelta
from pathlib import Path
import re
from typing import Mapping, Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tomorrow.checklists import Checklist, load_checklist_library
from tomorrow.defaults import DayBounds
from tomorrow.domain import Anchor, FinalizedPlan, Flex, minutes_since_midnight, parse_clock

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def default_plan_date(today: date | None = None) -> date:
    base = today or date.today()
    return base + timedelta(days=1)


def format_plan_date(plan_date: date) -> str:
    # Portable long English date (strftime %-d is platform-specific).
    return f"{plan_date.strftime('%A')}, {plan_date.day} {plan_date.strftime('%B %Y')}"


def plan_filename(plan_date: date) -> str:
    return f"{plan_date.isoformat()}.html"


def _format_clock(value: time) -> str:
    return value.strftime("%H:%M")


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
) -> list[dict[str, object]]:
    attached: list[tuple[Anchor | Flex, time]] = []
    for anchor in anchors:
        if anchor.checklist:
            attached.append((anchor, anchor.start))
    for flex in flexes:
        if flex.checklist and flex.start is not None:
            attached.append((flex, flex.start))
    attached.sort(key=lambda entry: minutes_since_midnight(entry[1]))

    bundles: list[dict[str, object]] = []
    for index, (item, _) in enumerate(attached):
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
    total_minutes = minutes_since_midnight(sleep) - minutes_since_midnight(wake)
    total_height = 420

    items: list[tuple[str, Anchor | Flex]] = [
        ("anchor", anchor) for anchor in anchors
    ] + [("flex", flex) for flex in flexes if flex.start is not None]
    items.sort(key=lambda entry: minutes_since_midnight(entry[1].start))

    views: list[dict[str, str | int]] = []
    cursor = wake
    for kind, item in items:
        start = item.start
        assert start is not None
        if minutes_since_midnight(start) > minutes_since_midnight(cursor):
            gap_minutes = minutes_since_midnight(start) - minutes_since_midnight(cursor)
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
                "start_label": _format_clock(start),
                "end_label": _format_clock(item.end),
                "min_height_px": max(52, int((duration_minutes / total_minutes) * total_height)),
            }
        )
        cursor = item.end

    if minutes_since_midnight(sleep) > minutes_since_midnight(cursor):
        gap_minutes = minutes_since_midnight(sleep) - minutes_since_midnight(cursor)
        views.append(
            {
                "kind": "gap",
                "label": f"Gap · {_format_duration(gap_minutes)}",
                "min_height_px": max(20, int((gap_minutes / total_minutes) * total_height)),
            }
        )

    return views


def render_plan(
    *,
    plan_date: date,
    bounds: DayBounds,
    anchors: Sequence[Anchor] = (),
    flexes: Sequence[Flex] = (),
    checklists: Mapping[str, Checklist] | None = None,
    weather: str | None = None,
) -> str:
    library = dict(checklists or ())
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("plan.html.j2")
    return template.render(
        plan_date_label=format_plan_date(plan_date),
        plan_date_key=plan_date.isoformat(),
        wake=bounds.wake,
        sleep=bounds.sleep,
        weather=weather,
        timeline=_timeline_views(bounds=bounds, anchors=anchors, flexes=flexes),
        prep_bundles=_prep_bundles(anchors=anchors, flexes=flexes, checklists=library),
    )


def write_plan(
    *,
    repo_root: Path,
    plan_date: date,
    bounds: DayBounds,
    anchors: Sequence[Anchor] = (),
    flexes: Sequence[Flex] = (),
    checklists: Mapping[str, Checklist] | None = None,
    weather: str | None = None,
) -> Path:
    plans_dir = repo_root / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / plan_filename(plan_date)
    library = dict(checklists or load_checklist_library(repo_root / "data"))
    path.write_text(
        render_plan(
            plan_date=plan_date,
            bounds=bounds,
            anchors=anchors,
            flexes=flexes,
            checklists=library,
            weather=weather,
        ),
        encoding="utf-8",
    )
    return path


def write_finalized_plan(
    *,
    repo_root: Path,
    plan_date: date,
    plan: FinalizedPlan,
    weather: str | None = None,
) -> Path:
    return write_plan(
        repo_root=repo_root,
        plan_date=plan_date,
        bounds=plan.bounds,
        anchors=plan.anchors,
        flexes=plan.flexes,
        weather=weather,
    )

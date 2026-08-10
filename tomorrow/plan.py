from datetime import date, time, timedelta
from pathlib import Path
from typing import Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tomorrow.defaults import DayBounds
from tomorrow.domain import Anchor, FinalizedPlan

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


def _anchor_views(anchors: Sequence[Anchor]) -> list[dict[str, str]]:
    return [
        {
            "name": anchor.name,
            "start_label": _format_clock(anchor.start),
            "end_label": _format_clock(anchor.end),
        }
        for anchor in sorted(anchors, key=lambda anchor: anchor.start)
    ]


def render_plan(*, plan_date: date, bounds: DayBounds, anchors: Sequence[Anchor] = ()) -> str:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("plan.html.j2")
    return template.render(
        plan_date_label=format_plan_date(plan_date),
        wake=bounds.wake,
        sleep=bounds.sleep,
        anchors=_anchor_views(anchors),
    )


def write_plan(
    *,
    repo_root: Path,
    plan_date: date,
    bounds: DayBounds,
    anchors: Sequence[Anchor] = (),
) -> Path:
    plans_dir = repo_root / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / plan_filename(plan_date)
    path.write_text(
        render_plan(plan_date=plan_date, bounds=bounds, anchors=anchors),
        encoding="utf-8",
    )
    return path


def write_finalized_plan(*, repo_root: Path, plan_date: date, plan: FinalizedPlan) -> Path:
    return write_plan(
        repo_root=repo_root,
        plan_date=plan_date,
        bounds=plan.bounds,
        anchors=plan.anchors,
    )

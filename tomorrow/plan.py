from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tomorrow.defaults import DayBounds

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def default_plan_date(today: date | None = None) -> date:
    base = today or date.today()
    return base + timedelta(days=1)


def format_plan_date(plan_date: date) -> str:
    # Portable long English date (strftime %-d is platform-specific).
    return f"{plan_date.strftime('%A')}, {plan_date.day} {plan_date.strftime('%B %Y')}"


def plan_filename(plan_date: date) -> str:
    return f"{plan_date.isoformat()}.html"


def render_stub_plan(*, plan_date: date, bounds: DayBounds) -> str:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("stub_plan.html.j2")
    return template.render(
        plan_date_label=format_plan_date(plan_date),
        wake=bounds.wake,
        sleep=bounds.sleep,
    )


def write_stub_plan(*, repo_root: Path, plan_date: date, bounds: DayBounds) -> Path:
    plans_dir = repo_root / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / plan_filename(plan_date)
    path.write_text(
        render_stub_plan(plan_date=plan_date, bounds=bounds),
        encoding="utf-8",
    )
    return path

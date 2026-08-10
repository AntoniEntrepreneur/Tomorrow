from datetime import date
from pathlib import Path

from tomorrow.defaults import DayBounds, load_defaults
from tomorrow.plan import default_plan_date, format_plan_date, write_stub_plan


def _prompt_with_default(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def run_wizard(*, repo_root: Path, today: date | None = None) -> Path:
    defaults_path = repo_root / "data" / "defaults.toml"
    defaults = load_defaults(defaults_path)

    plan_date = default_plan_date(today)
    print("Tomorrow — night-before planning\n")
    print(f"Plan date: {format_plan_date(plan_date)}\n")
    wake = _prompt_with_default("Wake time", defaults.wake)
    sleep = _prompt_with_default("Sleep time", defaults.sleep)

    bounds = DayBounds(wake=wake, sleep=sleep)
    path = write_stub_plan(repo_root=repo_root, plan_date=plan_date, bounds=bounds)
    print(f"\nPlan written to {path}")
    return path


def main() -> None:
    repo_root = Path.cwd()
    run_wizard(repo_root=repo_root)


if __name__ == "__main__":
    main()

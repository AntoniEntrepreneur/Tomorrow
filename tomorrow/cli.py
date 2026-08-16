from pathlib import Path

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


def main() -> None:
    repo_root = discover_repo_root()
    run_session(repo_root)


if __name__ == "__main__":
    main()

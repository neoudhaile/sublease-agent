"""The `sublease` command."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from sublease.cli.doctor import run_checks
from sublease.cli.init import DEFAULT_TEMPLATES, build_profile
from sublease.llm.registry import DEFAULT_MODEL, DEFAULT_PROVIDER, get_provider
from sublease.store.db import connect, migrate
from sublease.store.repositories import ProfileRepo

app = typer.Typer(help="Find a subletter for your place.", no_args_is_help=True)
console = Console()


def _provider(name: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL):
    try:
        return get_provider(name, model=model)
    except Exception as exc:      # noqa: BLE001 — doctor reports, never crashes
        console.print(f"[yellow]provider unavailable: {exc}[/yellow]")
        return None


@app.command()
def doctor(provider: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL) -> None:
    """Check that everything a run needs is present and working."""
    conn = connect()
    checks = run_checks(conn=conn, provider=_provider(provider, model))
    table = Table(title="sublease doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")
    for check in checks:
        mark = "[green]ok[/green]" if check.ok else "[red]FAIL[/red]"
        table.add_row(check.name, mark, check.detail)
    console.print(table)
    raise typer.Exit(0 if all(c.ok for c in checks) else 1)


@app.command()
def init() -> None:
    """Create a profile: your place, your dates, your constraints."""
    conn = connect()
    migrate(conn)

    answers: dict = {
        "name": typer.prompt("A name for this listing", default="My sublet"),
        "neighborhood": typer.prompt("Neighborhood"),
        "unit_type": typer.prompt("Renting a room or the whole unit?",
                                  default="room"),
        "window_start": typer.prompt("First date available (YYYY-MM-DD)"),
        "window_end": typer.prompt("Last date available (YYYY-MM-DD)"),
        "total_price": float(typer.prompt("Total price for the whole window")),
        "allow_split": typer.confirm(
            "Would you accept several subletters covering different dates?",
            default=True),
        "max_people_per_room": int(typer.prompt(
            "Maximum people sharing the room", default="1")),
    }

    preference = typer.prompt(
        "Gender preference, if any (male/female/none). This is a soft ranking "
        "signal only, and is used only when someone states it themselves",
        default="none")
    answers["gender_preference"] = None if preference == "none" else preference

    sources: list[dict] = []
    console.print("\nAdd the Facebook groups to watch. Slug is the part of the "
                  "group URL after /groups/. Leave the slug blank to finish.")
    while True:
        slug = typer.prompt("  group slug", default="", show_default=False)
        if not slug:
            break
        sources.append({"slug": slug,
                        "name": typer.prompt("  group name", default=slug),
                        "method": "forage"})
    answers["sources"] = sources

    profile = ProfileRepo(conn).save(build_profile(answers))
    console.print(f"\n[green]Saved profile {profile.id}: {profile.name}[/green]")
    console.print(f"Window is {profile.window.days} days across "
                  f"{len(profile.sources)} group(s).")
    console.print("Edit your outreach copy any time; the default is:\n")
    console.print(f"  {DEFAULT_TEMPLATES['outreach_message']}\n")
    console.print("Next: run [bold]sublease doctor[/bold], then "
                  "[bold]sublease run[/bold].")


if __name__ == "__main__":
    app()

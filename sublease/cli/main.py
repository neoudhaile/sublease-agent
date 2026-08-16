"""The `sublease` command."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from sublease.cli.doctor import run_checks
from sublease.cli.init import DEFAULT_TEMPLATES, build_profile, parse_date
from sublease.errors import ConfigError
from sublease.llm.registry import DEFAULT_MODEL, DEFAULT_PROVIDER, get_provider
from sublease.store.db import connect, migrate
from sublease.store.repositories import ProfileRepo

app = typer.Typer(help="Find a subletter for your place.", no_args_is_help=True)
console = Console()


def _provider(name: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL):
    """Return (provider, error). `error` carries the reason construction
    failed so callers (doctor's table) can show it, not just a printed
    warning that scrolls away."""
    try:
        return get_provider(name, model=model), None
    except Exception as exc:      # noqa: BLE001 — doctor reports, never crashes
        console.print(f"[yellow]provider unavailable: {exc}[/yellow]")
        return None, str(exc)


def _prompt_date(label: str, field: str) -> str:
    """Prompt for a date, re-prompting in plain language on a bad format.

    `build_profile` (called later, on the same string) validates again on
    its own — this loop is the friendly front door, not the only guard.
    """
    while True:
        raw = typer.prompt(label)
        try:
            parse_date(field, raw)
        except ConfigError as exc:
            console.print(f"[red]{exc}[/red]")
            continue
        return raw


@app.command()
def doctor(provider: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL) -> None:
    """Check that everything a run needs is present and working."""
    conn = connect()
    resolved_provider, provider_error = _provider(provider, model)
    checks = run_checks(conn=conn, provider=resolved_provider,
                        provider_error=provider_error)
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

    # A profile already exists → ask before silently creating a second one.
    # `ProfileRepo.list()` is ordered deterministically (oldest first), so
    # `[0]` is always the same "active" profile every other command assumes.
    existing = ProfileRepo(conn).list()
    replace_id: int | None = None
    if existing:
        current = existing[0]
        console.print(
            f"\n[yellow]A profile already exists:[/yellow] {current.name} "
            f"({current.window.start.isoformat()} to {current.window.end.isoformat()})")
        if len(existing) > 1:
            console.print(f"({len(existing)} profiles total — the active one "
                          "is the first one created.)")
        if not typer.confirm(
                "Replace it with what you're about to enter? "
                "Choosing no cancels and leaves it untouched", default=False):
            console.print("[green]Cancelled.[/green] The database was not changed.")
            raise typer.Exit(0)
        replace_id = current.id

    answers: dict = {
        "name": typer.prompt("A name for this listing", default="My sublet"),
        "neighborhood": typer.prompt("Neighborhood"),
        "unit_type": typer.prompt("Renting a room or the whole unit?",
                                  default="room"),
        "window_start": _prompt_date("First date available (YYYY-MM-DD)",
                                     "window_start"),
        "window_end": _prompt_date("Last date available (YYYY-MM-DD)",
                                   "window_end"),
        "total_price": float(typer.prompt("Total price for the whole window")),
        "allow_split": typer.confirm(
            "Would you accept several subletters covering different dates?",
            default=True),
        "max_people_per_room": int(typer.prompt(
            "Maximum people sharing the room", default="1")),
    }

    preference = typer.prompt(
        "Do you have a preference for the gender of the person renting from "
        "you? It's entirely optional, and it only ranks candidates — it "
        "never excludes anyone, a non-matching person just drops one tier "
        "in the results. It's applied only when someone states their own "
        "gender in their own post; it is never guessed from a name or a "
        "photo. Enter male, female, or none",
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

    new_profile = build_profile(answers)
    if replace_id is not None:
        new_profile.id = replace_id
    profile = ProfileRepo(conn).save(new_profile)
    console.print(f"\n[green]Saved profile {profile.id}: {profile.name}[/green]")
    console.print(f"Window is {profile.window.days} days across "
                  f"{len(profile.sources)} group(s).")
    console.print("Edit your outreach copy any time; the default is:\n")
    console.print(f"  {DEFAULT_TEMPLATES['outreach_message']}\n")
    console.print("Next: run [bold]sublease doctor[/bold], then "
                  "[bold]sublease run[/bold].")


if __name__ == "__main__":
    app()

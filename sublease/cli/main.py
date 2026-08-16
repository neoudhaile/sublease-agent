"""The `sublease` command."""
from __future__ import annotations

import os
from datetime import date as date_cls, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from sublease.cli.doctor import run_checks
from sublease.cli.init import DEFAULT_TEMPLATES, build_profile, parse_date
from sublease.cli.report import candidates_table, coverage_lines, rows_to_csv
from sublease.errors import ConfigError
from sublease.llm.registry import DEFAULT_MODEL, DEFAULT_PROVIDER, get_provider
from sublease.match.coverage import coverage as compute_coverage
from sublease.match.ranking import rank
from sublease.pipeline import run_pipeline
from sublease.sources.registry import get_source
from sublease.store.db import connect, migrate
from sublease.store.repositories import (
    CandidateRepo, EnrichmentRepo, ExtractionRepo, PostRepo, ProfileRepo,
)

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


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "posts.json"


def build_sources(profile, fixtures_path: Path | None = None) -> dict:
    """Construct one adapter per configured source."""
    built = {}
    for cfg in profile.sources:
        method = "fixtures" if fixtures_path else cfg.method
        kwargs: dict = {}
        if method == "fixtures":
            kwargs["path"] = fixtures_path or FIXTURES
        elif method == "apify":
            kwargs["token"] = os.environ.get("APIFY_TOKEN", "")
        try:
            built[cfg] = get_source(method, **kwargs)
        except Exception as exc:      # noqa: BLE001 — reported per source by the run
            console.print(f"[yellow]{cfg.name}: {exc}[/yellow]")
    return built


def _active_profile(conn):
    profiles = ProfileRepo(conn).list()
    if not profiles:
        console.print("[red]No profile yet. Run `sublease init` first.[/red]")
        raise typer.Exit(1)
    return profiles[0]


@app.command()
def run(fixtures: bool = typer.Option(False, help="Use synthetic posts, no Facebook."),
        days: int = typer.Option(21, help="How far back to scrape."),
        limit: int = typer.Option(300, help="Max posts per source."),
        dry_run: bool = typer.Option(False, help="Report without writing."),
        provider: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL) -> None:
    """Scrape, extract, match, and store candidates."""
    conn = connect()
    migrate(conn)
    profile = _active_profile(conn)

    llm, llm_error = _provider(provider, model)
    if llm is None:
        console.print(f"[red]provider unavailable: {llm_error}[/red]")
        raise typer.Exit(1)

    today = date_cls.today()
    report = run_pipeline(
        conn, profile, llm, today,
        sources=build_sources(profile, FIXTURES if fixtures else None),
        since=today - timedelta(days=days),
        limit=limit, dry_run=dry_run)

    for error in report.source_errors:
        console.print(f"[yellow]source failed — {error}[/yellow]")
    console.print(
        f"Scraped {report.scraped} posts ({report.new_posts} new). "
        f"Extracted {report.extracted}, enriched {report.enriched}. "
        f"{report.candidates} candidates ({report.new_candidates} new).")
    if dry_run:
        console.print("[yellow]dry run — nothing was written[/yellow]")


@app.command()
def candidates(tier: str = typer.Option(None, help="Only this tier (A/B/C/D)."),
               new: bool = typer.Option(False, help="Only ones you haven't contacted."),
               as_csv: bool = typer.Option(False, "--csv", help="Emit CSV.")) -> None:
    """List ranked candidates."""
    conn = connect()
    profile = _active_profile(conn)
    rows = CandidateRepo(conn).list(profile.id, tier=tier, new_only=new)
    if as_csv:
        print(rows_to_csv(rows), end="")
    else:
        console.print(candidates_table(rows))


@app.command()
def coverage() -> None:
    """Show the best single candidates and the best combination."""
    conn = connect()
    profile = _active_profile(conn)
    ranked = rank(
        {p["id"]: p for p in PostRepo(conn).get_all()},
        ExtractionRepo(conn).get_all(),
        EnrichmentRepo(conn).by_post_id(),
        profile,
    )
    plan = compute_coverage(ranked, profile.window.start, profile.window.end,
                            max_split=profile.window.max_split)
    for line in coverage_lines(plan):
        console.print(line)


if __name__ == "__main__":
    app()

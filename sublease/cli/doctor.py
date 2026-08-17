"""Pre-flight checks.

A scrape run takes twenty minutes. Discovering a stale Facebook session at
minute nineteen is the failure this command exists to prevent. Every check
returns a result rather than raising, so one failure never hides the rest.
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass

from sublease.errors import SubleaseError
from sublease.store.db import current_version
from sublease.store.repositories import ProfileRepo
from sublease.store.schema import MIGRATIONS


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _check_database(conn: sqlite3.Connection) -> Check:
    try:
        version = current_version(conn)
    except SubleaseError as exc:
        return Check("database", False, str(exc))
    if version < len(MIGRATIONS):
        return Check("database", False,
                     f"schema is at v{version}, expected v{len(MIGRATIONS)}; "
                     "run `sublease init` to migrate")
    return Check("database", True, f"schema v{version}")


def _check_provider(provider, error: str | None = None, probe: bool = False) -> Check:
    """Default (`probe=False`): a cheap, offline check via `provider.ready()`
    — credentials present, client constructs. No request is made, so nothing
    is billed, and connectivity is NOT verified.

    `probe=True` (from `sublease doctor --probe`): the full round-trip via
    `provider.health()`, which issues a real completion request — billable
    for the Anthropic and OpenAI providers.
    """
    if provider is None:
        return Check("llm provider", False, error or "no provider configured")
    health = provider.health() if probe else provider.ready()
    return Check("llm provider", health.ok, health.detail)


def _check_forage(binary: str, which) -> Check:
    path = which(binary)
    if not path:
        return Check("forage", False,
                     f"`{binary}` is not installed or not on PATH; "
                     "Facebook scraping will be skipped")
    return Check("forage", True, f"found at {path}")


def _check_profile(conn: sqlite3.Connection) -> Check:
    try:
        profiles = ProfileRepo(conn).list()
    except sqlite3.Error as exc:
        return Check("profile", False, f"could not read profiles: {exc}")
    if not profiles:
        return Check("profile", False, "no profile yet — run `sublease init`")
    return Check("profile", True,
                 f"{len(profiles)} profile(s); active: {profiles[0].name}")


def run_checks(conn: sqlite3.Connection | None = None, provider=None,
               provider_error: str | None = None,
               forage_binary: str = "forage", which=shutil.which,
               probe: bool = False) -> list[Check]:
    return [
        _check_database(conn),
        _check_provider(provider, provider_error, probe),
        _check_forage(forage_binary, which),
        _check_profile(conn),
    ]

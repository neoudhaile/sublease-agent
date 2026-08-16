"""Rendering for the read-only commands. Pure functions, so they are testable
without a terminal.
"""
from __future__ import annotations

import csv
import io

from rich.table import Table

from sublease.match.types import CoveragePlan

CSV_COLUMNS = [
    "tier", "tier_reason", "fit", "days_covered", "wants_start", "wants_end",
    "author_name", "author_url", "post_url", "group_name", "also_posted_in",
    "status", "draft", "post_text",
]
TIER_COLOR = {"A": "green", "B": "cyan", "C": "yellow", "D": "red"}


def candidates_table(rows: list[dict]) -> Table:
    table = Table(title="Candidates")
    for header in ("tier", "name", "days", "wants", "group", "status", "why"):
        table.add_column(header)
    for row in rows:
        tier = row.get("tier") or "?"
        table.add_row(
            f"[{TIER_COLOR.get(tier, 'white')}]{tier}[/]",
            row.get("author_name") or "unknown",
            f"{row.get('days_covered', 0)}",
            f"{row.get('wants_start') or '?'} → {row.get('wants_end') or 'open'}",
            row.get("group_name") or "",
            row.get("status") or "",
            row.get("tier_reason") or "",
        )
    return table


def rows_to_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        flat = dict(row)
        also = flat.get("also_posted_in") or []
        flat["also_posted_in"] = "; ".join(also) if isinstance(also, list) else also
        writer.writerow(flat)
    return buffer.getvalue()


def coverage_lines(plan: CoveragePlan) -> list[str]:
    lines = [f"Window is {plan.window_days} days."]

    if plan.singles:
        lines.append("")
        lines.append(f"Single candidates covering (nearly) the whole window "
                     f"({len(plan.singles)}):")
        for c in plan.singles:
            span = f"{c.wants_start or 'open'} → {c.wants_end or 'open'}"
            lines.append(f"  {c.name}: {span} "
                         f"({c.days_covered}/{plan.window_days} days)")

    if plan.combination:
        lines.append("")
        lines.append(f"Best combination — {len(plan.combination)} people covering "
                     f"{plan.combination_days}/{plan.window_days} days:")
        for c in plan.combination:
            span = f"{c.wants_start or 'open'} → {c.wants_end or 'open'}"
            lines.append(f"  {c.name}: {span}")
    elif not plan.singles:
        lines.append("")
        lines.append("No candidates overlap your window yet.")

    return lines

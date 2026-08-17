"""Rendering for `sublease price`. Pure functions: a `PricingResult` in,
strings out — same pattern as `sublease/cli/report.py`.

Estimate mode is labelled on every line it produces. That is deliberate, not
decoration: presenting a guess as though real comps existed is the one
outcome this whole feature must never produce, since the user prices a real
room off of it.
"""
from __future__ import annotations

from sublease.pricing.service import PricingResult

THIN_NOTE = "(thin sample — fewer than 5 comps; treat this with extra caution)"


def price_lines(result: PricingResult) -> list[str]:
    if result.mode == "estimate":
        return _estimate_lines(result)
    return _comps_lines(result)


def _estimate_lines(result: PricingResult) -> list[str]:
    lines = [
        f"[ESTIMATE] No real comps collected yet for {result.place.neighborhood} "
        "— this is the model's own knowledge, not an actual listing.",
    ]
    if result.estimate_low is None or result.estimate_high is None:
        lines.append("[ESTIMATE] unavailable — the model did not return a usable range.")
        return lines
    total_low = result.estimate_low * result.nights
    total_high = result.estimate_high * result.nights
    lines.append(
        f"[ESTIMATE] ${result.estimate_low:.0f}–${result.estimate_high:.0f}/night "
        f"· {result.nights} nights → "
        f"${total_low:,.0f}–${total_high:,.0f} total (estimated)")
    if result.estimate_note:
        lines.append(f"[ESTIMATE] {result.estimate_note}")
    lines.append("Run `sublease run` to collect real listings — "
                 "`sublease price` uses real comps once they exist.")
    return lines


def _comps_lines(result: PricingResult) -> list[str]:
    comp_set = result.comp_set
    if comp_set is None or comp_set.count == 0:
        dropped = comp_set.dropped if comp_set else 0
        return [
            f"No comparable {result.place.unit_type} listings found for "
            f"{result.place.neighborhood} yet "
            f"({dropped} other listing(s) collected but none usable)."
        ]

    has_adjacent = any(
        result.neighborhood_relations.get(comp.get("neighborhood")) == "adjacent"
        for comp in comp_set.comps)
    where = (f"{result.place.neighborhood} and nearby" if has_adjacent
             else result.place.neighborhood)

    lines = [f"{comp_set.count} comparable {result.place.unit_type} listing(s) in {where}"]
    if comp_set.thin:
        lines.append(THIN_NOTE)

    total = comp_set.median * result.nights
    lines.append(
        f"median ${comp_set.median:.0f}/night · range "
        f"${comp_set.low:.0f}–${comp_set.high:.0f} · "
        f"{result.nights} nights → ${total:,.0f} total")
    lines.append("")

    for comp in comp_set.comps:
        relation = result.neighborhood_relations.get(comp.get("neighborhood"))
        tag = " (adjacent)" if relation == "adjacent" else ""
        bedrooms = comp.get("bedrooms")
        br = f"{bedrooms}BR" if bedrooms is not None else "?BR"
        furnished = "furnished" if comp.get("furnished") else ""
        detail = ", ".join(part for part in (br, furnished) if part)
        span = f"{comp.get('start_date') or '?'} – {comp.get('end_date') or '?'}"
        lines.append(
            f"  ${comp['nightly_price']:.0f}/night  {detail:<24} {span:<24} "
            f"{comp.get('neighborhood') or ''}{tag}")

    if comp_set.dropped:
        lines.append("")
        lines.append(f"({comp_set.dropped} other listing(s) collected but not usable as comps.)")

    return lines

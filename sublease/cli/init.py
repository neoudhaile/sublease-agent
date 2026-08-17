"""Turn onboarding answers into a Profile.

`build_profile` is pure so it can be tested without a terminal, and so the M2
web wizard can reuse it unchanged.

The default copy is written in sentences with no leading "- " lines, because
Facebook's composer rewrites those into double bullets, and contains none of the
ASCII sequences the composer converts to emoji.
"""
from __future__ import annotations

from datetime import date

from sublease.errors import ConfigError
from sublease.pricing.service import PricingResult
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)

DEFAULT_TEMPLATES = {
    "outreach_message": (
        "Hi {first_name}! I saw your post in {group} looking for a place "
        "{their_dates}. I have a room available that overlaps your dates. "
        "Happy to send photos and details if you're still looking."
    ),
    "listing_post": (
        "Room available for sublet. Message me for photos and details, "
        "and I'm happy to answer any questions about the place or the "
        "neighborhood."
    ),
}


def parse_date(field: str, raw: object) -> date:
    """Parse a user-supplied date, raising a typed, plain-language error.

    Accepts a `date` object as-is so callers (the web wizard included) that
    already hold a real date never pay a round trip through string parsing.
    """
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f'{field}: "{raw}" is not a valid date. '
            f"Use YYYY-MM-DD, e.g. 2026-08-18."
        ) from exc


def suggested_nightly_price(result: PricingResult) -> float | None:
    """Pick a single nightly figure to offer the user during `init`, or None
    if the result has nothing usable to offer.

    Comps mode offers the median of the matched comps. Estimate mode offers
    the midpoint of the model's low/high range — it is still labelled an
    estimate everywhere it is shown; this function only picks the number,
    it does not decide how it is presented.
    """
    if result.mode == "comps":
        return result.comp_set.median if result.comp_set else None
    if result.estimate_low is not None and result.estimate_high is not None:
        return (result.estimate_low + result.estimate_high) / 2
    return None


def build_profile(answers: dict) -> Profile:
    return Profile(
        name=answers["name"],
        place=Place(
            neighborhood=answers["neighborhood"],
            unit_type=answers.get("unit_type", "room"),
            bedrooms=answers.get("bedrooms", 1),
            bath=answers.get("bath", "shared"),
            furnished=answers.get("furnished", True),
            amenities=answers.get("amenities", []),
        ),
        window=Window(
            start=parse_date("window_start", answers["window_start"]),
            end=parse_date("window_end", answers["window_end"]),
            flexible=answers.get("flexible", False),
            allow_split=answers.get("allow_split", True),
            max_split=answers.get("max_split", 3),
        ),
        price=Price(nightly=answers.get("nightly_price"),
                    total=answers.get("total_price")),
        constraints=Constraints(
            max_people_per_room=answers.get("max_people_per_room", 1),
            multi_room_seekers_ok=answers.get("multi_room_seekers_ok", True),
            gender_preference=answers.get("gender_preference"),
            pets_ok=answers.get("pets_ok", True),
        ),
        templates=Templates(
            outreach_message=answers.get("outreach_message",
                                         DEFAULT_TEMPLATES["outreach_message"]),
            listing_post=answers.get("listing_post",
                                     DEFAULT_TEMPLATES["listing_post"]),
        ),
        sources=[SourceConfig(**s) for s in answers.get("sources", [])],
    )

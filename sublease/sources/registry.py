"""Method name -> Source implementation."""
from __future__ import annotations

from sublease.errors import SourceError
from sublease.sources.base import Source

REGISTERED_METHODS = {"fixtures", "forage", "apify"}


def get_source(method: str, **kwargs) -> Source:
    if method == "fixtures":
        from sublease.sources.fixtures import FixtureSource
        return FixtureSource(kwargs["path"])
    if method == "forage":
        from sublease.sources.forage import ForageFacebookSource
        return ForageFacebookSource(**kwargs)
    if method == "apify":
        from sublease.sources.apify import ApifySource
        return ApifySource(**kwargs)
    raise SourceError(
        f"unknown source method {method!r}; expected one of {sorted(REGISTERED_METHODS)}")

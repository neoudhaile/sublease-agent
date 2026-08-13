"""Synthetic posts, so the whole pipeline is exercisable with no Facebook."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.base import RawPost
from sublease.sources.normalize import load_records, normalize


class FixtureSource:
    name = "fixtures"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        try:
            payload = json.loads(self.path.read_text())
        except OSError as exc:
            raise SourceError(f"cannot read fixtures at {self.path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SourceError(f"fixtures at {self.path} are not valid JSON: {exc}") from exc

        try:
            records = load_records(payload)[:limit]
            return [
                normalize(rec, rec.get("group") or cfg.name, self.name, slug=cfg.slug)
                for rec in records
            ]
        except (AttributeError, TypeError) as exc:
            raise SourceError(
                f"fixtures at {self.path} have invalid structure: {exc}"
            ) from exc

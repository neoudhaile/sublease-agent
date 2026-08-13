"""ForageFacebook CLI adapter — drives the user's own logged-in browser session.

Ported from reference/pipeline/scrape.py:91-117. `runner` is injectable so tests
never shell out.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from sublease.errors import SourceError
from sublease.paths import sublease_home
from sublease.profile.models import SourceConfig
from sublease.sources.base import RawPost
from sublease.sources.normalize import load_records, normalize

TIMEOUT_SECONDS = 3600


class ForageFacebookSource:
    name = "forage"

    def __init__(self, binary: str | None = None, raw_dir: Path | None = None,
                 delay: float = 3.0, runner=subprocess.run) -> None:
        # Prefer the forage installed alongside this interpreter, as the prototype did.
        self.binary = binary or str(Path(sys.executable).parent / "forage")
        self.raw_dir = Path(raw_dir) if raw_dir else sublease_home(create=True) / "raw"
        self.delay = delay
        self.runner = runner

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        outfile = self.raw_dir / f"{cfg.slug}.json"
        days = max((date.today() - since).days, 1)
        cmd = [
            self.binary, "scrape", str(cfg.slug),
            "--days", str(days),
            "--skip-comments", "--skip-reactions", "--no-input",
            "--delay", str(self.delay),
            "--limit", str(limit),
            "-f", "json", "-o", str(outfile),
        ]
        try:
            result = self.runner(cmd, capture_output=True, text=True,
                                 timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceError(f"could not run forage for {cfg.name}: {exc}") from exc

        if result.returncode != 0:
            raise SourceError(
                f"forage failed for {cfg.name}: {(result.stderr or '').strip()[:500]}")
        try:
            payload = json.loads(outfile.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceError(f"unreadable forage output for {cfg.name}: {exc}") from exc

        try:
            return [normalize(rec, cfg.name, self.name, slug=str(cfg.slug))
                    for rec in load_records(payload)]
        except (AttributeError, TypeError) as exc:
            raise SourceError(f"malformed forage output for {cfg.name}: {exc}") from exc

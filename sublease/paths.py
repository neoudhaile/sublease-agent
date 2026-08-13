"""Where this tool keeps its data.

A globally installed CLI must not write next to the current working directory,
so everything lives under SUBLEASE_HOME (default ~/.sublease).
"""
import os
from pathlib import Path

ENV_VAR = "SUBLEASE_HOME"
DEFAULT_DIR = ".sublease"


def sublease_home(create: bool = False) -> Path:
    raw = os.environ.get(ENV_VAR)
    home = Path(raw).expanduser() if raw else Path.home() / DEFAULT_DIR
    if create:
        home.mkdir(parents=True, exist_ok=True)
    return home


def db_path() -> Path:
    return sublease_home() / "sublease.db"

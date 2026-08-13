# tests/test_paths.py
from pathlib import Path
from sublease.paths import sublease_home, db_path


def test_home_defaults_to_dot_sublease(monkeypatch):
    monkeypatch.delenv("SUBLEASE_HOME", raising=False)
    assert sublease_home() == Path.home() / ".sublease"


def test_home_honors_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    assert sublease_home() == tmp_path


def test_db_path_sits_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    assert db_path() == tmp_path / "sublease.db"


def test_home_is_created_on_demand(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "home"
    monkeypatch.setenv("SUBLEASE_HOME", str(target))
    assert sublease_home(create=True).is_dir()

import os

import pytest

os.environ.setdefault("VALOR_AGENT_MODE", "mock")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file; the agent never calls Claude in tests."""
    from valor import config, store
    monkeypatch.setenv("VALOR_DB", str(tmp_path / "valor.db"))
    monkeypatch.setenv("VALOR_AGENT_MODE", "mock")
    config.settings.cache_clear()
    store._initialized.clear()
    s = config.settings()
    monkeypatch.setitem(s["storage"], "reports_dir", str(tmp_path / "reports"))
    monkeypatch.setitem(s["storage"], "agent_runs_dir", str(tmp_path / "agent_runs"))
    monkeypatch.setitem(s["agent"], "auto_explain", False)
    yield
    config.settings.cache_clear()

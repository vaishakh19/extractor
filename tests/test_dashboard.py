from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.dashboard import create_dashboard
from app.database.database import Database
from app.database.repositories import Repository


def test_dashboard_is_local_and_does_not_expose_secrets(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'dashboard.db'}")
    database.initialize()
    settings = Settings(
        _env_file=None,
        api_key="visible-key",
        api_secret="super-secret",
        database_url=f"sqlite:///{tmp_path / 'dashboard.db'}",
    )
    client = TestClient(create_dashboard(settings, Repository(database)))
    response = client.get("/")
    assert response.status_code == 200
    assert "Crypto trading control room" in response.text
    assert "visible-key" not in response.text
    assert "super-secret" not in response.text
    status = client.get("/api/status")
    assert status.status_code == 200
    assert "api_secret" not in status.text

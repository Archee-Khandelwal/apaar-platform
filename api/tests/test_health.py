"""Step 1: both services boot and report health."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from registry.app.main import app as registry_app


def test_api_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "api"
    assert body["db"] == "ok"
    assert body["synthetic_data"] is True


def test_registry_health() -> None:
    with TestClient(registry_app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "registry"

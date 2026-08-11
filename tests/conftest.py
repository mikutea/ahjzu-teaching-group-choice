from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.config import Config
from server.main import create_app


TEST_ADMIN_PASSWORD = "Local-Test-Only-Password!"


@pytest.fixture()
def app_config(tmp_path: Path) -> Config:
    return Config(
        environment="test",
        database_path=tmp_path / "test.db",
        app_secret="test-secret-that-is-long-enough-and-never-production",
        admin_username="admin",
        admin_initial_password=TEST_ADMIN_PASSWORD,
        cookie_secure=False,
        session_hours=12,
        public_base_url="http://127.0.0.1:8765",
        seed_demo_structure=True,
    )


@pytest.fixture()
def app(app_config: Config):
    return create_app(app_config)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def admin_login(client: TestClient) -> str:
    response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": admin_login(client)}


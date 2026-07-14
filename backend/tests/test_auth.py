from fastapi.testclient import TestClient

from passage.config import Settings, get_settings
from passage.main import create_app


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_token="correct-token",
        database_url="postgresql://postgres:postgres@127.0.0.1:54322/postgres",
        cron_secret="test-cron-secret",
    )
    return TestClient(app)


def test_me_without_token_is_unauthorized() -> None:
    with _client() as client:
        response = client.get("/api/me")

    assert response.status_code == 401


def test_me_with_wrong_token_is_unauthorized() -> None:
    with _client() as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401


def test_me_with_correct_token_is_authorized() -> None:
    with _client() as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer correct-token"})

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}


def test_health_remains_unauthenticated() -> None:
    with _client() as client:
        response = client.get("/health")

    assert response.status_code == 200

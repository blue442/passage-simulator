from fastapi.testclient import TestClient

from passage.config import Settings, get_settings
from passage.main import create_app

LOCAL_SUPABASE_DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_token="user-token",
        database_url=LOCAL_SUPABASE_DSN,
        cron_secret="correct-cron-secret",
    )
    return TestClient(app)


def test_keepalive_without_secret_is_unauthorized() -> None:
    with _client() as client:
        response = client.get("/api/cron/keepalive")

    assert response.status_code == 401


def test_keepalive_with_wrong_secret_is_unauthorized() -> None:
    with _client() as client:
        response = client.get("/api/cron/keepalive", headers={"Authorization": "Bearer wrong-secret"})

    assert response.status_code == 401


def test_keepalive_with_correct_secret_succeeds() -> None:
    with _client() as client:
        response = client.get(
            "/api/cron/keepalive", headers={"Authorization": "Bearer correct-cron-secret"}
        )

    assert response.status_code == 200
    assert response.json() == {"database": "ok"}


def test_user_token_does_not_authorize_keepalive() -> None:
    with _client() as client:
        response = client.get("/api/cron/keepalive", headers={"Authorization": "Bearer user-token"})

    assert response.status_code == 401


def test_cron_secret_does_not_authorize_me() -> None:
    with _client() as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer correct-cron-secret"})

    assert response.status_code == 401

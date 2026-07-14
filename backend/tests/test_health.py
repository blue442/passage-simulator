from fastapi.testclient import TestClient

from passage import __version__
from passage.config import Settings, get_settings
from passage.main import create_app


def test_health_returns_status_and_version() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(auth_token="test-token")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}

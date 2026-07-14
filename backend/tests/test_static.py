from pathlib import Path

from fastapi.testclient import TestClient

from passage.config import Settings, get_settings
from passage.main import create_app


def _client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_root_and_unknown_route_serve_index_html(tmp_path: Path) -> None:
    index_file = tmp_path / "index.html"
    index_file.write_text("<html><body>Passage Simulator</body></html>")
    settings = Settings(auth_token="test-token", static_dir=tmp_path)

    with _client(settings) as client:
        root_response = client.get("/")
        route_response = client.get("/some/route")

    assert root_response.status_code == 200
    assert root_response.text == index_file.read_text()
    assert route_response.status_code == 200
    assert route_response.text == index_file.read_text()


def test_existing_static_file_is_served_directly(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "app.js").write_text("console.log('hi')")
    settings = Settings(auth_token="test-token", static_dir=tmp_path)

    with _client(settings) as client:
        response = client.get("/app.js")

    assert response.status_code == 200
    assert response.text == "console.log('hi')"


def test_api_route_still_routes_to_api_when_static_dir_set(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    settings = Settings(auth_token="test-token", static_dir=tmp_path)

    with _client(settings) as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}


def test_static_dir_none_returns_404_for_unknown_route() -> None:
    settings = Settings(auth_token="test-token", static_dir=None)

    with _client(settings) as client:
        response = client.get("/some/route")

    assert response.status_code == 404

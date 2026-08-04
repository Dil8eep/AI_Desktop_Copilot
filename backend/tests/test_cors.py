"""CORS regressions for the local browser applications."""

from fastapi.testclient import TestClient

from app.main import create_application
from app.settings import Settings


def test_admin_login_preflight_allows_browser_cache_headers() -> None:
    application = create_application(
        Settings(local_auth_token="test-token", llm_provider="mock")
    )

    with TestClient(application) as client:
        response = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": ("content-type,cache-control,pragma"),
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ("http://127.0.0.1:5174")

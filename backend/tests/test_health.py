from fastapi.testclient import TestClient

from app.main import create_application
from app.settings import Settings


def test_health_reports_mock_mode() -> None:
    application = create_application(
        Settings(local_auth_token="test-token", llm_provider="mock")
    )

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "mock"}
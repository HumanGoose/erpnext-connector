from fastapi.testclient import TestClient

from connector.main import app


def test_health_returns_ok_and_initializes_db() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

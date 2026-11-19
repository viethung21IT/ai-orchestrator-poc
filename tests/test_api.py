from fastapi.testclient import TestClient

from app.main import app


def test_root_returns_running_message():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "AI Orchestrator is running"}


def test_health_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

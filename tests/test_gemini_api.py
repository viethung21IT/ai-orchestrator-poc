import json

import httpx2
import pytest
from fastapi.testclient import TestClient
from google import genai
from pydantic import SecretStr
from starlette.datastructures import State

from app.core.config import Settings
from app.main import app
from app.services.intent_criteria import INTENT_PROMPTS

QUESTION = "Tính tổng doanh thu giả lập tháng 6."
PROBABILITIES = {
    "kpi": 0.9,
    "rag": 0.02,
    "graph": 0.02,
    "hybrid_graph_rag": 0.02,
    "hybrid_kpi_rag": 0.02,
    "other": 0.02,
}


@pytest.fixture
def api(monkeypatch):
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("mock-key"),
        gemini_model="gemini-3.5-flash-lite",
        gemini_decision_model="gemini-decision-1",
    )
    monkeypatch.setattr(app, "state", State({"settings": settings}))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_google(monkeypatch):
    real_client = genai.Client
    requests = []

    def respond(status, body):
        def handle(request):
            requests.append(request)
            if callable(body):
                return body(request)
            if isinstance(body, Exception):
                raise body
            return httpx2.Response(status, json=body)

        def make_client(**kwargs):
            kwargs["http_options"].httpx_client = httpx2.Client(
                transport=httpx2.MockTransport(handle),
            )
            return real_client(**kwargs)

        monkeypatch.setattr(genai, "Client", make_client)
        return requests

    return respond


def test_chat_generates_text(api, mock_google):
    calls = mock_google(200, {
        "candidates": [{"content": {"parts": [{"text": "Ví dụ giả lập."}]}}],
    })
    response = api.post("/api/v1/chat", json={"question": QUESTION})

    assert response.status_code == 200
    assert response.json() == {"answer": "Ví dụ giả lập.", "model": "gemini-3.5-flash-lite"}
    request, = calls
    assert request.url.path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
    assert json.loads(request.content)["contents"][0]["parts"][0]["text"] == QUESTION


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_classify_returns_choice_and_probabilities(api, mock_google, version):
    app.state.settings.intent_criteria_version = version
    answer = {"choice": "kpi", "confidence": 0.9, "probabilities": PROBABILITIES}
    calls = mock_google(200, {"answers": {"intent": {"type": "choice", **answer}}})
    response = api.post("/api/v1/classify", json={"question": QUESTION})

    assert response.status_code == 200
    assert response.json() == answer
    request, = calls
    assert request.url.path == "/v1beta/decisions"
    body = json.loads(request.content)
    assert body["model"] == "gemini-decision-1"
    assert body["input"] == QUESTION
    assert body["questions"]["intent"]["type"] == "choice"
    instructions, criteria = INTENT_PROMPTS[version]
    assert body["questions"]["intent"] == {
        "type": "choice", "instructions": instructions, "criteria": criteria,
    }


@pytest.mark.parametrize("endpoint", ["chat", "classify"])
@pytest.mark.parametrize(("status", "body", "expected", "detail"), [
    (400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}, 503, "Gemini API key is invalid."),
    (403, {"error": {"message": "mock-key"}}, 503, "Gemini API key is invalid or lacks access."),
    (404, {"error": {"message": "mock-key"}}, 503, "The configured Gemini model is unavailable."),
    (429, {"error": {"message": "mock-key"}}, 429, "Gemini rate limit or quota exceeded."),
    (503, {"error": {"message": "mock-key"}}, 503, "Gemini is temporarily unavailable."),
    (200, httpx2.ReadTimeout("mock-key"), 504, "Gemini request timed out."),
    (200, httpx2.ConnectError("mock-key"), 503, "Could not connect to Gemini."),
    (200, {}, 502, "Gemini returned an empty or invalid response."),
])
def test_provider_failures_are_sanitized(api, mock_google, endpoint, status, body, expected, detail):
    calls = mock_google(status, body)
    response = api.post(f"/api/v1/{endpoint}", json={"question": QUESTION})

    assert response.status_code == expected
    assert response.json() == {"detail": detail}
    assert len(calls) == 1


def test_classify_rejects_incomplete_probabilities(api, mock_google):
    mock_google(200, {
        "answers": {"intent": {
            "type": "choice", "choice": "kpi", "confidence": 0.9, "probabilities": {"kpi": 0.9},
        }},
    })
    response = api.post("/api/v1/classify", json={"question": QUESTION})

    assert response.status_code == 502


@pytest.mark.parametrize("endpoint", ["chat", "classify"])
def test_requires_api_key_and_nonblank_question(api, mock_google, monkeypatch, endpoint):
    monkeypatch.setattr(app.state.settings, "gemini_api_key", None)
    calls = mock_google(500, {})
    path = f"/api/v1/{endpoint}"

    assert api.post(path, json={"question": QUESTION}).json() == {
        "detail": "Gemini API key is not configured.",
    }
    assert api.post(path, json={"question": "  "}).status_code == 422
    assert not calls



@pytest.mark.parametrize(("flash_status", "flash_text", "routing_status", "intent", "error_status"), [
    (200, '{"intent":"hybrid_graph_rag"}', "accepted", "hybrid_graph_rag", None),
    (200, '{"intent":"unsupported"}', "unconfirmed", None, 502),
    (200, '{"intent":"graph","confidence":0.99}', "unconfirmed", None, 502),
    (429, None, "unconfirmed", None, 429),
])
def test_route_uses_structured_flash_output(
    api, mock_google, flash_status, flash_text, routing_status, intent, error_status,
):
    app.state.settings.intent_criteria_version = "v1"
    app.state.settings.intent_confidence_threshold = 0.7
    app.state.settings.intent_fallback_enabled = True
    question = "Which fictional department owns this project, and what does its test plan require?"
    probabilities = {label: 0.5 if label == "graph" else 0.1 for label in PROBABILITIES}

    def handle(request):
        if request.url.path == "/v1beta/decisions":
            return httpx2.Response(200, json={"answers": {"intent": {
                "type": "choice", "choice": "graph", "confidence": 0.5, "probabilities": probabilities,
            }}})
        if flash_status == 429:
            return httpx2.Response(429, json={"error": {"message": "mock-key"}})
        return httpx2.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": flash_text}]}}],
        })

    calls = mock_google(200, handle)
    response = api.post("/api/v1/route", json={"question": question})

    assert response.status_code == 200
    data = response.json()
    assert data["initial_intent"] == "graph"
    assert data["initial_confidence"] == 0.5
    assert data["probabilities"] == probabilities
    assert data["final_intent"] == intent
    assert data["routing_status"] == routing_status
    assert data["fallback_used"]
    assert data["fallback_error_status"] == error_status
    assert data["decision_model"] == "gemini-decision-1"
    assert data["fallback_model"] == "gemini-3.5-flash-lite"
    assert data["latency_ms"] >= 0
    decision, flash = calls
    assert json.loads(decision.content)["questions"]["intent"]["criteria"] == INTENT_PROMPTS["v2"][1]
    body = json.loads(flash.content)
    assert flash.url.path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
    assert body["contents"][0]["parts"][0]["text"] == question
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    schema = body["generationConfig"]["responseJsonSchema"]
    assert set(schema["properties"]["intent"]["enum"]) == set(PROBABILITIES)
    assert set(schema["properties"]) == {"intent"}

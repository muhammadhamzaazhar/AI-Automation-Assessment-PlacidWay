import pytest
from fastapi.testclient import TestClient

from app.api import AppServices, create_app
from app.chat.schemas import GroundedAnswer, QueryAnalysis
from app.chat.service import ChatService
from app.config import Settings
from app.storage import Storage
from tests.conftest import FakeKB, FakeLLM, make_chunk

CHUNK = make_chunk("price-list", "Out-Patient Program | $18,995")


def queued_llm(n):
    results = []
    for _ in range(n):
        results.append(QueryAnalysis(intent="question", standalone_question="Price?", language="en",
                                     needs_medical_disclaimer=False))
        results.append(GroundedAnswer(answerable=True, answer="From $18,995.",
                                      cited_chunk_ids=["price-list#1"]))
    return FakeLLM(*results)


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_token="secret",
                        rate_limit_per_minute=3, openai_api_key=None)
    storage = Storage(tmp_path / "app.db")
    services = AppServices(chat=ChatService(queued_llm(5), FakeKB([CHUNK]), storage), storage=storage)
    with TestClient(create_app(settings, services)) as test_client:
        yield test_client


def test_ui_and_health(client):
    assert "PlacidWay Assistant" in client.get("/").text
    assert client.get("/api/health").json()["chunks"] == 1


def test_chat_returns_answer_sources_and_quote_url(client):
    data = client.post("/api/chat", json={"message": "How much?"}).json()
    assert data["answer"] == "From $18,995."
    assert data["sources"][0]["url"] == CHUNK.url
    assert data["quote_url"].startswith("https://")


def test_blank_or_oversized_messages_are_rejected(client):
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 1001}).status_code == 422


def test_rate_limit(client):
    codes = [client.post("/api/chat", json={"message": "How much?"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_admin_requires_token(client):
    assert client.get("/admin/unanswered").status_code == 401
    assert client.get("/admin/unanswered", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.get("/admin/unanswered", headers={"X-Admin-Token": "secret"}).status_code == 200


def test_lead_capture_requires_consent_and_is_stored(client):
    lead = {"name": "Ana", "email": "ana@example.com", "consent": False}
    assert client.post("/api/leads", json=lead).status_code == 422
    assert client.post("/api/leads", json={**lead, "consent": True}).status_code == 201
    leads = client.get("/admin/leads", headers={"X-Admin-Token": "secret"}).json()
    assert leads[0]["email"] == "ana@example.com"

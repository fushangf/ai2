from backend.app import main
from backend.app.schemas import VoiceChatTurn


def _auth_headers(client, username="speaker_v2", password="Speaker1234!", email="speaker_v2@example.com"):
    client.post("/api/register", json={"username": username, "email": email, "password": password})
    response = client.post("/api/login", json={"username": username, "password": password})
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_voice_chat_v2_endpoint_uses_service_and_returns_history(client, monkeypatch):
    headers = _auth_headers(client)

    async def fake_chat(payload):
        return main.VoiceChatResponse(
            ok=True,
            model="voice-chat-test-model",
            latency_ms=12,
            answer="当然可以，我会先帮你梳理这幅画的亮点。",
            spoken_feedback="当然可以，我会先帮你梳理这幅画的亮点。",
            intent="drawing_help",
            suggested_action="none",
            history=[
                VoiceChatTurn(role="user", content=payload.text),
                VoiceChatTurn(role="assistant", content="当然可以，我会先帮你梳理这幅画的亮点。"),
            ],
        )

    monkeypatch.setattr(main.voice_chat_v2, "chat", fake_chat)
    response = client.post(
        "/api/voice-chat-v2",
        headers={**headers, "Content-Type": "application/json"},
        json={"text": "请帮我总结这幅画的亮点", "history": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "v2"
    assert body["mode"] == "voice_chat_v2"
    assert body["answer"].startswith("当然可以")
    assert len(body["history"]) == 2


def test_health_reports_voice_chat_v2_model(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["voice_chat_v2_model"] == main.settings.resolved_voice_chat_model_v2

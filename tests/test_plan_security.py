from unittest.mock import AsyncMock, patch


def register_and_login(client):
    client.post("/api/register", json={"username": "alice", "email": "alice@example.com", "password": "Password123!"})
    response = client.post("/api/login", json={"username": "alice", "password": "Password123!"})
    return response.json()["token"]


def test_plan_requires_login(client):
    response = client.post("/api/plan", json={"text": "画一个圆"})
    assert response.status_code == 401


def test_plan_increments_usage_count(client):
    token = register_and_login(client)
    fake_plan = {
        "title": "测试",
        "plan_summary": "生成一个圆",
        "spoken_feedback": "完成",
        "operations": [
            {"op": "create", "shape": {"type": "circle", "id": "c1", "group_id": "g1", "label": "圆", "tags": [], "fill": "#fff", "stroke": "#000", "stroke_width": 1, "opacity": 1, "z_index": 0, "rotation": 0, "cx": 50, "cy": 50, "r": 20}}
        ],
    }

    async def fake_plan_method(request):
        from backend.app.schemas import DrawingPlan
        return DrawingPlan.model_validate(fake_plan), 123

    with patch("backend.app.main.planner.plan", new=AsyncMock(side_effect=fake_plan_method)):
        response = client.post(
            "/api/plan",
            json={"text": "画一个圆"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["latency_ms"] == 123

    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["usage_count"] == 1

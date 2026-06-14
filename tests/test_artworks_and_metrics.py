from unittest.mock import AsyncMock, patch


def register(client, username="artist", email="artist@example.com"):
    response = client.post(
        "/api/register",
        json={"username": username, "email": email, "password": "Password123!"},
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_save_and_restore_artwork(client):
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    scene = {
        "background": {"mode": "solid", "color1": "#ffffff"},
        "objects": [
            {
                "type": "circle",
                "id": "sun",
                "group_id": "sky",
                "label": "太阳",
                "tags": ["天空"],
                "fill": "gold",
                "stroke": "orange",
                "stroke_width": 2,
                "opacity": 1,
                "z_index": 1,
                "rotation": 0,
                "cx": 100,
                "cy": 100,
                "r": 50,
            }
        ],
    }
    saved = client.post("/api/artworks", json={"title": "测试作品", "scene": scene}, headers=headers)
    assert saved.status_code == 200
    assert saved.json()["object_count"] == 1

    latest = client.get("/api/artworks/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["scene"]["objects"][0]["id"] == "sun"


def test_local_route_updates_admin_metrics(client):
    token = register(client, "localartist", "local@example.com")
    request = {
        "text": "把太阳向右移动80像素",
        "canvas": {"width": 1000, "height": 700},
        "scene": {
            "background": {},
            "objects": [
                {"id": "sun", "group_id": "sun", "label": "太阳", "type": "circle", "bbox": [0, 0, 100, 100], "fill": "gold", "stroke": "orange", "tags": ["太阳"]}
            ],
        },
    }
    result = client.post("/api/plan", json=request, headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == 200
    assert result.json()["source"] == "local"
    assert result.json()["latency_ms"] >= 1

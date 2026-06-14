from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.bootstrap import ensure_admin_user


def register_user(client, username="alice", email="alice@example.com", password="Password123!"):
    response = client.post("/api/register", json={"username": username, "email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def login_user(client, username="alice", password="Password123!"):
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()


def test_register_and_me(client):
    auth = register_user(client)
    response = client.get("/api/me", headers={"Authorization": f"Bearer {auth['token']}"})
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "alice"
    assert data["role"] == "user"


def test_admin_can_ban_user(client):
    register_user(client)

    with SessionLocal() as db:
        ensure_admin_user(db)

    admin = client.post("/api/login", json={"username": "admin", "password": "Admin123456!"})
    assert admin.status_code == 200
    admin_token = admin.json()["token"]

    users = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert users.status_code == 200
    user_id = next(item["id"] for item in users.json()["users"] if item["username"] == "alice")

    ban = client.post(
        f"/api/admin/users/{user_id}/ban",
        json={"banned": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ban.status_code == 200
    assert ban.json()["is_banned"] is True

    blocked_login = client.post("/api/login", json={"username": "alice", "password": "Password123!"})
    assert blocked_login.status_code == 403

from backend.app.bootstrap import ensure_admin_user
from backend.app.database import SessionLocal


def test_product_pages_are_separated(client):
    assert client.get("/").status_code == 200
    assert "纯语音智能绘图平台" in client.get("/").text
    assert client.get("/login").status_code == 200
    assert "用户登录" in client.get("/login").text
    assert "管理员登录" in client.get("/login").text
    assert client.get("/register").status_code == 200
    assert "注册普通用户" in client.get("/register").text
    assert client.get("/workspace").status_code == 200
    assert client.get("/admin/login").status_code == 200
    assert client.get("/admin/dashboard").status_code == 200


def test_role_specific_login_endpoints(client):
    registered = client.post("/api/register", json={"username": "normaluser", "email": "normal@example.com", "password": "Password123!"})
    assert registered.status_code == 200
    assert registered.json()["redirect_to"] == "/workspace"

    user_login = client.post("/api/login/user", json={"username": "normal@example.com", "password": "Password123!"})
    assert user_login.status_code == 200
    assert user_login.json()["user"]["role"] == "user"

    wrong_portal = client.post("/api/login/admin", json={"username": "normaluser", "password": "Password123!"})
    assert wrong_portal.status_code == 403

    with SessionLocal() as db:
        ensure_admin_user(db)
    admin_login = client.post("/api/login/admin", json={"username": "admin", "password": "Admin123456!"})
    assert admin_login.status_code == 200
    assert admin_login.json()["redirect_to"] == "/admin/dashboard"

    admin_wrong_portal = client.post("/api/login/user", json={"username": "admin", "password": "Admin123456!"})
    assert admin_wrong_portal.status_code == 403

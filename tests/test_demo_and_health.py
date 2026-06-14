from backend.app import main


def test_health_does_not_expose_database_credentials(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert "database_url" not in body
    assert body["database_backend"] == "sqlite"
    assert body["auto_finish_policy"].startswith("adaptive voice activity")


def test_demo_login_is_local_and_flag_controlled(client):
    previous = main.settings.competition_kiosk_mode
    try:
        main.settings.competition_kiosk_mode = True
        response = client.post("/api/demo-login")
        assert response.status_code == 200
        assert response.json()["user"]["username"] == main.settings.competition_demo_username
    finally:
        main.settings.competition_kiosk_mode = previous


def test_preflight_reports_competition_dependencies(client):
    response = client.get("/api/preflight")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == main.settings.app_version
    assert body["checks"]["backend"]["ok"] is True
    assert body["checks"]["database"]["ok"] is True
    assert "cache" in body["checks"]

from pathlib import Path

from backend.app.settings import Settings


def test_mysql_url_is_built_from_individual_settings_and_encoded():
    settings = Settings(
        database_url="",
        mysql_host="mysql",
        mysql_port=3306,
        mysql_database="ai voice/draw",
        mysql_user="voice@draw",
        mysql_password="p:a/ss word",
        _env_file=None,
    )
    assert settings.resolved_database_url == (
        "mysql+pymysql://voice%40draw:p%3Aa%2Fss+word"
        "@mysql:3306/ai+voice%2Fdraw?charset=utf8mb4"
    )


def test_compose_uses_named_volume_and_single_mysql_credential_source():
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "mysql_data:/var/lib/mysql" in compose
    assert "./data/mysql:/var/lib/mysql" not in compose
    assert 'DATABASE_URL: ""' in compose
    assert "MYSQL_HOST: mysql" in compose
    assert 'MYSQL_PORT: "3306"' in compose
    assert '${MYSQL_HOST_PORT:-3307}:3306' in compose

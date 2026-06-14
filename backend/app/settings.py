from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Voice Draw Competition Edition"
    app_version: str = "4.3.1"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    debug: bool = False

    ai_provider: str = "qiniu"
    ai_api_key: str = ""
    ai_model: str = "qiniu/moonshotai/kimi-k2.5"
    ai_base_url: str = "https://api.qnaigc.com/v1"
    ai_timeout_seconds: float = 45.0
    ai_max_retries: int = 1
    ai_repair_retries: int = 1
    max_scene_objects_sent: int = 160
    max_operations: int = 220

    database_url: str = "sqlite:///./data/app.db"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "ai_voice_draw"
    mysql_user: str = ""
    mysql_password: str = ""

    auth_secret_key: str = "change-me-in-production"
    auth_token_expire_hours: int = 24
    password_hash_iterations: int = 120_000

    init_admin_username: str = "admin"
    init_admin_password: str = ""
    init_admin_email: str = "admin@example.com"

    competition_kiosk_mode: bool = False
    competition_demo_username: str = "demo_judge"
    competition_demo_password: str = ""
    competition_demo_email: str = "demo-judge@example.com"
    competition_demo_localhost_only: bool = True

    plan_rate_limit_per_minute: int = 30
    local_edit_router_enabled: bool = True
    plan_cache_enabled: bool = True
    plan_cache_ttl_seconds: int = 900
    plan_cache_max_entries: int = 128
    ai_connect_timeout_seconds: float = 8.0
    ai_pool_max_connections: int = 20
    voice_chat_model_v2: str = ""
    voice_chat_temperature: float = 0.35
    voice_chat_history_turns: int = 6
    cors_allow_origins: str = "*"

    @field_validator("database_url")
    @classmethod
    def resolve_database_url(cls, value: str) -> str:
        if value and value.strip():
            return value.strip()
        return ""

    @property
    def provider_label(self) -> str:
        return "七牛云 AI 推理服务"

    @property
    def resolved_base_url(self) -> str:
        return (self.ai_base_url or "https://api.qnaigc.com/v1").rstrip("/")

    @property
    def resolved_model(self) -> str:
        return self.ai_model or "qiniu/moonshotai/kimi-k2.5"

    @property
    def endpoint_url(self) -> str:
        return f"{self.resolved_base_url}/chat/completions"

    @property
    def resolved_voice_chat_model_v2(self) -> str:
        return self.voice_chat_model_v2 or self.resolved_model

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        database = quote_plus(self.mysql_database)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{database}?charset=utf8mb4"
        )

    @property
    def sqlite_mode(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def data_dir(self) -> Path:
        return Path("data")


@lru_cache
def get_settings() -> Settings:
    return Settings()

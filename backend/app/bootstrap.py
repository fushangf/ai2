from __future__ import annotations

import secrets

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .database import Base, engine
from .models import User
from .security import hash_password
from .settings import get_settings


def _migrate_legacy_schema() -> None:
    """为早期比赛版本做轻量兼容迁移，避免已有 SQLite/MySQL 数据库启动失败。"""
    inspector = inspect(engine)
    if "usage_logs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("usage_logs")}
    statements: list[str] = []
    if "source" not in existing:
        statements.append("ALTER TABLE usage_logs ADD COLUMN source VARCHAR(20) DEFAULT 'ai'")
    if "operation_count" not in existing:
        statements.append("ALTER TABLE usage_logs ADD COLUMN operation_count INTEGER DEFAULT 0")
    if "error_message" not in existing:
        statements.append("ALTER TABLE usage_logs ADD COLUMN error_message VARCHAR(500) DEFAULT ''")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(text("UPDATE usage_logs SET source='ai' WHERE source IS NULL"))
        connection.execute(text("UPDATE usage_logs SET operation_count=0 WHERE operation_count IS NULL"))
        connection.execute(text("UPDATE usage_logs SET error_message='' WHERE error_message IS NULL"))


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_legacy_schema()


def _ensure_user(
    db: Session,
    *,
    username: str,
    email: str,
    password: str,
    role: str,
) -> User:
    settings = get_settings()
    user = db.scalar(select(User).where(User.username == username))
    if user:
        return user
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password, settings.password_hash_iterations),
        role=role,
        is_active=True,
        is_banned=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_admin_user(db: Session) -> None:
    settings = get_settings()
    if not settings.init_admin_password:
        return
    _ensure_user(
        db,
        username=settings.init_admin_username,
        email=settings.init_admin_email,
        password=settings.init_admin_password,
        role="admin",
    )


def ensure_competition_demo_user(db: Session) -> User | None:
    settings = get_settings()
    if not settings.competition_kiosk_mode:
        return None
    return _ensure_user(
        db,
        username=settings.competition_demo_username,
        email=settings.competition_demo_email,
        password=settings.competition_demo_password or secrets.token_urlsafe(24),
        role="user",
    )

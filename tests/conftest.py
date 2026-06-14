import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DB = Path("data/test_app.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.resolve()}"
os.environ["AUTH_SECRET_KEY"] = "test-secret-key"
os.environ["INIT_ADMIN_PASSWORD"] = "Admin123456!"
os.environ["AI_API_KEY"] = "fake-key"

from backend.app.main import app, plan_limiter  # noqa: E402
from backend.app.bootstrap import init_database  # noqa: E402
from backend.app.database import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    plan_limiter.reset()
    Base.metadata.drop_all(bind=engine)
    init_database()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client

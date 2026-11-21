from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import SessionLocal, init_engine
from app.main import create_app
from app.services import tours as tour_service
from app.services.seed import init_db

TODAY = date(2026, 11, 21)
TEST_BOT_USERNAME = "test_demo_bot"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        bot_token="",
        bot_username=TEST_BOT_USERNAME,
        admin_chat_id=None,
        site_base_url="http://testserver",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
    )


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(tour_service, "current_date", lambda: TODAY)
    return TODAY


@pytest.fixture
def db(settings):
    engine = init_engine(settings.database_url)
    init_db(engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client

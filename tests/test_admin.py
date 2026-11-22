"""Админ-панель и демо-группа: вход, заявки, туры, подключение группы, вступление в группу."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.bot import handlers
from app.database import session_scope
from app.main import create_app
from app.models import Application, Tour
from app.routers import admin
from app.services import app_settings, publisher

PASSWORD = "test-admin-password"
GROUP_ID = -1001234567890


class FakeBot:
    """Записывает вызовы Bot API вместо обращения к Telegram."""

    def __init__(self):
        self.calls = []

    async def create_chat_invite_link(self, chat_id, **kwargs):
        self.calls.append(("invite", chat_id, kwargs))
        return SimpleNamespace(invite_link="https://t.me/+testInvite")

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("message", chat_id, text))
        return SimpleNamespace(message_id=101)

    async def send_photo(self, chat_id, photo, **kwargs):
        self.calls.append(("photo", chat_id, kwargs.get("caption")))
        return SimpleNamespace(message_id=102)

    async def create_forum_topic(self, chat_id, name):
        self.calls.append(("topic", chat_id, name))
        return SimpleNamespace(message_thread_id=77)

    def kinds(self):
        return [call[0] for call in self.calls]


@pytest.fixture
def admin_settings(settings):
    return replace(settings, admin_password=PASSWORD, app_secret="secret")


@pytest.fixture
def fake_bot():
    return FakeBot()


@pytest.fixture
def admin_client(admin_settings, fake_bot, monkeypatch):
    monkeypatch.setattr(publisher, "publish_in_background", lambda settings: False)
    app = create_app(admin_settings)

    async def bot_override():
        yield fake_bot

    app.dependency_overrides[admin.get_bot] = bot_override
    with TestClient(app) as client:
        yield client


def login(client):
    return client.post("/admin/login", data={"password": PASSWORD}, follow_redirects=False)


def connect_group(is_forum=True):
    with session_scope() as session:
        app_settings.remember_pending_group(session, GROUP_ID, "Naomi Tours — демо", is_forum)
        app_settings.connect_pending_group(session)


def add_application(tour_code="georgia_2027_03", user_id=555, status="new"):
    with session_scope() as session:
        tour = session.scalar(select(Tour).where(Tour.tour_code == tour_code))
        app = Application(tour_id=tour.id, name="Анна", comment="Нас двое", telegram_user_id=user_id,
                          telegram_username="anna", status=status)
        session.add(app)
        session.flush()
        return app.id


# ---------- вход ----------

def test_admin_requires_login(admin_client):
    response = admin_client.get("/admin/applications", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_wrong_password_rejected(admin_client):
    response = admin_client.post("/admin/login", data={"password": "nope"})
    assert response.status_code == 401
    assert "Неверный пароль" in response.text


def test_login_and_logout(admin_client):
    assert login(admin_client).status_code == 303
    assert admin_client.get("/admin/applications").status_code == 200
    admin_client.post("/admin/logout")
    assert admin_client.get("/admin/applications", follow_redirects=False).status_code == 303


def test_login_rate_limited(admin_client):
    admin._failures.clear()
    for _ in range(admin.LOGIN_MAX_FAILURES):
        admin_client.post("/admin/login", data={"password": "nope"})
    assert admin_client.post("/admin/login", data={"password": PASSWORD}).status_code == 429
    admin._failures.clear()


def test_admin_disabled_without_password(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/admin/login").status_code == 503


def test_forged_cookie_rejected(admin_client):
    admin_client.cookies.set(admin.COOKIE, "9999999999.forged", path="/admin")
    assert admin_client.get("/admin/applications", follow_redirects=False).status_code == 303


# ---------- группа ----------

def test_group_connect_flow(admin_client, fake_bot):
    login(admin_client)
    assert "Группа не подключена" in admin_client.get("/admin/applications").text
    with session_scope() as session:
        app_settings.remember_pending_group(session, GROUP_ID, "Naomi Tours — демо", True)
    assert "Подключить" in admin_client.get("/admin/applications").text
    page = admin_client.post("/admin/group/connect")
    assert "Группа подключена" in page.text
    # У каждого актуального тура появилась тема.
    assert fake_bot.kinds().count("topic") >= 4
    with session_scope() as session:
        assert session.scalar(select(Tour).where(Tour.tour_code == "georgia_2027_03")).forum_topic_id == 77


def test_group_without_topics_not_connected(admin_client):
    login(admin_client)
    with session_scope() as session:
        app_settings.remember_pending_group(session, GROUP_ID, "Без тем", False)
    page = admin_client.post("/admin/group/connect")
    assert "не включены «Темы»" in page.text
    with session_scope() as session:
        assert app_settings.connected_group(session) is None


# ---------- заявки ----------

def test_approve_sends_join_request_invite(admin_client, fake_bot):
    login(admin_client)
    connect_group()
    app_id = add_application()
    page = admin_client.post(f"/admin/applications/{app_id}/approve")
    assert "приглашение отправлено" in page.text
    invite = next(call for call in fake_bot.calls if call[0] == "invite")
    assert invite[1] == GROUP_ID and invite[2]["creates_join_request"] is True
    message = next(call for call in fake_bot.calls if call[0] == "message")
    assert message[1] == 555 and "одобрена" in message[2]
    with session_scope() as session:
        stored = session.get(Application, app_id)
        assert stored.status == "approved" and stored.invite_link == "https://t.me/+testInvite"


def test_approve_without_group_asks_to_connect(admin_client, fake_bot):
    login(admin_client)
    app_id = add_application()
    page = admin_client.post(f"/admin/applications/{app_id}/approve")
    assert "подключите группу" in page.text
    assert fake_bot.calls == []
    with session_scope() as session:
        assert session.get(Application, app_id).status == "new"


def test_reject(admin_client, fake_bot):
    login(admin_client)
    app_id = add_application()
    page = admin_client.post(f"/admin/applications/{app_id}/reject")
    assert "Заявка отклонена" in page.text
    with session_scope() as session:
        assert session.get(Application, app_id).status == "rejected"


# ---------- туры ----------

TOUR_FORM = {
    "title": "Рождественский Страсбург", "destination": "Франция", "start_date": "2027-12-18",
    "end_date": "2027-12-19", "transport": "Автобус", "price_label": "199 €", "duration": "2 дня",
    "summary": "Ярмарка и старый город.", "program": "День 1: Выезд и ярмарка\nДень 2: Старый город",
    "included": "Проезд\nОтель", "extras": "Ужин", "listed": "on",
}


def test_add_tour_creates_topic_and_announcement(admin_client, fake_bot):
    login(admin_client)
    connect_group()
    fake_bot.calls.clear()
    page = admin_client.post("/admin/tours/new", data=TOUR_FORM)
    assert "Тур сохранён" in page.text
    with session_scope() as session:
        tour = session.scalar(select(Tour).where(Tour.title == "Рождественский Страсбург"))
        assert tour.tour_code == "frantsiya_2027_12" and tour.source == "admin"
        assert tour.program[0] == {"title": "День 1", "text": "Выезд и ярмарка"}
        assert tour.forum_topic_id == 77 and tour.announcement_message_id == 101
    assert "topic" in fake_bot.kinds() and "message" in fake_bot.kinds()
    announcement = next(call for call in fake_bot.calls if call[0] == "message")
    assert announcement[1] == GROUP_ID and "Рождественский Страсбург" in announcement[2]
    # Тур сразу виден на сайте и доступен в боте по коду.
    assert "Рождественский Страсбург" in admin_client.get("/tours").text


def test_add_tour_validation(admin_client):
    login(admin_client)
    bad = {**TOUR_FORM, "end_date": "2027-12-01", "price_label": ""}
    page = admin_client.post("/admin/tours/new", data=bad)
    assert page.status_code == 400
    assert "Укажите цену" in page.text and "раньше даты начала" in page.text


def test_edit_tour_keeps_code_and_is_not_overwritten_by_seed(admin_client, admin_settings):
    login(admin_client)
    with session_scope() as session:
        tour = session.scalar(select(Tour).where(Tour.tour_code == "georgia_2027_03"))
        tour_id = tour.id
    form = {**TOUR_FORM, "title": "Грузия — новое название", "destination": "Грузия",
            "start_date": "2027-03-20", "end_date": "2027-03-27"}
    admin_client.post(f"/admin/tours/{tour_id}/edit", data=form)
    # Перезапуск приложения (повторная загрузка seed) не возвращает старое название.
    with TestClient(create_app(admin_settings)):
        pass
    with session_scope() as session:
        tour = session.get(Tour, tour_id)
        assert tour.title == "Грузия — новое название" and tour.tour_code == "georgia_2027_03"


def test_photo_upload(admin_client, tmp_path, monkeypatch):
    from PIL import Image
    from app.services import tour_admin
    monkeypatch.setattr(tour_admin, "UPLOADS_DIR", tmp_path)
    login(admin_client)
    image_path = tmp_path / "p.png"
    Image.new("RGB", (2400, 1200), "orange").save(image_path)
    with open(image_path, "rb") as fh:
        admin_client.post("/admin/tours/new", data=TOUR_FORM, files={"photo": ("p.png", fh, "image/png")})
    saved = Image.open(tmp_path / "frantsiya_2027_12.jpg")
    assert max(saved.size) == tour_admin.PHOTO_MAX_SIDE


# ---------- бот и группа ----------

def run(coro):
    return asyncio.run(coro)


def membership_event(status, is_forum=True):
    return SimpleNamespace(chat=SimpleNamespace(id=GROUP_ID, type="supergroup", title="Демо", is_forum=is_forum),
                           new_chat_member=SimpleNamespace(status=status))


def test_bot_added_to_group_becomes_pending(db):
    run(handlers.bot_membership_changed(membership_event("administrator")))
    with session_scope() as session:
        assert app_settings.pending_group(session).chat_id == GROUP_ID
        assert app_settings.connected_group(session) is None
    run(handlers.bot_membership_changed(membership_event("left")))
    with session_scope() as session:
        assert app_settings.pending_group(session) is None


def join_request_event(user_id):
    return SimpleNamespace(chat=SimpleNamespace(id=GROUP_ID), from_user=SimpleNamespace(id=user_id),
                           approve=AsyncMock(), decline=AsyncMock())


def test_join_request_only_for_approved(db):
    connect_group()
    add_application(user_id=555, status="approved")
    add_application(user_id=777, status="new")
    bot = SimpleNamespace(send_message=AsyncMock())

    approved = join_request_event(555)
    run(handlers.join_request(approved, bot))
    approved.approve.assert_awaited_once()
    bot.send_message.assert_awaited_once()

    stranger = join_request_event(777)
    run(handlers.join_request(stranger, bot))
    stranger.decline.assert_awaited_once()
    stranger.approve.assert_not_called()


def test_topic_link():
    from app.services.telegram_group import topic_link
    assert topic_link(GROUP_ID, 77) == "https://t.me/c/1234567890/77"
    assert topic_link(GROUP_ID, None) is None


# ---------- автопубликация сайта ----------

def test_publish_pushes_rebuilt_site(tmp_path, settings, db, monkeypatch):
    import subprocess

    def git(*args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    for key, value in [("user.name", "test"), ("user.email", "test@example.com")]:
        git("config", key, value, cwd=work)
    (work / "README.md").write_text("x", encoding="utf-8")
    git("add", "-A", cwd=work)
    git("commit", "-qm", "init", cwd=work)
    git("push", "-q", "origin", "HEAD:main", cwd=work)
    git("branch", "--set-upstream-to=origin/main", cwd=work)

    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("BOT_USERNAME", settings.bot_username)
    site_settings = replace(settings, site_repo_dir=str(work), site_pages_base_path="/naomi-tours-demo")
    assert publisher.publish_now(site_settings) == "published"
    log = subprocess.run(["git", "log", "--oneline", "origin/main"], cwd=work, capture_output=True, text=True, encoding="utf-8")
    assert "Обновление туров" in log.stdout
    assert (work / "docs" / "tours" / "georgia_2027_03" / "index.html").exists()
    assert publisher.publish_now(site_settings) == "nothing"
    assert publisher.last_status()[1] == "nothing"

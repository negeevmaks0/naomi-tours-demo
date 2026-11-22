"""Админ-панель: вход по паролю, заявки (одобрить/отклонить), туры (добавить/изменить), группа."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.config import Settings
from app.database import session_scope
from app.models import Application, Tour
from app.models.application import STATUS_APPROVED, STATUS_NEW, STATUS_REJECTED
from app.routers.pages import get_app_settings, templates
from app.services import app_settings, publisher, telegram_group, tour_admin
from app.services import tours as tour_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")

COOKIE = "naomi_admin"
SESSION_SECONDS = 12 * 3600
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
_failures: dict[str, deque] = defaultdict(deque)

# Короткие сообщения после действий (ключ передаётся в адресе, текст — только отсюда).
NOTICES = {
    "approved": ("ok", "Заявка одобрена — приглашение отправлено."),
    "rejected": ("ok", "Заявка отклонена."),
    "invite_failed": ("error", "Приглашение не отправлено. Причина — в карточке заявки."),
    "need_group": ("error", "Сначала подключите группу (вверху страницы)."),
    "group_connected": ("ok", "Группа подключена."),
    "group_not_forum": ("error", "В группе не включены «Темы». Включите их в настройках группы и добавьте бота заново."),
    "group_disconnected": ("ok", "Группа отключена."),
    "tour_saved": ("ok", "Тур сохранён. Сайт обновится примерно через минуту."),
    "tour_saved_local": ("ok", "Тур сохранён."),
    "tour_group_failed": ("error", "Тур сохранён, но в группу не опубликован: проверьте права бота в группе."),
}


# ---------- вход ----------

def _secret(settings: Settings) -> bytes:
    raw = settings.app_secret or f"{settings.admin_password}:{settings.bot_token}"
    return hashlib.sha256(raw.encode()).digest()


def _sign(settings: Settings, expires: int) -> str:
    return hmac.new(_secret(settings), f"admin:{expires}".encode(), hashlib.sha256).hexdigest()


def make_session_cookie(settings: Settings, now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_SECONDS)
    return f"{expires}.{_sign(settings, expires)}"


def is_logged_in(request: Request, settings: Settings) -> bool:
    raw = request.cookies.get(COOKIE, "")
    expires, _, signature = raw.partition(".")
    if not settings.admin_password or not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(signature, _sign(settings, int(expires)))


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def _too_many_failures(ip: str) -> bool:
    attempts = _failures[ip]
    while attempts and attempts[0] < time.time() - LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= LOGIN_MAX_FAILURES


def _url(settings: Settings, path: str) -> str:
    return f"{settings.base_path}/admin{path}"


def _redirect(settings: Settings, path: str, notice: str | None = None) -> RedirectResponse:
    target = _url(settings, path) + (f"?done={notice}" if notice else "")
    return RedirectResponse(target, status_code=303)


class LoginRequired(Exception):
    pass


def require_admin(request: Request, settings: Settings = Depends(get_app_settings)) -> Settings:
    if not is_logged_in(request, settings):
        raise LoginRequired()
    return settings


async def get_bot(settings: Settings = Depends(get_app_settings)) -> AsyncIterator[Bot]:
    bot = telegram_group.make_bot(settings)
    try:
        yield bot
    finally:
        await bot.session.close()


def _render(request: Request, name: str, context: dict, status_code: int = 200):
    notice = NOTICES.get(request.query_params.get("done", ""))
    return templates.TemplateResponse(request, f"admin/{name}", {"notice": notice, **context},
                                      status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, settings: Settings = Depends(get_app_settings)):
    if not settings.admin_password:
        return _render(request, "login.html", {"disabled": True}, status_code=503)
    return _render(request, "login.html", {})


@router.post("/login")
def login(request: Request, password: str = Form(""), settings: Settings = Depends(get_app_settings)):
    ip = _client_ip(request)
    if not settings.admin_password:
        return _render(request, "login.html", {"disabled": True}, status_code=503)
    if _too_many_failures(ip):
        return _render(request, "login.html", {"error": "Слишком много попыток. Подождите 15 минут."},
                       status_code=429)
    if not hmac.compare_digest(password.encode(), settings.admin_password.encode()):
        _failures[ip].append(time.time())
        return _render(request, "login.html", {"error": "Неверный пароль."}, status_code=401)
    _failures.pop(ip, None)
    response = _redirect(settings, "/applications")
    response.set_cookie(COOKIE, make_session_cookie(settings), max_age=SESSION_SECONDS, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https",
                        path=_url(settings, "") or "/")
    return response


@router.post("/logout")
def logout(settings: Settings = Depends(get_app_settings)):
    response = _redirect(settings, "/login")
    response.delete_cookie(COOKIE, path=_url(settings, "") or "/")
    return response


@router.get("")
@router.get("/")
def admin_home(settings: Settings = Depends(require_admin)):
    return _redirect(settings, "/applications")


# ---------- группа ----------

def _group_context() -> dict:
    with session_scope() as session:
        return {"group": app_settings.connected_group(session),
                "pending_group": app_settings.pending_group(session)}


@router.post("/group/connect")
async def connect_group(settings: Settings = Depends(require_admin), bot: Bot = Depends(get_bot)):
    with session_scope() as session:
        pending = app_settings.pending_group(session)
        if pending is not None and not pending.is_forum:
            return _redirect(settings, "/applications", "group_not_forum")
        group = app_settings.connect_pending_group(session)
    if group is not None:
        await _create_missing_topics(bot, group.chat_id)
    return _redirect(settings, "/applications", "group_connected")


@router.post("/group/disconnect")
def disconnect_group(settings: Settings = Depends(require_admin)):
    with session_scope() as session:
        group = app_settings.connected_group(session)
        if group is not None:
            app_settings.forget_group(session, group.chat_id)
    return _redirect(settings, "/applications", "group_disconnected")


async def _create_missing_topics(bot: Bot, chat_id: int) -> None:
    """После подключения группы у каждого актуального тура появляется своя тема."""
    today = tour_service.current_date()
    with session_scope() as session:
        tours = [t for t in session.scalars(select(Tour)) if t.is_public(today) and t.forum_topic_id is None]
    for tour in tours:
        try:
            topic_id = await telegram_group.create_tour_topic(bot, chat_id, tour)
        except TelegramAPIError as exc:
            logger.warning("Topic for %s not created: %s", tour.tour_code, exc.__class__.__name__)
            return
        with session_scope() as session:
            session.get(Tour, tour.id).forum_topic_id = topic_id


# ---------- заявки ----------

@router.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request, settings: Settings = Depends(require_admin)):
    with session_scope() as session:
        rows = session.execute(
            select(Application, Tour).join(Tour, Application.tour_id == Tour.id).order_by(Application.id.desc())
        ).all()
        new = [(a, t) for a, t in rows if a.status == STATUS_NEW]
        done = [(a, t) for a, t in rows if a.status != STATUS_NEW][:30]
    return _render(request, "applications.html",
                   {"new": new, "done": done, "active": "applications", **_group_context()})


@router.post("/applications/{application_id}/approve")
async def approve(application_id: int, settings: Settings = Depends(require_admin), bot: Bot = Depends(get_bot)):
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None or application.status != STATUS_NEW:
            return _redirect(settings, "/applications")
        tour = session.get(Tour, application.tour_id)
        group = app_settings.connected_group(session)
    if group is None:
        return _redirect(settings, "/applications", "need_group")
    error = None
    link = None
    try:
        link = await telegram_group.send_invite(bot, group.chat_id, application, tour)
    except telegram_group.InviteError as exc:
        error = str(exc)
    except TelegramAPIError as exc:
        logger.warning("Invite for application %s failed: %s", application_id, exc.__class__.__name__)
        error = "Telegram не создал приглашение: проверьте, что бот — администратор группы с правом приглашать."
    with session_scope() as session:
        stored = session.get(Application, application_id)
        if error:
            stored.invite_error = error
        else:
            stored.status, stored.invite_link, stored.invite_error = STATUS_APPROVED, link, None
            stored.decided_at = datetime.now(timezone.utc)
    return _redirect(settings, "/applications", "invite_failed" if error else "approved")


@router.post("/applications/{application_id}/reject")
async def reject(application_id: int, settings: Settings = Depends(require_admin), bot: Bot = Depends(get_bot)):
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None or application.status != STATUS_NEW:
            return _redirect(settings, "/applications")
        application.status = STATUS_REJECTED
        application.decided_at = datetime.now(timezone.utc)
        tour = session.get(Tour, application.tour_id)
    await telegram_group.send_rejection(bot, application, tour)
    return _redirect(settings, "/applications", "rejected")


# ---------- туры ----------

@router.get("/tours", response_class=HTMLResponse)
def tours_page(request: Request, settings: Settings = Depends(require_admin)):
    today = tour_service.current_date()
    with session_scope() as session:
        tours = list(session.scalars(select(Tour).order_by(Tour.start_date)))
    upcoming = [t for t in tours if t.is_public(today)]
    past = [t for t in tours if not t.is_public(today)]
    return _render(request, "tours.html", {"upcoming": upcoming, "past": past, "active": "tours",
                                           "publish": publisher.last_status(), **_group_context()})


@router.get("/tours/new", response_class=HTMLResponse)
def new_tour_page(request: Request, settings: Settings = Depends(require_admin)):
    return _render(request, "tour_form.html", {"form": tour_admin.TourForm(), "tour": None,
                                               "transports": tour_admin.TRANSPORTS, "active": "tours"})


@router.get("/tours/{tour_id}/edit", response_class=HTMLResponse)
def edit_tour_page(tour_id: int, request: Request, settings: Settings = Depends(require_admin)):
    with session_scope() as session:
        tour = session.get(Tour, tour_id)
    if tour is None:
        return _redirect(settings, "/tours")
    return _render(request, "tour_form.html", {"form": tour_admin.TourForm.from_tour(tour), "tour": tour,
                                               "transports": tour_admin.TRANSPORTS, "active": "tours"})


def _form(title: str, destination: str, start_date: str, end_date: str, dates_are_demo: str | None,
          transport: str, duration: str, price_label: str, subtitle: str, summary: str, program: str,
          included: str, extras: str, listed: str | None) -> tour_admin.TourForm:
    return tour_admin.TourForm(
        title=title, destination=destination, start_date=start_date, end_date=end_date,
        dates_are_demo=dates_are_demo is not None, transport=transport, duration=duration,
        price_label=price_label, subtitle=subtitle, summary=summary, program=program,
        included=included, extras=extras, listed=listed is not None,
    )


@router.post("/tours/new")
@router.post("/tours/{tour_id}/edit")
async def save_tour(
    request: Request,
    tour_id: int | None = None,
    title: str = Form(""), destination: str = Form(""), start_date: str = Form(""), end_date: str = Form(""),
    dates_are_demo: str | None = Form(None), transport: str = Form("Автобус"), duration: str = Form(""),
    price_label: str = Form(""), subtitle: str = Form(""), summary: str = Form(""), program: str = Form(""),
    included: str = Form(""), extras: str = Form(""), listed: str | None = Form(None),
    photo: UploadFile | None = File(None),
    settings: Settings = Depends(require_admin),
    bot: Bot = Depends(get_bot),
):
    form = _form(title, destination, start_date, end_date, dates_are_demo, transport, duration, price_label,
                 subtitle, summary, program, included, extras, listed)
    photo_bytes = await photo.read() if photo is not None and photo.filename else b""
    try:
        fields = tour_admin.validate(form)
        with session_scope() as session:
            tour = session.get(Tour, tour_id) if tour_id else None
            is_new = tour is None
            if tour_id and is_new:
                return _redirect(settings, "/tours")
            if is_new:
                tour = Tour(tour_code=tour_admin.make_tour_code(session, fields["destination"],
                                                                fields["start_date"]), image=None)
                session.add(tour)
            for key, value in fields.items():
                setattr(tour, key, value)
            tour.source = "admin"
            if photo_bytes:
                tour.image = tour_admin.save_photo(photo_bytes, tour.tour_code)
            session.flush()
            saved_id = tour.id
    except tour_admin.TourFormError as exc:
        with session_scope() as session:
            tour = session.get(Tour, tour_id) if tour_id else None
        return _render(request, "tour_form.html", {"form": form, "tour": tour, "error": str(exc),
                                                   "transports": tour_admin.TRANSPORTS, "active": "tours"},
                       status_code=400)

    notice = "tour_saved" if publisher.publish_in_background(settings) else "tour_saved_local"
    if is_new and not await _publish_to_group(bot, saved_id, settings):
        notice = "tour_group_failed"
    return _redirect(settings, "/tours", notice)


async def _publish_to_group(bot: Bot, tour_id: int, settings: Settings) -> bool:
    """Новый тур: тема в группе и анонс в общей теме. True — успешно или группа не подключена."""
    with session_scope() as session:
        group = app_settings.connected_group(session)
        tour = session.get(Tour, tour_id)
    if group is None or not tour.is_public(tour_service.current_date()):
        return True
    try:
        topic_id = await telegram_group.create_tour_topic(bot, group.chat_id, tour)
        message_id = await telegram_group.announce_tour(bot, group.chat_id, tour, settings)
    except TelegramAPIError as exc:
        logger.warning("Group publish for %s failed: %s", tour.tour_code, exc.__class__.__name__)
        return False
    with session_scope() as session:
        stored = session.get(Tour, tour_id)
        stored.forum_topic_id, stored.announcement_message_id = topic_id, message_id
    return True

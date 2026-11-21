"""Публичные страницы: главная, каталог, страница тура, «Как записаться», «О нас»."""
from __future__ import annotations

import zlib
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import SessionLocal
from app.services import tours as tour_service

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Оттенок фона-заглушки для направлений без фото. Известным странам — подобранный цвет,
# остальным — стабильный оттенок из названия, чтобы у каждой страны был свой фон.
DESTINATION_HUES = {"Испания": 18, "Грузия": 345, "Португалия": 195, "Франция": 275}


def destination_hue(destination: str) -> int:
    if destination in DESTINATION_HUES:
        return DESTINATION_HUES[destination]
    return zlib.crc32(destination.encode("utf-8")) % 360


templates.env.globals["format_date_range"] = tour_service.format_date_range
templates.env.globals["destination_hue"] = destination_hue

router = APIRouter()

HOME_TOURS_LIMIT = 3
SORT_OPTIONS = {"nearest": "Сначала ближайшие", "latest": "Сначала поздние"}


def configure_templates(settings: Settings) -> None:
    """Пути сайта зависят от префикса (GitHub Pages) и режима статической сборки."""
    base = settings.base_path

    def static_url(path: str) -> str:
        return f"{base}/static/{path}"

    def sort_url(sort: str) -> str:
        if settings.static_site:
            return f"{base}/tours/latest/" if sort == "latest" else f"{base}/tours/"
        return f"{base}/tours?sort=latest" if sort == "latest" else f"{base}/tours"

    templates.env.globals.update(
        base=base, static_url=static_url, sort_url=sort_url, organizer=_organizer(settings),
    )


def _organizer(settings: Settings) -> dict | None:
    if not (settings.organizer_name or settings.organizer_contact):
        return None
    return {"name": settings.organizer_name, "contact": settings.organizer_contact}


def render_not_found(request: Request, kind: str = "page"):
    """kind: page — неизвестный адрес, tour — неизвестный тур, finished — тур начался/завершился."""
    return templates.TemplateResponse(request, "not_found.html", {"kind": kind}, status_code=404)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_today() -> date:
    return tour_service.current_date()


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    session: Session = Depends(get_session),
    today: date = Depends(get_today),
):
    tours = tour_service.list_public_tours(session, today)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"tours": tours[:HOME_TOURS_LIMIT], "total": len(tours), "active": "home"},
    )


@router.get("/tours", response_class=HTMLResponse)
def catalog(
    request: Request,
    sort: str = "nearest",
    session: Session = Depends(get_session),
    today: date = Depends(get_today),
):
    if sort not in SORT_OPTIONS:
        sort = "nearest"
    tours = tour_service.list_public_tours(session, today)
    if sort == "latest":
        tours.reverse()
    return templates.TemplateResponse(
        request,
        "catalog.html",
        {"tours": tours, "sort": sort, "sort_options": SORT_OPTIONS, "active": "tours"},
    )


@router.get("/tours/{tour_code}", response_class=HTMLResponse)
def tour_detail(
    tour_code: str,
    request: Request,
    session: Session = Depends(get_session),
    today: date = Depends(get_today),
    settings: Settings = Depends(get_app_settings),
):
    lookup = tour_service.find_public_tour(session, tour_code, today)
    if lookup.status is not tour_service.LookupStatus.OK:
        finished = lookup.status is tour_service.LookupStatus.UNAVAILABLE
        return render_not_found(request, "finished" if finished else "tour")
    tour = lookup.tour
    start_link = tour_service.build_start_link(settings.bot_username, tour.tour_code)
    return templates.TemplateResponse(
        request, "tour.html", {"tour": tour, "start_link": start_link, "active": "tours"}
    )


@router.get("/how", response_class=HTMLResponse)
def how_to_apply(request: Request, settings: Settings = Depends(get_app_settings)):
    bot_link = f"https://t.me/{settings.bot_username}" if settings.bot_username else None
    return templates.TemplateResponse(request, "how.html", {"bot_link": bot_link, "active": "how"})


@router.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {"active": "about"})


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

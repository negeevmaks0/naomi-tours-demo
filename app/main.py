"""FastAPI-приложение сайта. Запуск: uvicorn app.main:create_app --factory"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.database import init_engine
from app.routers import pages
from app.services.seed import init_db

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Пути, для которых 404 остаётся машинным ответом (JSON), а не HTML-страницей.
NON_HTML_PREFIXES = ("/static/", "/api/", "/health")


def wants_html(request: Request) -> bool:
    if request.url.path.startswith(NON_HTML_PREFIXES):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "application/json" not in accept


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        engine = init_engine(settings.database_url)
        init_db(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Naomi Tours Demo", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    pages.configure_templates(settings)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)

    @app.exception_handler(StarletteHTTPException)
    async def not_found_page(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and wants_html(request):
            return pages.render_not_found(request)
        return await http_exception_handler(request, exc)

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

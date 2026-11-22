"""Настройки приложения из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = "sqlite:///./data/naomi_tours_demo.db"
SEED_PATH = PROJECT_ROOT / "data" / "seed_tours.json"
STATIC_DIR = PROJECT_ROOT / "app" / "static"
DEFAULT_SITE_BASE_URL = "http://127.0.0.1:8000"
_LOOPBACK_HOSTS = {"localhost", "0.0.0.0", "::1"}


def is_loopback_url(url: str) -> bool:
    """True для адресов, которые открываются только на этом компьютере."""
    host = (urlsplit(url).hostname or "").lower()
    return (not host or host in _LOOPBACK_HOSTS or host.startswith("127.")
            or host.endswith(".localhost"))


@dataclass(frozen=True)
class Settings:
    bot_token: str = ""
    bot_username: str = ""
    admin_chat_id: int | None = None
    site_base_url: str = DEFAULT_SITE_BASE_URL
    database_url: str = DEFAULT_DATABASE_URL
    demo_mode: bool = True
    # Префикс путей сайта, если он открыт не из корня домена (например, GitHub Pages: /naomi-tours-demo).
    base_path: str = ""
    # True при сборке статической копии сайта (app/export_static.py).
    static_site: bool = False
    # Данные организатора показываются на сайте, только если явно заданы в .env.
    organizer_name: str = ""
    organizer_contact: str = ""

    @property
    def site_is_public(self) -> bool:
        """Можно ли отправлять ссылки на сайт пользователю (открываются не только на этом ПК)."""
        return not is_loopback_url(self.site_base_url)

    @property
    def catalog_url(self) -> str:
        return f"{self.site_base_url.rstrip('/')}/tours"

    def tour_url(self, tour_code: str) -> str:
        return f"{self.site_base_url.rstrip('/')}/tours/{tour_code}"


def _normalize_base_path(raw: str) -> str:
    raw = raw.strip().strip("/")
    return f"/{raw}" if raw else ""


def _parse_admin_chat_id(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError("ADMIN_CHAT_ID должен быть числовым ID чата Telegram или пустым") from exc


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        bot_username=os.getenv("BOT_USERNAME", "").strip().lstrip("@"),
        admin_chat_id=_parse_admin_chat_id(os.getenv("ADMIN_CHAT_ID", "")),
        site_base_url=os.getenv("SITE_BASE_URL", "").strip() or DEFAULT_SITE_BASE_URL,
        database_url=os.getenv("DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL,
        demo_mode=os.getenv("DEMO_MODE", "true").strip().lower() in {"1", "true", "yes"},
        base_path=_normalize_base_path(os.getenv("SITE_BASE_PATH", "")),
        organizer_name=os.getenv("ORGANIZER_NAME", "").strip(),
        organizer_contact=os.getenv("ORGANIZER_CONTACT", "").strip(),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()

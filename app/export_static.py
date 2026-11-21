"""Статическая копия сайта для GitHub Pages.

    python -m app.export_static --out docs --base-path /naomi-tours-demo

Страницы рендерятся тем же FastAPI-приложением, поэтому выглядят как живой сайт.
Каталог фиксируется на дату сборки: тур, который начнётся позже, исчезнет из статической
копии только после повторной сборки. Заявки принимает бот, сайт их не хранит.
"""
from __future__ import annotations

import argparse
import shutil
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import PROJECT_ROOT, load_settings
from app.database import SessionLocal
from app.main import STATIC_DIR, create_app
from app.models import Tour
from app.services import tours as tour_service

PAGES = {
    "/": "index.html",
    "/tours": "tours/index.html",
    "/tours?sort=latest": "tours/latest/index.html",
    "/how": "how/index.html",
    "/about": "about/index.html",
}


def _tour_pages() -> dict[str, str]:
    """Все туры, у которых прямая ссылка работает (включая скрытые из каталога)."""
    today = tour_service.current_date()
    with SessionLocal() as session:
        tours = session.scalars(select(Tour)).all()
        return {f"/tours/{t.tour_code}": f"tours/{t.tour_code}/index.html"
                for t in tours if t.is_public(today)}


def export(out_dir: Path, base_path: str, database_url: str | None = None) -> list[str]:
    settings = load_settings()
    settings = replace(
        settings,
        base_path=base_path,
        static_site=True,
        database_url=database_url or settings.database_url,
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    written = []
    with TestClient(create_app(settings)) as client:
        pages = {**PAGES, **_tour_pages()}
        for url, target in pages.items():
            response = client.get(url, headers={"accept": "text/html"})
            response.raise_for_status()
            _write(out_dir / target, response.text)
            written.append(target)
        not_found = client.get("/__missing__", headers={"accept": "text/html"})
        _write(out_dir / "404.html", not_found.text)
        written.append("404.html")

    shutil.copytree(STATIC_DIR, out_dir / "static")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return written


def _write(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка статической копии сайта")
    parser.add_argument("--out", default="docs", help="папка результата (по умолчанию docs)")
    parser.add_argument("--base-path", default="", help="префикс путей, например /naomi-tours-demo")
    args = parser.parse_args()
    base = "/" + args.base_path.strip("/") if args.base_path.strip("/") else ""
    out = Path(args.out)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    pages = export(out, base)
    print(f"Готово: {len(pages)} страниц в {out} (префикс путей: {base or '/'})")


if __name__ == "__main__":
    main()

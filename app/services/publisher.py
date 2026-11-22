"""Автопубликация сайта на GitHub Pages после изменения туров в админке.

Пересобирает статическую копию (отдельным процессом, чтобы не трогать работающий сайт)
в папку docs/ git-клона и отправляет коммит на GitHub. Включается, если задан SITE_REPO_DIR.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import PROJECT_ROOT, Settings
from app.database import session_scope
from app.services import app_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()
COMMAND_TIMEOUT = 180


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=COMMAND_TIMEOUT)


def _record(status: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with session_scope() as session:
        app_settings.set_value(session, app_settings.PUBLISH_STATUS, f"{stamp}|{status}")


def publish_now(settings: Settings) -> str:
    """Синхронная публикация. Возвращает статус: published / nothing / failed."""
    repo = Path(settings.site_repo_dir)
    with _lock:
        try:
            pull = _run(["git", "pull", "--rebase", "--quiet"], repo)
            if pull.returncode != 0:
                raise RuntimeError(f"git pull: {pull.stderr.strip()[:200]}")
            export = _run([sys.executable, "-m", "app.export_static", "--out", str(repo / "docs"),
                           "--base-path", settings.site_pages_base_path], PROJECT_ROOT)
            if export.returncode != 0:
                raise RuntimeError(f"export: {export.stderr.strip()[-300:]}")
            _run(["git", "add", "-A", "docs"], repo)
            if _run(["git", "diff", "--cached", "--quiet"], repo).returncode == 0:
                status = "nothing"
            else:
                commit = _run(["git", "commit", "-q", "-m", "Обновление туров из админки"], repo)
                if commit.returncode != 0:
                    raise RuntimeError(f"git commit: {commit.stderr.strip()[:200]}")
                push = _run(["git", "push", "-q"], repo)
                if push.returncode != 0:
                    raise RuntimeError(f"git push: {push.stderr.strip()[:200]}")
                status = "published"
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            logger.error("Site publish failed: %s", exc)
            status = "failed"
    _record(status)
    logger.info("Site publish: %s", status)
    return status


def publish_in_background(settings: Settings) -> bool:
    """Запускает публикацию в фоне. False — публикация не настроена (нет SITE_REPO_DIR)."""
    if not settings.site_repo_dir:
        return False
    threading.Thread(target=publish_now, args=(settings,), daemon=True).start()
    return True


def last_status() -> tuple[str, str] | None:
    """(время ISO, статус) последней публикации или None."""
    with session_scope() as session:
        raw = app_settings.get_value(session, app_settings.PUBLISH_STATUS)
    if "|" not in raw:
        return None
    stamp, status = raw.split("|", 1)
    return stamp, status

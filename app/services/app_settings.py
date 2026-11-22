"""Хранилище «ключ — значение» в SQLite: подключённая демо-группа и статус публикации сайта."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import AppSetting

GROUP_ID = "group_chat_id"
GROUP_TITLE = "group_title"
GROUP_IS_FORUM = "group_is_forum"
PENDING_GROUP_ID = "pending_group_chat_id"
PENDING_GROUP_TITLE = "pending_group_title"
PENDING_GROUP_IS_FORUM = "pending_group_is_forum"
PUBLISH_STATUS = "site_publish_status"


def get_value(session: Session, key: str, default: str = "") -> str:
    item = session.get(AppSetting, key)
    return item.value if item is not None else default


def set_value(session: Session, key: str, value: str) -> None:
    item = session.get(AppSetting, key)
    if item is None:
        session.add(AppSetting(key=key, value=value))
    else:
        item.value = value
    session.flush()  # сессии без autoflush: чтобы следующее чтение в этой же сессии видело значение


def delete_keys(session: Session, *keys: str) -> None:
    for key in keys:
        item = session.get(AppSetting, key)
        if item is not None:
            session.delete(item)
    session.flush()


@dataclass(frozen=True)
class GroupInfo:
    chat_id: int
    title: str
    is_forum: bool


def _group(session: Session, id_key: str, title_key: str, forum_key: str) -> GroupInfo | None:
    raw = get_value(session, id_key)
    if not raw:
        return None
    return GroupInfo(int(raw), get_value(session, title_key), get_value(session, forum_key) == "1")


def connected_group(session: Session) -> GroupInfo | None:
    return _group(session, GROUP_ID, GROUP_TITLE, GROUP_IS_FORUM)


def pending_group(session: Session) -> GroupInfo | None:
    return _group(session, PENDING_GROUP_ID, PENDING_GROUP_TITLE, PENDING_GROUP_IS_FORUM)


def remember_pending_group(session: Session, chat_id: int, title: str, is_forum: bool) -> None:
    """Бота добавили в группу — ждём подтверждения владельца в админке."""
    set_value(session, PENDING_GROUP_ID, str(chat_id))
    set_value(session, PENDING_GROUP_TITLE, title)
    set_value(session, PENDING_GROUP_IS_FORUM, "1" if is_forum else "0")


def connect_pending_group(session: Session) -> GroupInfo | None:
    group = pending_group(session)
    if group is None:
        return None
    set_value(session, GROUP_ID, str(group.chat_id))
    set_value(session, GROUP_TITLE, group.title)
    set_value(session, GROUP_IS_FORUM, "1" if group.is_forum else "0")
    delete_keys(session, PENDING_GROUP_ID, PENDING_GROUP_TITLE, PENDING_GROUP_IS_FORUM)
    return group


def forget_group(session: Session, chat_id: int) -> None:
    """Бота удалили из группы: убираем её и из подключённой, и из ожидающей."""
    if get_value(session, GROUP_ID) == str(chat_id):
        delete_keys(session, GROUP_ID, GROUP_TITLE, GROUP_IS_FORUM)
    if get_value(session, PENDING_GROUP_ID) == str(chat_id):
        delete_keys(session, PENDING_GROUP_ID, PENDING_GROUP_TITLE, PENDING_GROUP_IS_FORUM)

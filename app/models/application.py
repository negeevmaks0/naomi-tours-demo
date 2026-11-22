from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.tour import Tour


STATUS_NEW = "new"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Application(Base):
    """Демонстрационная заявка: запрос на рассмотрение, не бронирование."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tour_id: Mapped[int] = mapped_column(ForeignKey("tours.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    comment: Mapped[str] = mapped_column(Text, default="")
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # new — ждёт решения, approved — одобрена (отправлено приглашение), rejected — отклонена.
    status: Mapped[str] = mapped_column(String(32), default=STATUS_NEW)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invite_link: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Сообщение для владельца, если приглашение отправить не удалось (человек не писал боту и т.п.).
    invite_error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    tour: Mapped[Tour] = relationship()

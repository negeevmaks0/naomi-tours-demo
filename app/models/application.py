from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.tour import Tour


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
    status: Mapped[str] = mapped_column(String(32), default="demo_new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    tour: Mapped[Tour] = relationship()

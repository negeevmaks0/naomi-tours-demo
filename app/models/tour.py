from __future__ import annotations

from datetime import date

from sqlalchemy import JSON, Boolean, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tour(Base):
    __tablename__ = "tours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tour_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    destination: Mapped[str] = mapped_column(String(100), default="")
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    dates_are_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    # False — тур не показывается в каталоге (сведения не подтверждены), но прямая ссылка работает.
    listed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    date_note: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[str] = mapped_column(String(100), default="")
    transport: Mapped[str] = mapped_column(String(100), default="")
    image: Mapped[str | None] = mapped_column(String(200), nullable=True)
    image_note: Mapped[str] = mapped_column(Text, default="")
    price_label: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    route: Mapped[list] = mapped_column(JSON, default=list)
    logistics: Mapped[list] = mapped_column(JSON, default=list)
    program: Mapped[list] = mapped_column(JSON, default=list)
    prices: Mapped[list] = mapped_column(JSON, default=list)
    included: Mapped[list] = mapped_column(JSON, default=list)
    extras: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[list] = mapped_column(JSON, default=list)

    def is_public(self, today: date) -> bool:
        """Тур показывается публично и принимает заявки, пока он не начался."""
        return self.start_date > today

    def is_finished(self, today: date) -> bool:
        return self.end_date < today

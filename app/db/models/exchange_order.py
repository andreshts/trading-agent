from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExchangeOrder(Base):
    __tablename__ = "exchange_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    position_id: Mapped[int | None] = mapped_column(ForeignKey("paper_positions.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(24), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8), index=True)
    order_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    order_list_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    executed_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

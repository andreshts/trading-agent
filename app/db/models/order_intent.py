from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderIntent(Base):
    """Persisted record of an order send-attempt, keyed by a deterministic
    client_order_id derived from the intent_id. Allows safe retries: a second
    attempt for the same intent_id reuses the same client_order_id, which the
    exchange will reject as duplicate, and we recover the existing order via
    GET /api/v3/order rather than opening a second position.
    """

    __tablename__ = "order_intents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    intent_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    client_order_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8), index=True)
    role: Mapped[str] = mapped_column(String(24), index=True)
    order_type: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="PENDING")
    exchange_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

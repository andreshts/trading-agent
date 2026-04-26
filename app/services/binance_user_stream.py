import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import websockets
from sqlalchemy import select

from app.db.models import ExchangeOrder, PaperPosition
from app.db.session import SessionLocal
from app.services.audit_logger import AuditLogger
from app.services.binance_spot import BinanceSpotClient


class BinanceUserDataStream:
    def __init__(
        self,
        client: BinanceSpotClient,
        ws_base_url: str,
        audit_logger: AuditLogger | None = None,
        keepalive_seconds: int = 30 * 60,
    ) -> None:
        self.client = client
        self.ws_base_url = ws_base_url.rstrip("/")
        self.audit_logger = audit_logger
        self.keepalive_seconds = keepalive_seconds
        self._listen_key: str | None = None
        self._task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._listen_key = await asyncio.to_thread(self.client.create_listen_key)
        self._task = asyncio.create_task(self._run(), name="binance-user-data-stream")
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(),
            name="binance-user-data-stream-keepalive",
        )
        self._audit("binance_user_stream_started", {"listen_key_created": True})

    async def stop(self) -> None:
        self._stop_event.set()
        for task in (self._task, self._keepalive_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._listen_key:
            await asyncio.to_thread(self.client.close_listen_key, self._listen_key)
            self._listen_key = None
        self._audit("binance_user_stream_stopped", {})

    async def _run(self) -> None:
        if not self._listen_key:
            return
        url = f"{self.ws_base_url}/{self._listen_key}"
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url) as websocket:
                    async for raw_message in websocket:
                        self.handle_event(json.loads(raw_message))
                        if self._stop_event.is_set():
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._audit("binance_user_stream_error", {"error": str(exc)})
                await asyncio.sleep(5)

    async def _keepalive_loop(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self.keepalive_seconds)
            if self._listen_key:
                await asyncio.to_thread(self.client.keepalive_listen_key, self._listen_key)

    def handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("e")
        if event_type == "executionReport":
            self._handle_execution_report(event)
            return
        if event_type == "listStatus":
            self._handle_list_status(event)

    def _handle_execution_report(self, event: dict[str, Any]) -> None:
        symbol = str(event.get("s") or "").upper()
        side = str(event.get("S") or "").upper()
        status = event.get("X")
        order_id = self._as_string(event.get("i"))
        client_order_id = self._as_string(event.get("c"))
        order_list_id = self._as_order_list_id(event.get("g"))

        self._upsert_exchange_order(
            role="user_stream",
            symbol=symbol,
            side=side,
            order_type=str(event.get("o") or "UNKNOWN"),
            status=status,
            exchange_order_id=order_id,
            client_order_id=client_order_id,
            order_list_id=order_list_id,
            quantity=self._as_float(event.get("q")),
            executed_quantity=self._as_float(event.get("z")),
            price=self._as_float(event.get("p")),
            average_price=self._average_event_price(event),
            payload=event,
        )

        if side == "SELL" and status == "FILLED" and order_list_id:
            self._close_oco_position_from_stream(symbol, order_list_id, event)

    def _handle_list_status(self, event: dict[str, Any]) -> None:
        symbol = str(event.get("s") or "").upper()
        order_list_id = self._as_order_list_id(event.get("g"))
        list_status = event.get("L") or event.get("l")
        self._upsert_exchange_order(
            role="user_stream_oco",
            symbol=symbol,
            side="SELL",
            order_type="OCO",
            status=list_status,
            order_list_id=order_list_id,
            payload=event,
        )

        if not order_list_id:
            return
        with SessionLocal() as db:
            positions = db.scalars(
                select(PaperPosition).where(
                    PaperPosition.symbol == symbol,
                    PaperPosition.status == "OPEN",
                )
            ).all()
            for position in positions:
                payload = position.payload or {}
                if payload.get("protective_order_list_id") != order_list_id:
                    continue
                payload.update(
                    {
                        "protective_order_status": list_status,
                        "protective_order_stream_payload": event,
                    }
                )
                position.payload = payload
            db.commit()

    def _close_oco_position_from_stream(
        self,
        symbol: str,
        order_list_id: str,
        event: dict[str, Any],
    ) -> None:
        exit_price = self._average_event_price(event)
        if exit_price is None:
            return

        with SessionLocal() as db:
            positions = db.scalars(
                select(PaperPosition).where(
                    PaperPosition.symbol == symbol,
                    PaperPosition.status == "OPEN",
                )
            ).all()
            for position in positions:
                payload = position.payload or {}
                if payload.get("protective_order_list_id") != order_list_id:
                    continue

                realized_pnl = (exit_price - position.entry_price) * position.quantity
                position.status = "CLOSED"
                position.closed_at = datetime.now(timezone.utc)
                position.exit_price = exit_price
                position.exit_reason = self._event_exit_reason(event, position, exit_price)
                position.realized_pnl = realized_pnl
                payload.update(
                    {
                        "close_exchange_order_id": self._as_string(event.get("i")),
                        "close_exchange_status": event.get("X"),
                        "close_exchange_stream_payload": event,
                    }
                )
                position.payload = payload
                db.commit()
                self._audit(
                    "binance_user_stream_position_closed",
                    {
                        "position_id": position.id,
                        "symbol": symbol,
                        "order_list_id": order_list_id,
                        "exit_price": exit_price,
                        "realized_pnl": realized_pnl,
                    },
                )
                return

    def _upsert_exchange_order(
        self,
        role: str,
        symbol: str,
        side: str,
        order_type: str,
        status: str | None = None,
        exchange_order_id: str | None = None,
        client_order_id: str | None = None,
        order_list_id: str | None = None,
        quantity: float | None = None,
        executed_quantity: float | None = None,
        price: float | None = None,
        average_price: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with SessionLocal() as db:
            row = None
            if exchange_order_id:
                row = db.scalars(
                    select(ExchangeOrder).where(ExchangeOrder.exchange_order_id == exchange_order_id)
                ).first()
            if row is None and client_order_id:
                row = db.scalars(
                    select(ExchangeOrder).where(ExchangeOrder.client_order_id == client_order_id)
                ).first()
            if row is None and order_list_id and role == "user_stream_oco":
                row = db.scalars(
                    select(ExchangeOrder).where(ExchangeOrder.order_list_id == order_list_id)
                ).first()

            if row is None:
                row = ExchangeOrder(
                    role=role,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                )
                db.add(row)

            row.status = status
            row.exchange_order_id = exchange_order_id or row.exchange_order_id
            row.client_order_id = client_order_id or row.client_order_id
            row.order_list_id = order_list_id or row.order_list_id
            row.quantity = quantity if quantity is not None else row.quantity
            row.executed_quantity = (
                executed_quantity if executed_quantity is not None else row.executed_quantity
            )
            row.price = price if price is not None else row.price
            row.average_price = average_price if average_price is not None else row.average_price
            row.payload = payload or {}
            db.commit()

    def _audit(self, event_type: str, payload: dict) -> None:
        if self.audit_logger:
            self.audit_logger.record(event_type, payload)

    @staticmethod
    def _average_event_price(event: dict[str, Any]) -> float | None:
        executed_qty = BinanceUserDataStream._as_float(event.get("z"))
        quote_qty = BinanceUserDataStream._as_float(event.get("Z"))
        if executed_qty and quote_qty:
            return quote_qty / executed_qty
        last_price = BinanceUserDataStream._as_float(event.get("L"))
        return last_price if last_price and last_price > 0 else None

    @staticmethod
    def _event_exit_reason(event: dict[str, Any], position: PaperPosition, exit_price: float) -> str:
        order_type = event.get("o")
        if order_type in {"LIMIT_MAKER", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"}:
            return "take_profit"
        if order_type in {"STOP_LOSS", "STOP_LOSS_LIMIT"}:
            return "stop_loss"
        if position.take_profit is None:
            return "stop_loss"
        return (
            "take_profit"
            if abs(exit_price - position.take_profit) <= abs(exit_price - position.stop_loss)
            else "stop_loss"
        )

    @staticmethod
    def _as_order_list_id(value: Any) -> str | None:
        if value is None or value == -1 or value == "-1":
            return None
        return str(value)

    @staticmethod
    def _as_string(value: Any) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

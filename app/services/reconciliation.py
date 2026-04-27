"""Startup reconciliation between local DB and the exchange.

Without this, if the agent was offline while an OCO triggered or an order
fill happened, the local PaperPosition would stay OPEN forever and the
local ExchangeOrder rows would not reflect reality. We pull the
authoritative state from /openOrders and /myTrades and reconcile.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.models import ExchangeOrder, PaperPosition
from app.db.session import SessionLocal
from app.services.audit_logger import AuditLogger
from app.services.binance_spot import BinanceSpotClient


class StartupReconciliationService:
    def __init__(
        self,
        client: BinanceSpotClient,
        allowed_symbols: list[str],
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.client = client
        self.allowed_symbols = [s.upper() for s in allowed_symbols if s.strip()]
        self.audit_logger = audit_logger

    async def run(self) -> dict[str, Any]:
        if not self.client.configured:
            return {"skipped": True, "reason": "binance client not configured"}

        report: dict[str, Any] = {
            "open_orders_seen": 0,
            "trades_seen": 0,
            "positions_closed": 0,
            "positions_orphan": 0,
            "errors": [],
        }

        for symbol in self.allowed_symbols:
            try:
                open_orders = self.client.get_open_orders(symbol)
                report["open_orders_seen"] += len(open_orders)
                self._sync_open_orders(symbol, open_orders)
            except Exception as exc:
                report["errors"].append({"step": "open_orders", "symbol": symbol, "error": str(exc)})

            try:
                trades = self.client.get_my_trades(symbol, limit=200)
                report["trades_seen"] += len(trades)
                closed = self._reconcile_positions_with_trades(symbol, trades, open_orders=None)
                report["positions_closed"] += closed
            except Exception as exc:
                report["errors"].append({"step": "my_trades", "symbol": symbol, "error": str(exc)})

        report["positions_orphan"] = self._count_orphan_open_positions()

        if self.audit_logger:
            self.audit_logger.record("startup_reconciliation", report)
        return report

    def _sync_open_orders(self, symbol: str, open_orders: list[dict]) -> None:
        if not open_orders:
            return
        with SessionLocal() as db:
            for order in open_orders:
                exchange_order_id = self._as_str(order.get("orderId"))
                client_order_id = self._as_str(order.get("clientOrderId"))
                row = None
                if exchange_order_id:
                    row = db.scalars(
                        select(ExchangeOrder).where(
                            ExchangeOrder.exchange_order_id == exchange_order_id
                        )
                    ).first()
                if row is None and client_order_id:
                    row = db.scalars(
                        select(ExchangeOrder).where(
                            ExchangeOrder.client_order_id == client_order_id
                        )
                    ).first()
                if row is None:
                    row = ExchangeOrder(
                        role="reconciled_open",
                        symbol=symbol.upper(),
                        side=str(order.get("side") or "").upper(),
                        order_type=str(order.get("type") or "UNKNOWN"),
                    )
                    db.add(row)

                row.status = order.get("status") or row.status
                row.exchange_order_id = exchange_order_id or row.exchange_order_id
                row.client_order_id = client_order_id or row.client_order_id
                row.order_list_id = self._as_str(order.get("orderListId")) or row.order_list_id
                row.quantity = self._as_float(order.get("origQty")) or row.quantity
                row.executed_quantity = (
                    self._as_float(order.get("executedQty")) or row.executed_quantity
                )
                row.price = self._as_float(order.get("price")) or row.price
                row.payload = order
            db.commit()

    def _reconcile_positions_with_trades(
        self,
        symbol: str,
        trades: list[dict],
        open_orders: list[dict] | None,
    ) -> int:
        if not trades:
            return 0
        sells_by_order_id: dict[str, list[dict]] = {}
        for trade in trades:
            if trade.get("isBuyer") is True:
                continue
            order_id = self._as_str(trade.get("orderId"))
            if order_id is None:
                continue
            sells_by_order_id.setdefault(order_id, []).append(trade)

        if not sells_by_order_id:
            return 0

        closed_count = 0
        with SessionLocal() as db:
            open_positions = db.scalars(
                select(PaperPosition).where(
                    PaperPosition.symbol == symbol.upper(),
                    PaperPosition.status == "OPEN",
                )
            ).all()

            for position in open_positions:
                payload = position.payload or {}
                # naive heuristic: if there are SELL trades for this symbol after
                # the position was opened and the position has no exchange-side
                # protection still active, close it using the latest SELL fill.
                latest_sell_trades = self._sell_trades_after(
                    sells_by_order_id, position.opened_at
                )
                if not latest_sell_trades:
                    continue

                fill_price, total_qty = self._weighted_average(latest_sell_trades)
                if fill_price is None or total_qty < (position.quantity or 0) * 0.99:
                    continue

                realized_pnl = (fill_price - position.entry_price) * position.quantity
                position.status = "CLOSED"
                position.closed_at = datetime.now(timezone.utc)
                position.exit_price = fill_price
                position.exit_reason = "reconciled_on_startup"
                position.realized_pnl = realized_pnl
                payload.update(
                    {
                        "reconciled_on_startup": True,
                        "reconciliation_trades": latest_sell_trades,
                    }
                )
                position.payload = payload
                closed_count += 1
            db.commit()
        return closed_count

    def _count_orphan_open_positions(self) -> int:
        with SessionLocal() as db:
            rows = db.scalars(
                select(PaperPosition).where(PaperPosition.status == "OPEN")
            ).all()
            return len(rows)

    @staticmethod
    def _sell_trades_after(
        sells_by_order_id: dict[str, list[dict]], after: datetime | None
    ) -> list[dict]:
        if after is None:
            threshold_ms = 0
        else:
            stamp = after if after.tzinfo else after.replace(tzinfo=timezone.utc)
            threshold_ms = int(stamp.timestamp() * 1000)
        result: list[dict] = []
        for trades in sells_by_order_id.values():
            for trade in trades:
                ts = trade.get("time")
                if isinstance(ts, (int, float)) and ts >= threshold_ms:
                    result.append(trade)
        return result

    @staticmethod
    def _weighted_average(trades: list[dict]) -> tuple[float | None, float]:
        total_qty = 0.0
        total_quote = 0.0
        for trade in trades:
            try:
                qty = float(trade.get("qty") or 0)
                price = float(trade.get("price") or 0)
            except (TypeError, ValueError):
                continue
            total_qty += qty
            total_quote += qty * price
        if total_qty <= 0:
            return None, 0.0
        return total_quote / total_qty, total_qty

    @staticmethod
    def _as_str(value: Any) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

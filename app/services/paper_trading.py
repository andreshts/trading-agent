from app.schemas.signal import TradeSignal
from app.schemas.trade import PaperPosition as PaperPositionSchema
from app.schemas.trade import PaperTradeResult
from app.db.models import PaperPosition
from app.db.session import SessionLocal, init_db
from app.services.audit_logger import AuditLogger


class PaperTradingExecutor:
    def __init__(
        self,
        paper_trading_enabled: bool = True,
        real_trading_enabled: bool = False,
        default_order_quantity: float = 0.001,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.paper_trading_enabled = paper_trading_enabled
        self.real_trading_enabled = real_trading_enabled
        self.default_order_quantity = default_order_quantity
        self.audit_logger = audit_logger
        init_db()

    def execute(
        self,
        signal: TradeSignal,
        quantity: float | None = None,
        risk_amount: float | None = None,
    ) -> PaperTradeResult:
        if self.real_trading_enabled:
            raise RuntimeError("Real trading is disabled by design in this server.")
        if not self.paper_trading_enabled:
            raise RuntimeError("Paper trading is disabled.")
        if signal.action == "HOLD":
            raise ValueError("HOLD signals cannot be executed.")
        if signal.entry_price is None or signal.stop_loss is None:
            raise ValueError("Executable signals require entry_price and stop_loss.")

        trade_quantity = quantity or self.default_order_quantity
        calculated_risk = risk_amount or abs(signal.entry_price - signal.stop_loss) * trade_quantity

        with SessionLocal() as db:
            position = PaperPosition(
                symbol=signal.symbol,
                action=signal.action,
                status="OPEN",
                quantity=trade_quantity,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                risk_amount=calculated_risk,
                payload=signal.model_dump(mode="json"),
            )
            db.add(position)
            db.commit()
            db.refresh(position)

        result = PaperTradeResult(
            id=position.id,
            symbol=signal.symbol,
            action=signal.action,
            quantity=trade_quantity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            risk_amount=calculated_risk,
            execution_mode="paper",
        )
        if self.audit_logger:
            self.audit_logger.record("paper_trade", result.model_dump(mode="json"))
        return result

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str = "manual",
    ) -> PaperPositionSchema:
        with SessionLocal() as db:
            position = db.get(PaperPosition, position_id)
            if position is None:
                raise ValueError("Position not found.")
            if position.status != "OPEN":
                raise ValueError("Position is not open.")

            if position.action == "BUY":
                realized_pnl = (exit_price - position.entry_price) * position.quantity
            else:
                realized_pnl = (position.entry_price - exit_price) * position.quantity

            from datetime import datetime, timezone

            position.status = "CLOSED"
            position.closed_at = datetime.now(timezone.utc)
            position.exit_price = exit_price
            position.exit_reason = exit_reason
            position.realized_pnl = realized_pnl
            db.commit()
            db.refresh(position)

            schema = PaperPositionSchema.model_validate(position)
            schema = self._with_payload_metadata(schema, position.payload)

        if self.audit_logger:
            self.audit_logger.record("paper_position_closed", schema.model_dump(mode="json"))
        return schema

    def list_positions(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[PaperPositionSchema]:
        from sqlalchemy import select

        with SessionLocal() as db:
            query = select(PaperPosition).order_by(PaperPosition.opened_at.desc()).limit(limit)
            if status:
                query = query.where(PaperPosition.status == status.upper())
            positions = db.scalars(query).all()
            return [
                self._with_payload_metadata(
                    PaperPositionSchema.model_validate(position),
                    position.payload,
                )
                for position in positions
            ]

    @staticmethod
    def enrich_unrealized_pnl(
        position: PaperPositionSchema,
        current_price: float | None,
    ) -> PaperPositionSchema:
        if position.status != "OPEN" or current_price is None:
            return position

        if position.action == "BUY":
            unrealized_pnl = (current_price - position.entry_price) * position.quantity
        else:
            unrealized_pnl = (position.entry_price - current_price) * position.quantity

        return position.model_copy(
            update={
                "current_price": current_price,
                "unrealized_pnl": unrealized_pnl,
            }
        )

    def has_open_position(self, symbol: str) -> bool:
        from sqlalchemy import select

        with SessionLocal() as db:
            position = db.scalars(
                select(PaperPosition).where(
                    PaperPosition.symbol == symbol.upper(),
                    PaperPosition.status == "OPEN",
                )
            ).first()
            return position is not None

    @staticmethod
    def _with_payload_metadata(
        position: PaperPositionSchema,
        payload: dict | None,
    ) -> PaperPositionSchema:
        payload = payload or {}
        return position.model_copy(
            update={
                "execution_mode": payload.get("execution_mode", "paper"),
                "exchange_order_id": payload.get("exchange_order_id"),
                "exchange_status": payload.get("exchange_status"),
                "close_exchange_order_id": payload.get("close_exchange_order_id"),
                "protective_order_list_id": payload.get("protective_order_list_id"),
                "protective_order_status": payload.get("protective_order_status"),
            }
        )

    def evaluate_open_positions(
        self,
        symbol: str,
        current_price: float,
    ) -> list[PaperPositionSchema]:
        from sqlalchemy import select

        closed: list[PaperPositionSchema] = []
        with SessionLocal() as db:
            positions = db.scalars(
                select(PaperPosition).where(
                    PaperPosition.symbol == symbol.upper(),
                    PaperPosition.status == "OPEN",
                )
            ).all()

        for position in positions:
            exit_reason: str | None = None
            if position.action == "BUY":
                if current_price <= position.stop_loss:
                    exit_reason = "stop_loss"
                elif position.take_profit is not None and current_price >= position.take_profit:
                    exit_reason = "take_profit"
            else:
                if current_price >= position.stop_loss:
                    exit_reason = "stop_loss"
                elif position.take_profit is not None and current_price <= position.take_profit:
                    exit_reason = "take_profit"

            if exit_reason:
                closed.append(self.close_position(position.id, current_price, exit_reason))

        return closed

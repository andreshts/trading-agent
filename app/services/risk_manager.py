from app.db.models import RiskDecisionLog
from app.db.session import SessionLocal
from app.schemas.risk import RiskDecision
from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.services.audit_logger import AuditLogger
from app.services.kill_switch import KillSwitchService


class RiskManager:
    def __init__(
        self,
        max_daily_loss: float,
        max_weekly_loss: float,
        max_trades_per_day: int,
        max_risk_per_trade_percent: float,
        min_confidence: float,
        kill_switch: KillSwitchService,
        default_order_quantity: float = 0.001,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.max_daily_loss = max_daily_loss
        self.max_weekly_loss = max_weekly_loss
        self.max_trades_per_day = max_trades_per_day
        self.max_risk_per_trade_percent = max_risk_per_trade_percent
        self.min_confidence = min_confidence
        self.default_order_quantity = default_order_quantity
        self.kill_switch = kill_switch
        self.audit_logger = audit_logger

    def validate_trade(
        self,
        signal: TradeSignal,
        account_state: AccountState,
        quantity: float | None = None,
    ) -> RiskDecision:
        trade_quantity = quantity or self.default_order_quantity
        decision = self._validate_trade(signal, account_state, trade_quantity)
        if self.audit_logger:
            self.audit_logger.record(
                "risk_decision",
                {
                    "signal": signal.model_dump(mode="json"),
                    "account_state": account_state.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                },
            )
        self._persist_decision(signal, account_state, decision)
        return decision

    def _validate_trade(
        self,
        signal: TradeSignal,
        account_state: AccountState,
        quantity: float,
    ) -> RiskDecision:
        max_risk = account_state.equity * (self.max_risk_per_trade_percent / 100)

        if self.kill_switch.is_active():
            return self._reject("Trading bloqueado por kill switch", max_risk, quantity)

        if not account_state.trading_enabled:
            return self._reject("Trading deshabilitado", max_risk, quantity)

        if account_state.daily_loss >= self.max_daily_loss:
            self.kill_switch.activate("Límite de pérdida diaria alcanzado")
            return self._reject("Límite de pérdida diaria alcanzado", max_risk, quantity)

        if account_state.weekly_loss >= self.max_weekly_loss:
            self.kill_switch.activate("Límite de pérdida semanal alcanzado")
            return self._reject("Límite de pérdida semanal alcanzado", max_risk, quantity)

        if account_state.trades_today >= self.max_trades_per_day:
            return self._reject("Máximo de operaciones diarias alcanzado", max_risk, quantity)

        if signal.action == "HOLD":
            return self._reject("No se ejecutan señales HOLD", max_risk, quantity)

        if signal.confidence < self.min_confidence:
            return self._reject("Confianza inferior al mínimo permitido", max_risk, quantity)

        if signal.stop_loss is None:
            return self._reject("Operación bloqueada: no tiene stop loss", max_risk, quantity)

        if signal.entry_price is None:
            return self._reject("Operación bloqueada: no tiene precio de entrada", max_risk, quantity)

        coherence_error = self._validate_price_coherence(signal)
        if coherence_error:
            return self._reject(coherence_error, max_risk, quantity)

        risk_amount = self.calculate_risk_amount(signal.entry_price, signal.stop_loss, quantity)
        if risk_amount > max_risk:
            return RiskDecision(
                approved=False,
                reason=f"Riesgo por operación superior al {self.max_risk_per_trade_percent:g}%",
                risk_amount=risk_amount,
                max_allowed_risk=max_risk,
                quantity=quantity,
            )

        return RiskDecision(
            approved=True,
            reason="Operación aprobada",
            risk_amount=risk_amount,
            max_allowed_risk=max_risk,
            quantity=quantity,
        )

    @staticmethod
    def calculate_risk_amount(entry_price: float, stop_loss: float, quantity: float) -> float:
        return abs(entry_price - stop_loss) * quantity

    @staticmethod
    def _validate_price_coherence(signal: TradeSignal) -> str | None:
        if signal.entry_price is None or signal.stop_loss is None:
            return None

        if signal.action == "BUY":
            if signal.stop_loss >= signal.entry_price:
                return "BUY inválido: stop_loss debe estar por debajo de entry_price"
            if signal.take_profit is not None and signal.take_profit <= signal.entry_price:
                return "BUY inválido: take_profit debe estar por encima de entry_price"

        if signal.action == "SELL":
            if signal.stop_loss <= signal.entry_price:
                return "SELL inválido: stop_loss debe estar por encima de entry_price"
            if signal.take_profit is not None and signal.take_profit >= signal.entry_price:
                return "SELL inválido: take_profit debe estar por debajo de entry_price"

        return None

    @staticmethod
    def _reject(reason: str, max_risk: float, quantity: float) -> RiskDecision:
        return RiskDecision(
            approved=False,
            reason=reason,
            max_allowed_risk=max_risk,
            quantity=quantity,
        )

    @staticmethod
    def _persist_decision(
        signal: TradeSignal,
        account_state: AccountState,
        decision: RiskDecision,
    ) -> None:
        try:
            with SessionLocal() as db:
                db.add(
                    RiskDecisionLog(
                        symbol=signal.symbol,
                        action=signal.action,
                        approved=decision.approved,
                        reason=decision.reason,
                        payload={
                            "signal": signal.model_dump(mode="json"),
                            "account_state": account_state.model_dump(mode="json"),
                            "decision": decision.model_dump(mode="json"),
                        },
                    )
                )
                db.commit()
        except Exception:
            pass

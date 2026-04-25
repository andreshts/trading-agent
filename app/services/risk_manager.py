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
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.max_daily_loss = max_daily_loss
        self.max_weekly_loss = max_weekly_loss
        self.max_trades_per_day = max_trades_per_day
        self.max_risk_per_trade_percent = max_risk_per_trade_percent
        self.min_confidence = min_confidence
        self.kill_switch = kill_switch
        self.audit_logger = audit_logger

    def validate_trade(self, signal: TradeSignal, account_state: AccountState) -> RiskDecision:
        decision = self._validate_trade(signal, account_state)
        if self.audit_logger:
            self.audit_logger.record(
                "risk_decision",
                {
                    "signal": signal.model_dump(mode="json"),
                    "account_state": account_state.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                },
            )
        return decision

    def _validate_trade(self, signal: TradeSignal, account_state: AccountState) -> RiskDecision:
        if self.kill_switch.is_active():
            return RiskDecision(approved=False, reason="Trading bloqueado por kill switch")

        if not account_state.trading_enabled:
            return RiskDecision(approved=False, reason="Trading deshabilitado")

        if account_state.daily_loss >= self.max_daily_loss:
            self.kill_switch.activate("Límite de pérdida diaria alcanzado")
            return RiskDecision(approved=False, reason="Límite de pérdida diaria alcanzado")

        if account_state.weekly_loss >= self.max_weekly_loss:
            self.kill_switch.activate("Límite de pérdida semanal alcanzado")
            return RiskDecision(approved=False, reason="Límite de pérdida semanal alcanzado")

        if account_state.trades_today >= self.max_trades_per_day:
            return RiskDecision(approved=False, reason="Máximo de operaciones diarias alcanzado")

        if signal.action == "HOLD":
            return RiskDecision(approved=False, reason="No se ejecutan señales HOLD")

        if signal.confidence < self.min_confidence:
            return RiskDecision(approved=False, reason="Confianza inferior al mínimo permitido")

        if signal.stop_loss is None:
            return RiskDecision(approved=False, reason="Operación bloqueada: no tiene stop loss")

        if signal.entry_price is None:
            return RiskDecision(approved=False, reason="Operación bloqueada: no tiene precio de entrada")

        max_risk = account_state.equity * (self.max_risk_per_trade_percent / 100)
        if signal.risk_amount > max_risk:
            return RiskDecision(
                approved=False,
                reason=f"Riesgo por operación superior al {self.max_risk_per_trade_percent:g}%",
            )

        return RiskDecision(approved=True, reason="Operación aprobada")


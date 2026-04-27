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
        max_signal_price_deviation_percent: float = 0.5,
        taker_fee_percent: float = 0.1,
        slippage_assumption_percent: float = 0.05,
        min_reward_to_risk_ratio: float = 1.5,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.max_daily_loss = max_daily_loss
        self.max_weekly_loss = max_weekly_loss
        self.max_trades_per_day = max_trades_per_day
        self.max_risk_per_trade_percent = max_risk_per_trade_percent
        self.min_confidence = min_confidence
        self.default_order_quantity = default_order_quantity
        self.max_signal_price_deviation_percent = max_signal_price_deviation_percent
        self.taker_fee_percent = taker_fee_percent
        self.slippage_assumption_percent = slippage_assumption_percent
        self.min_reward_to_risk_ratio = min_reward_to_risk_ratio
        self.kill_switch = kill_switch
        self.audit_logger = audit_logger

    def pre_signal_skip_reason(self, account_state: AccountState) -> str | None:
        if self.kill_switch.is_active():
            return "Kill switch activo"
        if not account_state.trading_enabled:
            return "Trading deshabilitado"
        if account_state.daily_loss >= self.max_daily_loss:
            return "Límite de pérdida diaria alcanzado"
        if account_state.weekly_loss >= self.max_weekly_loss:
            return "Límite de pérdida semanal alcanzado"
        if account_state.trades_today >= self.max_trades_per_day:
            return "Máximo de operaciones diarias alcanzado"
        return None

    def validate_trade(
        self,
        signal: TradeSignal,
        account_state: AccountState,
        quantity: float | None = None,
        market_price: float | None = None,
    ) -> RiskDecision:
        trade_quantity = quantity or self.default_order_quantity
        decision = self._validate_trade(signal, account_state, trade_quantity, market_price)
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
        market_price: float | None,
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

        deviation_error = self._validate_market_price_deviation(signal, market_price)
        if deviation_error:
            return self._reject(deviation_error, max_risk, quantity)

        rr_error = self._validate_reward_to_risk(signal, quantity)
        if rr_error:
            return self._reject(rr_error, max_risk, quantity)

        risk_amount = self.calculate_risk_amount(
            signal.entry_price, signal.stop_loss, quantity
        )
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

    def calculate_risk_amount(
        self,
        entry_price: float,
        stop_loss: float,
        quantity: float,
    ) -> float:
        """Worst-case loss including round-trip fees and slippage on both legs."""
        price_risk = abs(entry_price - stop_loss) * quantity
        fee_cost = self._round_trip_fee_cost(entry_price, stop_loss, quantity)
        slippage_cost = self._round_trip_slippage_cost(entry_price, stop_loss, quantity)
        return price_risk + fee_cost + slippage_cost

    def _round_trip_fee_cost(
        self, entry_price: float, exit_price: float, quantity: float
    ) -> float:
        fee_rate = self.taker_fee_percent / 100
        return (entry_price + exit_price) * quantity * fee_rate

    def _round_trip_slippage_cost(
        self, entry_price: float, exit_price: float, quantity: float
    ) -> float:
        slip_rate = self.slippage_assumption_percent / 100
        return (entry_price + exit_price) * quantity * slip_rate

    def _validate_reward_to_risk(
        self, signal: TradeSignal, quantity: float
    ) -> str | None:
        if self.min_reward_to_risk_ratio <= 0:
            return None
        if signal.take_profit is None or signal.entry_price is None or signal.stop_loss is None:
            return None

        net_risk = self.calculate_risk_amount(signal.entry_price, signal.stop_loss, quantity)
        if net_risk <= 0:
            return None

        gross_reward = abs(signal.take_profit - signal.entry_price) * quantity
        # Reward also pays exit fees + slippage at the take-profit price.
        reward_fees = self._round_trip_fee_cost(
            signal.entry_price, signal.take_profit, quantity
        )
        reward_slippage = self._round_trip_slippage_cost(
            signal.entry_price, signal.take_profit, quantity
        )
        net_reward = gross_reward - reward_fees - reward_slippage
        if net_reward <= 0:
            return (
                "R:R inválido tras costes: el take_profit no cubre comisiones y slippage"
            )

        ratio = net_reward / net_risk
        if ratio < self.min_reward_to_risk_ratio:
            return (
                f"R:R neto {ratio:.2f} inferior al mínimo {self.min_reward_to_risk_ratio:g}"
            )
        return None

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

    def _validate_market_price_deviation(
        self,
        signal: TradeSignal,
        market_price: float | None,
    ) -> str | None:
        if signal.entry_price is None or market_price is None:
            return None
        if market_price <= 0:
            return None

        deviation_percent = abs(signal.entry_price - market_price) / market_price * 100
        if deviation_percent > self.max_signal_price_deviation_percent:
            return (
                "Precio de entrada demasiado alejado del mercado actual: "
                f"{deviation_percent:.2f}% > {self.max_signal_price_deviation_percent:g}%"
            )
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

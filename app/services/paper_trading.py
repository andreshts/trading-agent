from app.schemas.signal import TradeSignal
from app.schemas.trade import PaperTradeResult
from app.services.audit_logger import AuditLogger


class PaperTradingExecutor:
    def __init__(
        self,
        paper_trading_enabled: bool = True,
        real_trading_enabled: bool = False,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.paper_trading_enabled = paper_trading_enabled
        self.real_trading_enabled = real_trading_enabled
        self.audit_logger = audit_logger

    def execute(self, signal: TradeSignal) -> PaperTradeResult:
        if self.real_trading_enabled:
            raise RuntimeError("Real trading is disabled by design in this server.")
        if not self.paper_trading_enabled:
            raise RuntimeError("Paper trading is disabled.")
        if signal.action == "HOLD":
            raise ValueError("HOLD signals cannot be executed.")
        if signal.entry_price is None or signal.stop_loss is None:
            raise ValueError("Executable signals require entry_price and stop_loss.")

        result = PaperTradeResult(
            symbol=signal.symbol,
            action=signal.action,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )
        if self.audit_logger:
            self.audit_logger.record("paper_trade", result.model_dump(mode="json"))
        return result


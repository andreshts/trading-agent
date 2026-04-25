from app.core.config import Settings
from app.schemas.system import AccountState


class SystemStateService:
    def __init__(self, settings: Settings) -> None:
        self._trading_enabled = settings.trading_enabled
        self._equity = 1000.0
        self._daily_loss = 0.0
        self._weekly_loss = 0.0
        self._trades_today = 0

    def get_account_state(self) -> AccountState:
        return AccountState(
            equity=self._equity,
            daily_loss=self._daily_loss,
            weekly_loss=self._weekly_loss,
            trades_today=self._trades_today,
            trading_enabled=self._trading_enabled,
        )

    def set_trading_enabled(self, enabled: bool) -> AccountState:
        self._trading_enabled = enabled
        return self.get_account_state()

    def register_paper_trade(self) -> AccountState:
        self._trades_today += 1
        return self.get_account_state()

    def reset_simulation(self) -> AccountState:
        self._equity = 1000.0
        self._daily_loss = 0.0
        self._weekly_loss = 0.0
        self._trades_today = 0
        self._trading_enabled = True
        return self.get_account_state()


import pytest

from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.services.binance_spot import BinanceSpotExecutor


class FakeBinanceClient:
    configured = True

    def __init__(self, fill_price: float = 64200) -> None:
        self.orders: list[dict] = []
        self.fill_price = fill_price

    def create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        test_order: bool = False,
        client_order_id: str | None = None,
    ) -> dict:
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "test_order": test_order,
                "client_order_id": client_order_id,
            }
        )
        return {
            "symbol": symbol,
            "orderId": 123,
            "status": "FILLED",
            "executedQty": str(quantity),
            "cummulativeQuoteQty": str(quantity * self.fill_price),
            "fills": [{"price": str(self.fill_price), "qty": str(quantity), "commission": "0", "commissionAsset": "BNB"}],
        }

    def create_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
        test_order: bool = False,
        client_order_id: str | None = None,
    ) -> dict:
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "time_in_force": time_in_force,
                "test_order": test_order,
                "client_order_id": client_order_id,
            }
        )
        return {
            "symbol": symbol,
            "orderId": 456,
            "status": "FILLED",
            "executedQty": str(quantity),
            "cummulativeQuoteQty": str(quantity * price),
            "fills": [{"price": str(price), "qty": str(quantity), "commission": "0", "commissionAsset": "BNB"}],
        }

    def get_account(self) -> dict:
        return {"balances": [{"asset": "USDT", "free": "2500", "locked": "0"}]}


class UnfilledLimitBinanceClient(FakeBinanceClient):
    def create_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
        test_order: bool = False,
        client_order_id: str | None = None,
    ) -> dict:
        return {
            "symbol": symbol,
            "orderId": 789,
            "status": "EXPIRED",
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
            "fills": [],
        }


def make_signal(action: str = "BUY") -> TradeSignal:
    return TradeSignal(
        symbol="BTCUSDT",
        action=action,
        confidence=0.72,
        entry_price=64200,
        stop_loss=62800,
        take_profit=67000,
        risk_amount=10,
        reason="Valid setup.",
    )


def make_executor(
    client: FakeBinanceClient | None = None,
    execution_mode: str = "binance_testnet",
    real_trading_enabled: bool = False,
    order_type: str = "market",
) -> BinanceSpotExecutor:
    return BinanceSpotExecutor(
        client=client or FakeBinanceClient(),
        execution_mode=execution_mode,
        real_trading_enabled=real_trading_enabled,
        default_order_quantity=0.001,
        allowed_symbols=["BTCUSDT"],
        max_notional_per_order=100,
        order_type=order_type,
    )


def test_binance_testnet_executor_places_buy_market_order() -> None:
    client = FakeBinanceClient()
    executor = make_executor(client=client)

    result = executor.execute(make_signal("BUY"))

    assert result.execution_mode == "binance_testnet"
    assert result.exchange_order_id == "123"
    assert result.exchange_status == "FILLED"
    assert client.orders[0]["side"] == "BUY"


def test_binance_executor_recalculates_protective_prices_from_real_fill() -> None:
    client = FakeBinanceClient(fill_price=77620)
    executor = make_executor(client=client)

    result = executor.execute(make_signal("BUY"))

    assert result.entry_price == 77620
    assert result.stop_loss == pytest.approx(75927.35202492212)
    assert result.take_profit == pytest.approx(81005.29595015576)
    assert result.risk_amount == pytest.approx(1.6926479750778817)


def test_binance_spot_executor_rejects_sell_as_opening_trade() -> None:
    executor = make_executor()

    with pytest.raises(ValueError, match="only opens BUY"):
        executor.execute(make_signal("SELL"))


def test_binance_live_requires_real_trading_enabled() -> None:
    executor = make_executor(execution_mode="binance_live", real_trading_enabled=False)

    with pytest.raises(RuntimeError, match="REAL_TRADING_ENABLED=true"):
        executor.execute(make_signal("BUY"))


def test_binance_executor_can_place_limit_ioc_order() -> None:
    client = FakeBinanceClient()
    executor = make_executor(client=client, order_type="limit")

    result = executor.execute(make_signal("BUY"))

    assert result.exchange_order_id == "456"
    assert client.orders[0]["price"] == 64200
    assert client.orders[0]["time_in_force"] == "IOC"


def test_binance_executor_uses_usdt_balance_for_account_state() -> None:
    executor = make_executor()
    fallback = AccountState(
        equity=1000,
        daily_loss=0,
        weekly_loss=0,
        trades_today=0,
        trading_enabled=True,
    )

    account_state = executor.get_account_state(fallback)

    assert account_state.equity == 2500


def test_binance_executor_does_not_create_position_for_unfilled_limit_order() -> None:
    executor = make_executor(client=UnfilledLimitBinanceClient(), order_type="limit")

    with pytest.raises(RuntimeError, match="not filled"):
        executor.execute(make_signal("BUY"))

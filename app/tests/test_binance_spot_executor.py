import pytest

from app.schemas.signal import TradeSignal
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
    ) -> dict:
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "test_order": test_order,
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
) -> BinanceSpotExecutor:
    return BinanceSpotExecutor(
        client=client or FakeBinanceClient(),
        execution_mode=execution_mode,
        real_trading_enabled=real_trading_enabled,
        default_order_quantity=0.001,
        allowed_symbols=["BTCUSDT"],
        max_notional_per_order=100,
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

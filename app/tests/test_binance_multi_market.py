import pytest

from app.schemas.signal import TradeSignal
from app.services.binance_multi_market import (
    BinanceFuturesExecutor,
    BinanceMarginExecutor,
)


class FakeFuturesClient:
    configured = True

    def __init__(self) -> None:
        self.orders: list[dict] = []

    def create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        test_order: bool = False,
        client_order_id: str | None = None,
        reduce_only: bool = False,
        position_side: str | None = None,
    ) -> dict:
        order = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "test_order": test_order,
            "client_order_id": client_order_id,
            "reduce_only": reduce_only,
            "position_side": position_side,
        }
        self.orders.append(order)
        return {
            "symbol": symbol,
            "orderId": 321,
            "status": "FILLED",
            "executedQty": str(quantity),
            "avgPrice": "64200",
        }


class FakeMarginClient:
    configured = True

    def __init__(self) -> None:
        self.orders: list[dict] = []

    def create_margin_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: float | None = None,
        time_in_force: str = "GTC",
        client_order_id: str | None = None,
        isolated: bool = True,
        side_effect_type: str = "AUTO_BORROW_REPAY",
    ) -> dict:
        order = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "time_in_force": time_in_force,
            "client_order_id": client_order_id,
            "isolated": isolated,
            "side_effect_type": side_effect_type,
        }
        self.orders.append(order)
        return {
            "symbol": symbol,
            "orderId": 654,
            "status": "FILLED",
            "executedQty": str(quantity),
            "cummulativeQuoteQty": str(quantity * 64200),
            "fills": [{"price": "64200", "qty": str(quantity)}],
        }


def make_short(market_type: str) -> TradeSignal:
    return TradeSignal(
        symbol="BTCUSDT",
        action="SELL",
        market_type=market_type,
        intent="open",
        position_side="short",
        confidence=0.72,
        entry_price=64200,
        stop_loss=65600,
        take_profit=62000,
        risk_amount=10,
        reason="Valid short setup.",
    )


def make_futures_executor(client: FakeFuturesClient) -> BinanceFuturesExecutor:
    return BinanceFuturesExecutor(
        client=client,
        execution_mode="binance_testnet",
        real_trading_enabled=False,
        default_order_quantity=0.001,
        allowed_symbols=["BTCUSDT"],
        max_notional_per_order=100,
        order_type="market",
    )


def make_margin_executor(
    client: FakeMarginClient,
    execution_mode: str = "binance_live",
    real_trading_enabled: bool = True,
) -> BinanceMarginExecutor:
    return BinanceMarginExecutor(
        client=client,
        execution_mode=execution_mode,
        real_trading_enabled=real_trading_enabled,
        default_order_quantity=0.001,
        allowed_symbols=["BTCUSDT"],
        max_notional_per_order=100,
        order_type="market",
    )


def test_futures_executor_opens_short_with_sell() -> None:
    client = FakeFuturesClient()
    executor = make_futures_executor(client)

    result = executor.execute(make_short("futures"))

    assert result.market_type == "futures"
    assert result.position_side == "short"
    assert client.orders[0]["side"] == "SELL"


def test_margin_executor_opens_short_with_margin_order_in_live_mode() -> None:
    client = FakeMarginClient()
    executor = make_margin_executor(client)

    result = executor.execute(make_short("margin"))

    assert result.market_type == "margin"
    assert result.position_side == "short"
    assert client.orders[0]["side"] == "SELL"
    assert client.orders[0]["side_effect_type"] == "AUTO_BORROW_REPAY"


def test_margin_executor_blocks_binance_testnet() -> None:
    executor = make_margin_executor(
        FakeMarginClient(),
        execution_mode="binance_testnet",
        real_trading_enabled=False,
    )

    with pytest.raises(RuntimeError, match="Margin no está soportado"):
        executor.execute(make_short("margin"))

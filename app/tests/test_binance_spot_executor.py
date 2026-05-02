import pytest

from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.services.binance_spot import BinanceSpotExecutor


class FakeBinanceClient:
    configured = True

    def __init__(self, fill_price: float = 64200) -> None:
        self.orders: list[dict] = []
        self.oco_orders: list[dict] = []
        self.canceled_order_lists: list[dict] = []
        self.fill_price = fill_price
        self.order_list: dict = {
            "orderListId": 999,
            "listOrderStatus": "EXEC_STARTED",
            "listStatusType": "EXEC_STARTED",
            "orderReports": [],
        }

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

    def get_symbol_filters(self, symbol: str) -> dict:
        return {
            "PRICE_FILTER": {
                "tickSize": "0.01000000",
            }
        }

    def create_oco_sell_order(
        self,
        symbol: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
        stop_limit_time_in_force: str = "GTC",
        test_order: bool = False,
        list_client_order_id: str | None = None,
    ) -> dict:
        order = {
            "symbol": symbol,
            "quantity": quantity,
            "take_profit_price": take_profit_price,
            "stop_price": stop_price,
            "stop_limit_price": stop_limit_price,
            "stop_limit_time_in_force": stop_limit_time_in_force,
            "test_order": test_order,
            "list_client_order_id": list_client_order_id,
        }
        self.oco_orders.append(order)
        return self.order_list

    def cancel_order_list(self, symbol: str, order_list_id: str) -> dict:
        cancellation = {"symbol": symbol, "order_list_id": order_list_id}
        self.canceled_order_lists.append(cancellation)
        return {"orderListId": order_list_id, "listOrderStatus": "ALL_DONE"}

    def get_order_list(self, order_list_id: str) -> dict:
        return self.order_list


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
    place_oco_protection: bool = False,
) -> BinanceSpotExecutor:
    return BinanceSpotExecutor(
        client=client or FakeBinanceClient(),
        execution_mode=execution_mode,
        real_trading_enabled=real_trading_enabled,
        default_order_quantity=0.001,
        allowed_symbols=["BTCUSDT"],
        max_notional_per_order=100,
        order_type=order_type,
        place_oco_protection=place_oco_protection,
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


def test_binance_executor_places_oco_protection_after_buy_fill() -> None:
    client = FakeBinanceClient(fill_price=77620)
    executor = make_executor(client=client, place_oco_protection=True)

    result = executor.execute(make_signal("BUY"))

    assert result.protective_order_list_id == "999"
    assert len(client.oco_orders) == 1
    assert client.oco_orders[0]["symbol"] == "BTCUSDT"
    assert client.oco_orders[0]["quantity"] == pytest.approx(0.001)
    assert client.oco_orders[0]["take_profit_price"] == pytest.approx(result.take_profit)
    assert client.oco_orders[0]["stop_price"] == pytest.approx(result.stop_loss)
    assert client.oco_orders[0]["stop_limit_price"] < client.oco_orders[0]["stop_price"]


def test_binance_executor_rounds_oco_prices_to_tick_size() -> None:
    client = FakeBinanceClient(fill_price=78493.98)
    executor = make_executor(client=client, place_oco_protection=True)
    signal = TradeSignal(
        symbol="BTCUSDT",
        action="BUY",
        confidence=0.7,
        entry_price=78493.98,
        stop_loss=78310.54,
        take_profit=78596.61,
        reason="Valid setup.",
    )

    result = executor.execute(signal)

    assert result.stop_loss == pytest.approx(78310.54)
    assert result.take_profit == pytest.approx(78596.61)
    assert client.oco_orders[0]["stop_limit_price"] == pytest.approx(78232.22)


def test_binance_executor_cancels_oco_before_manual_close() -> None:
    client = FakeBinanceClient(fill_price=77620)
    executor = make_executor(client=client, place_oco_protection=True)
    result = executor.execute(make_signal("BUY"))

    closed = executor.close_position(result.id or 0, exit_price=78000, exit_reason="manual")

    assert closed.status == "CLOSED"
    assert client.canceled_order_lists == [{"symbol": "BTCUSDT", "order_list_id": "999"}]
    assert client.orders[-1]["side"] == "SELL"


def test_binance_executor_syncs_position_closed_by_oco() -> None:
    client = FakeBinanceClient(fill_price=77620)
    executor = make_executor(client=client, place_oco_protection=True)
    result = executor.execute(make_signal("BUY"))
    client.order_list = {
        "orderListId": 999,
        "listOrderStatus": "ALL_DONE",
        "listStatusType": "ALL_DONE",
        "orderReports": [
            {
                "side": "SELL",
                "status": "FILLED",
                "executedQty": "0.001",
                "cummulativeQuoteQty": "81.00529595015576",
                "price": "81005.29595015576",
            }
        ],
    }

    closed = executor.evaluate_open_positions("BTCUSDT", current_price=81005.29595015576)
    target = next(position for position in closed if position.id == result.id)

    assert target.status == "CLOSED"
    assert target.exit_reason == "take_profit"
    assert target.exit_price == pytest.approx(81005.29595015576)

from app.schemas.signal import TradeSignal
from app.services.binance_spot import BinanceSpotExecutor
from app.tests.test_binance_spot_executor import FakeBinanceClient, make_signal


def make_executor(client: FakeBinanceClient) -> BinanceSpotExecutor:
    return BinanceSpotExecutor(
        client=client,
        execution_mode="binance_testnet",
        real_trading_enabled=False,
        default_order_quantity=0.001,
        allowed_symbols=["BTCUSDT"],
        max_notional_per_order=100,
        order_type="market",
    )


def test_client_order_id_is_deterministic_per_intent() -> None:
    intent_id_a = "intent-A"
    intent_id_b = "intent-A"
    intent_id_c = "intent-B"

    a = BinanceSpotExecutor._derive_client_order_id(intent_id_a, "BUY")
    b = BinanceSpotExecutor._derive_client_order_id(intent_id_b, "BUY")
    c = BinanceSpotExecutor._derive_client_order_id(intent_id_c, "BUY")

    assert a == b
    assert a != c
    assert a.startswith("ocx-b-")


def test_repeat_execute_with_same_intent_id_does_not_send_second_order() -> None:
    client = FakeBinanceClient()
    executor = make_executor(client)
    signal = make_signal("BUY")

    first = executor.execute(signal, intent_id="my-intent-1")
    second = executor.execute(signal, intent_id="my-intent-1")

    assert len(client.orders) == 1, "second call should not place a new order"
    assert first.id == second.id
    assert first.exchange_order_id == second.exchange_order_id

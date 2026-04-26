import pytest

from app.db.models import ExchangeOrder, PaperPosition
from app.db.session import SessionLocal, init_db
from app.services.binance_user_stream import BinanceUserDataStream


class FakeListenKeyClient:
    def create_listen_key(self) -> str:
        return "listen-key"

    def keepalive_listen_key(self, listen_key: str) -> None:
        return None

    def close_listen_key(self, listen_key: str) -> None:
        return None


def test_user_stream_closes_local_position_when_oco_sell_fills() -> None:
    init_db()
    with SessionLocal() as db:
        position = PaperPosition(
            symbol="BTCUSDT",
            action="BUY",
            status="OPEN",
            quantity=0.001,
            entry_price=77620,
            stop_loss=76000,
            take_profit=81000,
            risk_amount=1.62,
            payload={
                "execution_mode": "binance_testnet",
                "protective_order_list_id": "999",
            },
        )
        db.add(position)
        db.commit()
        db.refresh(position)
        position_id = position.id

    stream = BinanceUserDataStream(
        client=FakeListenKeyClient(),
        ws_base_url="wss://example.test/ws",
    )

    stream.handle_event(
        {
            "e": "executionReport",
            "s": "BTCUSDT",
            "S": "SELL",
            "o": "LIMIT_MAKER",
            "X": "FILLED",
            "i": 987,
            "c": "client-close",
            "g": 999,
            "q": "0.001",
            "z": "0.001",
            "Z": "81",
            "p": "81000",
            "L": "81000",
        }
    )

    with SessionLocal() as db:
        position = db.get(PaperPosition, position_id)
        order = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == "987").first()

    assert position is not None
    assert position.status == "CLOSED"
    assert position.exit_reason == "take_profit"
    assert position.exit_price == 81000
    assert position.realized_pnl == pytest.approx(3.38)
    assert order is not None
    assert order.status == "FILLED"

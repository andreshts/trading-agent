from app.services.market_service import MarketService


def make_candles(start: float = 100.0, count: int = 60) -> list[dict]:
    candles = []
    price = start
    for index in range(count):
        close = price + 1
        candles.append(
            {
                "open_time": index,
                "open": price,
                "high": close + 0.5,
                "low": price - 0.5,
                "close": close,
                "volume": 100 + index,
                "close_time": index,
            }
        )
        price = close
    return candles


def test_summarize_candles_includes_indicators() -> None:
    summary = MarketService.summarize_candles(make_candles(), current_price=160)

    assert "Precio actual: 160" in summary
    assert "EMA 9" in summary
    assert "RSI 14" in summary
    assert "ratio volumen" in summary
    assert "tendencia EMA: alcista" in summary


def test_normalize_binance_interval_accepts_uppercase_timeframe() -> None:
    assert MarketService._normalize_binance_interval("1H") == "1h"
    assert MarketService._normalize_binance_interval("15M") == "15m"


def test_summarize_candles_requires_enough_data() -> None:
    assert MarketService.summarize_candles(make_candles(count=10)) == ""

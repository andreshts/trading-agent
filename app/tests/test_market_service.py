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


def test_closed_candles_excludes_current_open_binance_candle() -> None:
    candles = make_candles(count=31)
    candles[-1]["close_time"] = 2_000
    candles[-1]["volume"] = 0.01

    closed = MarketService._closed_candles(candles, now_ms=1_999)

    assert len(closed) == 30
    assert closed[-1]["volume"] == 129


def test_summary_volume_uses_last_closed_candle_after_filtering() -> None:
    candles = make_candles(count=60)
    candles[-1]["close_time"] = 2_000
    candles[-1]["volume"] = 0.01

    closed = MarketService._closed_candles(candles, now_ms=1_999)
    summary = MarketService.summarize_candles(closed, current_price=160)

    assert "Volumen actual: 158" in summary
    assert "Volumen actual: 0.01" not in summary

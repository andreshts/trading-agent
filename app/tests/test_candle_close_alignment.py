from app.services.autonomous_runner import AutonomousRunner, _timeframe_to_seconds


def _make_runner() -> AutonomousRunner:
    runner = AutonomousRunner(
        max_consecutive_errors=10,
        backoff_base_seconds=1.0,
        backoff_max_seconds=60.0,
        candle_close_buffer_seconds=2.0,
    )
    runner._interval_seconds = 5.0
    runner._consecutive_errors = 0
    return runner


def test_timeframe_to_seconds_known() -> None:
    assert _timeframe_to_seconds("15M") == 900
    assert _timeframe_to_seconds("1h") == 3600
    assert _timeframe_to_seconds("4H") == 14400
    assert _timeframe_to_seconds("1d") == 86400


def test_timeframe_to_seconds_unknown_returns_none() -> None:
    assert _timeframe_to_seconds("bogus") is None
    assert _timeframe_to_seconds("") is None


def test_compute_sleep_returns_interval_when_align_disabled() -> None:
    runner = _make_runner()
    runner._timeframe = "15M"
    runner._align_to_candle_close = False
    assert runner._compute_sleep(iteration_had_error=False) == 5.0


def test_compute_sleep_returns_interval_when_timeframe_unknown() -> None:
    runner = _make_runner()
    runner._timeframe = "BOGUS"
    runner._align_to_candle_close = True
    assert runner._compute_sleep(iteration_had_error=False) == 5.0


def test_seconds_until_next_candle_close_aligned_to_utc_buckets() -> None:
    runner = _make_runner()
    runner._timeframe = "15M"
    # 900s candle: at t=0 the next close is the entire candle later (+ buffer).
    assert runner._seconds_until_next_candle_close(now_ts=0.0) == 900 + 2.0
    # 1s into a 15m candle: ~899s remaining.
    assert runner._seconds_until_next_candle_close(now_ts=1.0) == 899 + 2.0
    # 899s into a 15m candle: ~1s remaining.
    assert runner._seconds_until_next_candle_close(now_ts=899.0) == 1 + 2.0


def test_compute_sleep_with_align_uses_candle_close_when_larger_than_interval() -> None:
    runner = _make_runner()
    runner._timeframe = "15M"
    runner._align_to_candle_close = True
    runner._interval_seconds = 5.0

    # The actual value depends on real time, so just assert it's much bigger
    # than the floor and bounded by one full candle plus buffer.
    sleep = runner._compute_sleep(iteration_had_error=False)
    assert sleep >= 5.0
    assert sleep <= 900 + 2.0 + 0.001


def test_compute_sleep_falls_back_to_backoff_on_error_even_with_align() -> None:
    runner = _make_runner()
    runner._timeframe = "15M"
    runner._align_to_candle_close = True
    runner._interval_seconds = 1.0
    runner._consecutive_errors = 3
    # On error, exponential backoff takes precedence; we don't wait for candle close.
    sleep = runner._compute_sleep(iteration_had_error=True)
    assert sleep == 4.0

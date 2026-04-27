import asyncio
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.schemas.agent import AgentTickRequest, AgentTickResult
from app.services.audit_logger import AuditLogger
from app.services.kill_switch import KillSwitchService


TickHandler = Callable[[AgentTickRequest], Awaitable[AgentTickResult]]


_TIMEFRAME_SECONDS: dict[str, int] = {
    "1M": 60,
    "3M": 180,
    "5M": 300,
    "15M": 900,
    "30M": 1800,
    "1H": 3600,
    "2H": 7200,
    "4H": 14400,
    "6H": 21600,
    "8H": 28800,
    "12H": 43200,
    "1D": 86400,
    "3D": 259200,
    "1W": 604800,
}


def _timeframe_to_seconds(timeframe: str) -> int | None:
    return _TIMEFRAME_SECONDS.get(timeframe.strip().upper())


class AutonomousRunner:
    def __init__(
        self,
        audit_logger: AuditLogger | None = None,
        kill_switch: KillSwitchService | None = None,
        max_consecutive_errors: int = 5,
        backoff_base_seconds: float = 1.0,
        backoff_max_seconds: float = 60.0,
        candle_close_buffer_seconds: float = 2.0,
    ) -> None:
        self.audit_logger = audit_logger
        self.kill_switch = kill_switch
        self.max_consecutive_errors = max_consecutive_errors
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.candle_close_buffer_seconds = candle_close_buffer_seconds
        self._task: asyncio.Task | None = None
        self._symbols: list[str] = []
        self._timeframe = "1H"
        self._market_context = ""
        self._interval_seconds = 60.0
        self._open_new_position = True
        self._align_to_candle_close = False
        self._last_tick_at: str | None = None
        self._last_results: dict[str, dict] = {}
        self._last_error: str | None = None
        self._consecutive_errors = 0
        self._tripped_reason: str | None = None

    def start(
        self,
        symbols: list[str],
        timeframe: str,
        market_context: str,
        interval_seconds: float,
        open_new_position: bool,
        tick_handler: TickHandler,
        align_to_candle_close: bool = False,
    ) -> dict:
        if self.is_running:
            raise RuntimeError("Autonomous runner is already running.")

        self._symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        if not self._symbols:
            raise ValueError("At least one symbol is required.")

        self._timeframe = timeframe.strip().upper()
        self._market_context = market_context.strip()
        self._interval_seconds = interval_seconds
        self._open_new_position = open_new_position
        self._align_to_candle_close = align_to_candle_close
        self._last_error = None
        self._last_results = {}
        self._consecutive_errors = 0
        self._tripped_reason = None
        self._task = asyncio.create_task(self._run(tick_handler))

        if self.audit_logger:
            self.audit_logger.record("autonomous_runner_started", self.status())
        return self.status()

    async def stop(self) -> dict:
        if self._task is None:
            return self.status()

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

        if self.audit_logger:
            self.audit_logger.record("autonomous_runner_stopped", self.status())
        return self.status()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {
            "running": self.is_running,
            "symbols": self._symbols,
            "timeframe": self._timeframe,
            "interval_seconds": self._interval_seconds,
            "open_new_position": self._open_new_position,
            "align_to_candle_close": self._align_to_candle_close,
            "last_tick_at": self._last_tick_at,
            "last_results": self._last_results,
            "last_error": self._last_error,
            "consecutive_errors": self._consecutive_errors,
            "circuit_breaker_tripped": self._tripped_reason is not None,
            "circuit_breaker_reason": self._tripped_reason,
        }

    async def _run(self, tick_handler: TickHandler) -> None:
        while True:
            iteration_had_error = False
            for symbol in self._symbols:
                request = AgentTickRequest(
                    symbol=symbol,
                    timeframe=self._timeframe,
                    market_context=self._market_context,
                    open_new_position=self._open_new_position,
                )
                try:
                    result = await tick_handler(request)
                    self._last_results[symbol] = result.model_dump(mode="json")
                    self._last_error = None
                    self._consecutive_errors = 0
                except Exception as exc:
                    iteration_had_error = True
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    self._consecutive_errors += 1
                    if self.audit_logger:
                        self.audit_logger.record(
                            "autonomous_runner_error",
                            {
                                "symbol": symbol,
                                "error": self._last_error,
                                "consecutive_errors": self._consecutive_errors,
                            },
                        )
                    if self._consecutive_errors >= self.max_consecutive_errors:
                        self._trip_circuit_breaker()
                        return

            self._last_tick_at = datetime.now(timezone.utc).isoformat()
            await asyncio.sleep(self._compute_sleep(iteration_had_error))

    def _compute_sleep(self, iteration_had_error: bool) -> float:
        if iteration_had_error and self.backoff_base_seconds > 0:
            backoff = self.backoff_base_seconds * (2 ** (self._consecutive_errors - 1))
            return min(max(backoff, self._interval_seconds), self.backoff_max_seconds)
        if self._align_to_candle_close:
            next_close = self._seconds_until_next_candle_close(time.time())
            if next_close is not None:
                return max(next_close, self._interval_seconds)
        return self._interval_seconds

    def _seconds_until_next_candle_close(self, now_ts: float) -> float | None:
        interval = _timeframe_to_seconds(self._timeframe)
        if interval is None:
            return None
        seconds_into_candle = now_ts % interval
        return (interval - seconds_into_candle) + self.candle_close_buffer_seconds

    def _trip_circuit_breaker(self) -> None:
        reason = (
            f"Circuit breaker tripped after {self._consecutive_errors} consecutive errors: "
            f"{self._last_error}"
        )
        self._tripped_reason = reason
        if self.audit_logger:
            self.audit_logger.record(
                "autonomous_runner_circuit_breaker_tripped",
                {
                    "consecutive_errors": self._consecutive_errors,
                    "last_error": self._last_error,
                    "reason": reason,
                },
            )
        if self.kill_switch is not None:
            try:
                self.kill_switch.activate(reason)
            except Exception:
                pass

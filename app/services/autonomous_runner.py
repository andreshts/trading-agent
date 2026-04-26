import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.schemas.agent import AgentTickRequest, AgentTickResult
from app.services.audit_logger import AuditLogger


TickHandler = Callable[[AgentTickRequest], Awaitable[AgentTickResult]]


class AutonomousRunner:
    def __init__(self, audit_logger: AuditLogger | None = None) -> None:
        self.audit_logger = audit_logger
        self._task: asyncio.Task | None = None
        self._symbols: list[str] = []
        self._timeframe = "1H"
        self._market_context = ""
        self._interval_seconds = 60.0
        self._open_new_position = True
        self._last_tick_at: str | None = None
        self._last_results: dict[str, dict] = {}
        self._last_error: str | None = None

    def start(
        self,
        symbols: list[str],
        timeframe: str,
        market_context: str,
        interval_seconds: float,
        open_new_position: bool,
        tick_handler: TickHandler,
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
        self._last_error = None
        self._last_results = {}
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
            "last_tick_at": self._last_tick_at,
            "last_results": self._last_results,
            "last_error": self._last_error,
        }

    async def _run(self, tick_handler: TickHandler) -> None:
        while True:
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
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    if self.audit_logger:
                        self.audit_logger.record(
                            "autonomous_runner_error",
                            {"symbol": symbol, "error": self._last_error},
                        )

            self._last_tick_at = datetime.now(timezone.utc).isoformat()
            await asyncio.sleep(self._interval_seconds)

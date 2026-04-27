from contextlib import asynccontextmanager

import asyncio
import logging

from fastapi import FastAPI
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agent, health, risk, system, trades, ws
from app.api.security import require_api_key
from app.core.config import get_settings
from app.db.session import init_db
from app.services.audit_logger import AuditLogger
from app.services.binance_spot import BinanceSpotClient
from app.services.binance_user_stream import BinanceUserDataStream
from app.services.event_bus import get_event_bus


logger = logging.getLogger(__name__)

settings = get_settings()


PRICE_TICKER_INTERVAL_SECONDS = 2.0


async def _price_ticker_loop() -> None:
    """Periodically push current prices for open positions while WS clients exist."""
    bus = get_event_bus()
    # Lazy imports to avoid touching dependencies before settings are ready.
    from app.api.deps import get_market_service, get_paper_executor

    while True:
        try:
            await asyncio.sleep(PRICE_TICKER_INTERVAL_SECONDS)
            if not bus.has_subscribers():
                continue
            executor = get_paper_executor()
            positions = executor.list_positions(status="OPEN", limit=200)
            symbols = {p.symbol for p in positions}
            if not symbols:
                continue
            market = get_market_service()
            prices: dict[str, float] = {}
            for symbol in symbols:
                price = await market.get_current_price(symbol)
                if price is not None:
                    prices[symbol] = price
            if prices:
                bus.publish("position_prices", {"prices": prices})
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive
            logger.exception("price ticker loop error")
            await asyncio.sleep(PRICE_TICKER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bus = get_event_bus()
    bus.bind_loop(asyncio.get_running_loop())
    price_ticker_task = asyncio.create_task(_price_ticker_loop(), name="price-ticker")
    user_stream = None
    if settings.binance_user_stream_enabled and settings.execution_mode in {
        "binance_testnet",
        "binance_live",
    }:
        base_url = (
            settings.binance_testnet_base_url
            if settings.execution_mode == "binance_testnet"
            else settings.binance_live_base_url
        )
        ws_base_url = (
            settings.binance_testnet_ws_base_url
            if settings.execution_mode == "binance_testnet"
            else settings.binance_live_ws_base_url
        )
        user_stream = BinanceUserDataStream(
            client=BinanceSpotClient(
                api_key=settings.binance_api_key,
                api_secret=settings.binance_api_secret,
                base_url=base_url,
                recv_window=settings.binance_recv_window,
                max_retries=settings.binance_max_retries,
                retry_backoff_seconds=settings.binance_retry_backoff_seconds,
            ),
            ws_base_url=ws_base_url,
            audit_logger=AuditLogger(),
        )
        await user_stream.start()
        app.state.binance_user_stream = user_stream
    try:
        yield
    finally:
        price_ticker_task.cancel()
        try:
            await price_ticker_task
        except (asyncio.CancelledError, Exception):
            pass
        if user_stream:
            await user_stream.stop()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected = [Depends(require_api_key)]

app.include_router(health.router)
app.include_router(ws.router, tags=["realtime"])
app.include_router(agent.router, prefix="/agent", tags=["agent"], dependencies=protected)
app.include_router(risk.router, prefix="/risk", tags=["risk"], dependencies=protected)
app.include_router(trades.router, prefix="/trades", tags=["trades"], dependencies=protected)
app.include_router(system.router, prefix="/system", tags=["system"], dependencies=protected)

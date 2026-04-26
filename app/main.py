from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agent, health, risk, system, trades
from app.core.config import get_settings
from app.db.session import init_db
from app.services.audit_logger import AuditLogger
from app.services.binance_spot import BinanceSpotClient
from app.services.binance_user_stream import BinanceUserDataStream


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
            ),
            ws_base_url=ws_base_url,
            audit_logger=AuditLogger(),
        )
        await user_stream.start()
        app.state.binance_user_stream = user_stream
    try:
        yield
    finally:
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

app.include_router(health.router)
app.include_router(agent.router, prefix="/agent", tags=["agent"])
app.include_router(risk.router, prefix="/risk", tags=["risk"])
app.include_router(trades.router, prefix="/trades", tags=["trades"])
app.include_router(system.router, prefix="/system", tags=["system"])

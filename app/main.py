from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agent, health, risk, system, trades
from app.core.config import get_settings
from app.db.session import init_db


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


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

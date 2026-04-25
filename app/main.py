from fastapi import FastAPI

from app.api.routes import agent, health, risk, system, trades
from app.core.config import get_settings


settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(health.router)
app.include_router(agent.router, prefix="/agent", tags=["agent"])
app.include_router(risk.router, prefix="/risk", tags=["risk"])
app.include_router(trades.router, prefix="/trades", tags=["trades"])
app.include_router(system.router, prefix="/system", tags=["system"])


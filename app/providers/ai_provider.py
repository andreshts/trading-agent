import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import ValidationError

from app.schemas.signal import SignalRequest, TradeSignal


class AIProvider(ABC):
    @abstractmethod
    async def generate_signal(self, request: SignalRequest, prompt: str) -> TradeSignal:
        raise NotImplementedError


def hold_signal(symbol: str, reason: str) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        action="HOLD",
        confidence=0,
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        risk_amount=0,
        reason=reason,
    )


def parse_trade_signal(raw_content: str | dict[str, Any], symbol: str) -> TradeSignal:
    try:
        payload = raw_content if isinstance(raw_content, dict) else json.loads(raw_content)
        payload.setdefault("symbol", symbol)
        return TradeSignal.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return hold_signal(symbol, f"Invalid AI response: {exc}")


import re

from app.providers.ai_provider import AIProvider
from app.schemas.signal import SignalRequest, TradeSignal


class MockAIProvider(AIProvider):
    async def generate_signal(self, request: SignalRequest, prompt: str) -> TradeSignal:
        context = request.market_context.lower()
        price = self._first_number(context)

        if any(word in context for word in ["alcista", "bullish", "ruptura", "breakout"]):
            action = "BUY"
            confidence = 0.68
            reason = "Contexto alcista detectado por proveedor local de simulación."
            stop_loss = price * 0.98 if price else None
            take_profit = price * 1.04 if price else None
        elif any(word in context for word in ["bajista", "bearish", "rechazo", "breakdown"]):
            action = "SELL"
            confidence = 0.64
            reason = "Contexto bajista detectado por proveedor local de simulación."
            stop_loss = price * 1.02 if price else None
            take_profit = price * 0.96 if price else None
        else:
            action = "HOLD"
            confidence = 0.35
            reason = "No hay información suficiente para proponer una operación."
            stop_loss = None
            take_profit = None

        if action in {"BUY", "SELL"} and price is None:
            action = "HOLD"
            confidence = 0.25
            reason = "No se detectó precio de entrada en el contexto; se mantiene HOLD."

        return TradeSignal(
            symbol=request.symbol,
            action=action,
            confidence=confidence,
            entry_price=price if action != "HOLD" else None,
            stop_loss=stop_loss if action != "HOLD" else None,
            take_profit=take_profit if action != "HOLD" else None,
            risk_amount=10 if action != "HOLD" else 0,
            reason=reason,
        )

    @staticmethod
    def _first_number(value: str) -> float | None:
        match = re.search(r"\d+(?:[.,]\d+)?", value)
        if not match:
            return None
        return float(match.group(0).replace(",", "."))


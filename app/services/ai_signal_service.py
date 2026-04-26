from app.db.models import AISignalLog
from app.db.session import SessionLocal
from app.providers.ai_provider import AIProvider, hold_signal
from app.schemas.signal import SignalRequest, TradeSignal
from app.services.audit_logger import AuditLogger


PROMPT_TEMPLATE = """Eres un asistente de análisis de mercado para un sistema de trading automatizado.

Tu tarea es analizar el contexto recibido y devolver una señal estructurada.

Reglas obligatorias:
- Responde únicamente en JSON válido.
- No incluyas texto fuera del JSON.
- Si no hay suficiente información, usa action = "HOLD".
- Nunca sugieras una operación sin stop_loss.
- Nunca inventes precios si no están en el contexto.
- Usa los datos calculados de mercado antes que el criterio textual del usuario.
- Si propones BUY o SELL, entry_price debe ser coherente con el precio actual.
- Incluye una justificación breve en el campo reason.

Formato esperado:
{{
  "symbol": "string",
  "action": "BUY | SELL | HOLD",
  "confidence": number entre 0 y 1,
  "entry_price": number o null,
  "stop_loss": number o null,
  "take_profit": number o null,
  "risk_amount": number,
  "reason": "string"
}}

Símbolo: {symbol}
Temporalidad: {timeframe}

Contexto de mercado:
{market_context}
"""


class AISignalService:
    def __init__(self, provider: AIProvider, audit_logger: AuditLogger | None = None) -> None:
        self.provider = provider
        self.audit_logger = audit_logger

    async def generate_signal(self, request: SignalRequest) -> TradeSignal:
        if not request.market_context.strip():
            return hold_signal(request.symbol, "No market context provided.")

        prompt = self.build_prompt(request)
        if self.audit_logger:
            self.audit_logger.record(
                "ai_prompt",
                {
                    "symbol": request.symbol,
                    "timeframe": request.timeframe,
                    "prompt": prompt,
                },
            )

        signal = await self.provider.generate_signal(request=request, prompt=prompt)

        if self.audit_logger:
            self.audit_logger.record("ai_signal", signal.model_dump(mode="json"))
        self._persist_signal(signal)
        return signal

    @staticmethod
    def build_prompt(request: SignalRequest) -> str:
        return PROMPT_TEMPLATE.format(
            symbol=request.symbol,
            timeframe=request.timeframe,
            market_context=request.market_context,
        )

    @staticmethod
    def _persist_signal(signal: TradeSignal) -> None:
        try:
            with SessionLocal() as db:
                db.add(
                    AISignalLog(
                        symbol=signal.symbol,
                        action=signal.action,
                        confidence=signal.confidence,
                        payload=signal.model_dump(mode="json"),
                    )
                )
                db.commit()
        except Exception:
            pass

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
{reward_to_risk_rule}
- En BUY: stop_loss < entry_price < take_profit. En SELL: take_profit <
  entry_price < stop_loss. Verifica este orden antes de responder.
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
    def __init__(
        self,
        provider: AIProvider,
        audit_logger: AuditLogger | None = None,
        min_reward_to_risk_ratio: float = 1.5,
    ) -> None:
        self.provider = provider
        self.audit_logger = audit_logger
        self.min_reward_to_risk_ratio = min_reward_to_risk_ratio

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

    def build_prompt(self, request: SignalRequest) -> str:
        return PROMPT_TEMPLATE.format(
            symbol=request.symbol,
            timeframe=request.timeframe,
            market_context=request.market_context,
            reward_to_risk_rule=self._reward_to_risk_rule(),
        )

    def _reward_to_risk_rule(self) -> str:
        ratio = self.min_reward_to_risk_ratio
        if ratio <= 0:
            return (
                "- No hay ratio riesgo/beneficio mínimo configurado. Aun así, si propones "
                "BUY o SELL, define stop_loss y take_profit técnicos, coherentes y con "
                "distancia suficiente para cubrir costes."
            )
        return (
            "- Antes de proponer BUY o SELL, verifica la geometría del trade: la distancia\n"
            f"  desde entry_price hasta take_profit debe ser al menos {ratio:g} veces mayor que\n"
            "  la distancia desde entry_price hasta stop_loss. Si los niveles técnicos\n"
            "  disponibles no permiten ese ratio, devuelve HOLD en lugar de forzar el\n"
            f"  trade. Ejemplo: si entry=100 y stop_loss=99 (distancia 1), take_profit\n"
            f"  debe ser >= {100 + ratio:g} para BUY o <= {100 - ratio:g} para SELL."
        )

    @staticmethod
    def _persist_signal(signal: TradeSignal) -> None:
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

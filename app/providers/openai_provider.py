from app.providers.ai_provider import AIProvider, hold_signal, parse_trade_signal
from app.schemas.signal import SignalRequest, TradeSignal


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def generate_signal(self, request: SignalRequest, prompt: str) -> TradeSignal:
        if not self.api_key or self.api_key == "replace_me":
            return hold_signal(request.symbol, "OpenAI API key is not configured.")

        try:
            from openai import AsyncOpenAI
        except ImportError:
            return hold_signal(request.symbol, "openai package is not installed.")

        try:
            client = AsyncOpenAI(api_key=self.api_key)
            response = await client.responses.create(
                model=self.model,
                input=prompt,
                text={"format": {"type": "json_object"}},
            )
            return parse_trade_signal(response.output_text, request.symbol, request.market_type)
        except Exception as exc:
            return hold_signal(request.symbol, f"OpenAI provider error: {exc}")

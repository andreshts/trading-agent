from app.providers.ai_provider import AIProvider, hold_signal, parse_trade_signal
from app.schemas.signal import SignalRequest, TradeSignal


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def generate_signal(self, request: SignalRequest, prompt: str) -> TradeSignal:
        if not self.api_key or self.api_key == "replace_me":
            return hold_signal(request.symbol, "Gemini API key is not configured.")

        try:
            from google import genai
        except ImportError:
            return hold_signal(request.symbol, "google-genai package is not installed.")

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            return parse_trade_signal(response.text, request.symbol)
        except Exception as exc:
            return hold_signal(request.symbol, f"Gemini provider error: {exc}")


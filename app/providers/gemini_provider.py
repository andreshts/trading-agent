from app.providers.ai_provider import AIProvider, hold_signal, parse_trade_signal
from app.schemas.signal import SignalRequest, TradeSignal


_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "symbol": {"type": "STRING"},
        "action": {"type": "STRING", "enum": ["BUY", "SELL", "HOLD"]},
        "market_type": {"type": "STRING", "enum": ["spot", "futures", "margin"]},
        "intent": {"type": "STRING", "enum": ["open", "close", "reduce"]},
        "position_side": {"type": "STRING", "enum": ["long", "short"], "nullable": True},
        "confidence": {"type": "NUMBER"},
        "entry_price": {"type": "NUMBER", "nullable": True},
        "stop_loss": {"type": "NUMBER", "nullable": True},
        "take_profit": {"type": "NUMBER", "nullable": True},
        "risk_amount": {"type": "NUMBER"},
        "reason": {"type": "STRING"},
    },
    "required": ["symbol", "action", "confidence", "reason"],
}


class GeminiProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        top_p: float = 0.9,
        max_output_tokens: int = 512,
        thinking_budget: int = 0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_output_tokens = max_output_tokens
        # Gemini 2.5 Flash enables "thinking" by default which consumes the
        # output budget before the JSON gets emitted, producing truncated
        # responses. For BUY/SELL/HOLD classification we don't need it, so
        # 0 is the right default. Set to a positive value to opt back in.
        self.thinking_budget = thinking_budget

    async def generate_signal(self, request: SignalRequest, prompt: str) -> TradeSignal:
        if not self.api_key or self.api_key == "replace_me":
            return hold_signal(request.symbol, "Gemini API key is not configured.")

        try:
            from google import genai
        except ImportError:
            return hold_signal(request.symbol, "google-genai package is not installed.")

        try:
            client = genai.Client(api_key=self.api_key)
            config: dict = {
                "response_mime_type": "application/json",
                "response_schema": _RESPONSE_SCHEMA,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "max_output_tokens": self.max_output_tokens,
            }
            if self.thinking_budget == 0:
                config["thinking_config"] = {"thinking_budget": 0}
            elif self.thinking_budget > 0:
                config["thinking_config"] = {"thinking_budget": self.thinking_budget}
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            return parse_trade_signal(response.text, request.symbol, request.market_type)
        except Exception as exc:
            return hold_signal(request.symbol, f"Gemini provider error: {exc}")

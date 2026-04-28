from app.providers.mock_provider import MockAIProvider
from app.schemas.signal import SignalRequest
from app.services.ai_signal_service import AISignalService


def _request() -> SignalRequest:
    return SignalRequest(
        symbol="BTCUSDT",
        timeframe="15M",
        market_context="Datos de mercado calculados desde Binance.",
    )


def test_prompt_uses_configured_reward_to_risk_ratio() -> None:
    service = AISignalService(provider=MockAIProvider(), min_reward_to_risk_ratio=2.0)

    prompt = service.build_prompt(_request())

    assert "al menos 2 veces" in prompt
    assert "take_profit\n  debe ser >= 102" in prompt
    assert "1.5 veces" not in prompt


def test_prompt_disables_fixed_reward_to_risk_rule_when_config_is_zero() -> None:
    service = AISignalService(provider=MockAIProvider(), min_reward_to_risk_ratio=0.0)

    prompt = service.build_prompt(_request())

    assert "No hay ratio riesgo/beneficio mínimo configurado" in prompt
    assert "1.5 veces" not in prompt

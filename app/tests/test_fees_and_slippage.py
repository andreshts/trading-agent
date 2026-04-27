import pytest

from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.services.kill_switch import KillSwitchService
from app.services.paper_trading import PaperTradingExecutor
from app.services.risk_manager import RiskManager


def _signal(**overrides) -> TradeSignal:
    data = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "confidence": 0.72,
        "entry_price": 64200,
        "stop_loss": 62800,
        "take_profit": 67000,
        "risk_amount": 0,
        "reason": "Valid setup.",
    }
    data.update(overrides)
    return TradeSignal(**data)


def _account(**overrides) -> AccountState:
    data = {
        "equity": 1000,
        "daily_loss": 0,
        "weekly_loss": 0,
        "trades_today": 0,
        "trading_enabled": True,
    }
    data.update(overrides)
    return AccountState(**data)


def _manager(**kwargs) -> RiskManager:
    base = {
        "max_daily_loss": 30,
        "max_weekly_loss": 80,
        "max_trades_per_day": 5,
        "max_risk_per_trade_percent": 1,
        "min_confidence": 0.55,
        "kill_switch": KillSwitchService(enabled=True),
        "default_order_quantity": 0.001,
        "taker_fee_percent": 0.1,
        "slippage_assumption_percent": 0.05,
        "min_reward_to_risk_ratio": 1.5,
    }
    base.update(kwargs)
    base["kill_switch"].deactivate()
    return RiskManager(**base)


def test_risk_amount_includes_round_trip_fees_and_slippage() -> None:
    # qty 0.001, entry 64200, stop 62800.
    # Price risk = 1.4
    # Fee = (64200 + 62800) * 0.001 * 0.001 = 0.127
    # Slippage = (64200 + 62800) * 0.001 * 0.0005 = 0.0635
    # Expected total = 1.4 + 0.127 + 0.0635 = 1.5905
    decision = _manager().validate_trade(_signal(), _account())
    assert decision.approved is True
    assert decision.risk_amount == pytest.approx(1.5905)


def test_rejects_when_reward_to_risk_below_minimum_after_fees() -> None:
    # Take-profit only 1.5x the stop distance gross, but fees eat into reward
    # while inflating risk, so net R:R falls below 1.5.
    decision = _manager().validate_trade(
        _signal(entry_price=64200, stop_loss=62800, take_profit=64900),
        _account(),
    )
    assert decision.approved is False
    assert "R:R" in decision.reason


def test_accepts_when_reward_clearly_above_minimum() -> None:
    decision = _manager().validate_trade(
        _signal(entry_price=64200, stop_loss=63800, take_profit=66000),
        _account(),
    )
    assert decision.approved is True


def test_rejects_when_take_profit_does_not_cover_fees() -> None:
    # Tiny reward window — fees eat all of it.
    decision = _manager().validate_trade(
        _signal(entry_price=64200, stop_loss=63000, take_profit=64210),
        _account(),
    )
    assert decision.approved is False
    assert "comisiones" in decision.reason or "R:R" in decision.reason


def test_rr_check_disabled_when_min_ratio_zero() -> None:
    decision = _manager(min_reward_to_risk_ratio=0).validate_trade(
        _signal(entry_price=64200, stop_loss=62800, take_profit=64210),
        _account(),
    )
    # With R:R disabled, only the price-coherence and risk-cap rules apply.
    assert decision.approved is True


def test_paper_close_subtracts_round_trip_costs_from_pnl() -> None:
    executor = PaperTradingExecutor(
        default_order_quantity=0.001,
        taker_fee_percent=0.1,
        slippage_assumption_percent=0.05,
    )
    opened = executor.execute(_signal())
    closed = executor.close_position(opened.id, exit_price=65200, exit_reason="tp")
    # Gross PnL = (65200 - 64200) * 0.001 = 1.0
    # Cost = (64200 + 65200) * 0.001 * (0.001 + 0.0005) = 0.1941
    # Net = 0.8059
    assert closed.realized_pnl == pytest.approx(0.8059, abs=1e-4)


def test_paper_unrealized_pnl_subtracts_round_trip_costs() -> None:
    executor = PaperTradingExecutor(
        default_order_quantity=0.001,
        taker_fee_percent=0.1,
        slippage_assumption_percent=0.05,
    )
    executor.execute(_signal())
    position = executor.list_positions(status="OPEN", limit=1)[0]
    enriched = executor.enrich_unrealized_pnl(position, current_price=65200)
    assert enriched.unrealized_pnl == pytest.approx(0.8059, abs=1e-4)


def test_paper_executor_with_zero_fees_matches_legacy_behavior() -> None:
    executor = PaperTradingExecutor(default_order_quantity=0.001)
    opened = executor.execute(_signal())
    closed = executor.close_position(opened.id, exit_price=65200, exit_reason="tp")
    assert closed.realized_pnl == pytest.approx(1.0)

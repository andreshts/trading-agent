import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_paper_executor, get_risk_manager
from app.core.config import get_settings
from app.main import app
from app.services.runtime_config import RuntimeConfigStore, get_runtime_config_store


@pytest.fixture
def isolated_store(tmp_path: Path):
    """Replace the cached store with one that points at a tmp file."""
    store = RuntimeConfigStore(tmp_path / "runtime_overrides.json")
    app.dependency_overrides[get_runtime_config_store] = lambda: store
    # Also reset cached settings field values that previous tests may have mutated.
    settings = get_settings()
    fresh_defaults = type(settings)()
    for key in (
        "max_risk_per_trade_percent",
        "min_confidence",
        "max_signal_price_deviation_percent",
        "taker_fee_percent",
        "slippage_assumption_percent",
        "min_reward_to_risk_ratio",
        "max_daily_loss",
        "max_weekly_loss",
        "max_trades_per_day",
        "default_order_quantity",
    ):
        setattr(settings, key, getattr(fresh_defaults, key))
    yield store
    app.dependency_overrides.pop(get_runtime_config_store, None)
    # Restore defaults again so unrelated tests aren't affected.
    for key in (
        "max_risk_per_trade_percent",
        "min_confidence",
        "max_signal_price_deviation_percent",
        "taker_fee_percent",
        "slippage_assumption_percent",
        "min_reward_to_risk_ratio",
        "max_daily_loss",
        "max_weekly_loss",
        "max_trades_per_day",
        "default_order_quantity",
    ):
        setattr(settings, key, getattr(fresh_defaults, key))


client = TestClient(app)


def test_get_risk_config_returns_current_values(isolated_store) -> None:
    response = client.get("/system/risk-config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["min_confidence"] == 0.55
    assert payload["min_reward_to_risk_ratio"] == 1.5
    assert payload["taker_fee_percent"] == 0.1


def test_post_risk_config_updates_settings_and_persists(isolated_store) -> None:
    response = client.post(
        "/system/risk-config",
        json={"min_confidence": 0.4, "min_reward_to_risk_ratio": 1.0},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["min_confidence"] == 0.4
    assert payload["min_reward_to_risk_ratio"] == 1.0
    # Saved to disk
    on_disk = json.loads(isolated_store.path.read_text())
    assert on_disk["min_confidence"] == 0.4
    assert on_disk["min_reward_to_risk_ratio"] == 1.0


def test_post_risk_config_picked_up_by_risk_manager(isolated_store) -> None:
    client.post(
        "/system/risk-config",
        json={"min_reward_to_risk_ratio": 0},
    )
    rm = get_risk_manager()
    assert rm.min_reward_to_risk_ratio == 0


def test_post_risk_config_picked_up_by_paper_executor(isolated_store) -> None:
    client.post(
        "/system/risk-config",
        json={"taker_fee_percent": 0.25, "slippage_assumption_percent": 0.1},
    )
    executor = get_paper_executor()
    assert executor.taker_fee_percent == 0.25
    assert executor.slippage_assumption_percent == 0.1


def test_post_risk_config_rejects_negative_values(isolated_store) -> None:
    response = client.post(
        "/system/risk-config",
        json={"min_confidence": -0.1},
    )
    assert response.status_code == 422


def test_post_risk_config_rejects_unknown_keys(isolated_store) -> None:
    # Unknown keys silently ignored at schema level (Pydantic strips them by default,
    # but if they slipped through, the store also whitelists). Update with only an
    # unknown key returns the unchanged config.
    response = client.post("/system/risk-config", json={"execution_mode": "binance_live"})
    assert response.status_code == 200
    payload = response.json()
    # Settings.execution_mode is not in the risk config schema, so it must not appear.
    assert "execution_mode" not in payload


def test_reset_risk_config_clears_overrides(isolated_store) -> None:
    client.post("/system/risk-config", json={"min_confidence": 0.4})
    assert isolated_store.path.exists()
    response = client.post("/system/risk-config/reset")
    assert response.status_code == 200
    assert not isolated_store.path.exists()
    payload = response.json()
    assert payload["min_confidence"] == 0.55  # back to default


def test_partial_update_does_not_clobber_other_fields(isolated_store) -> None:
    client.post("/system/risk-config", json={"min_confidence": 0.4})
    client.post("/system/risk-config", json={"taker_fee_percent": 0.2})
    final = client.get("/system/risk-config").json()
    assert final["min_confidence"] == 0.4
    assert final["taker_fee_percent"] == 0.2


def test_overrides_apply_on_settings_load(isolated_store) -> None:
    isolated_store.path.write_text(
        json.dumps({"min_confidence": 0.3, "min_reward_to_risk_ratio": 0.5})
    )
    settings = get_settings()
    isolated_store.apply_to(settings)
    assert settings.min_confidence == 0.3
    assert settings.min_reward_to_risk_ratio == 0.5

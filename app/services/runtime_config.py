"""Runtime overrides for risk-tunable settings.

Lets the operator change knobs (R:R, fees, daily loss, etc.) from the dashboard
without a server restart. Overrides are persisted to disk so they survive
restarts; on boot we apply them to the cached Settings instance, and per-request
RiskManager / PaperExecutor pick the new values up because they read from
``get_settings()`` each time.

Only a whitelisted set of keys can be modified — execution mode, API keys, DB
URL and other invariants stay locked in the env file.
"""

from __future__ import annotations

import json
import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)


ALLOWED_KEYS: frozenset[str] = frozenset(
    {
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
    }
)


class RuntimeConfigStore:
    """File-backed store for runtime risk overrides."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read runtime overrides at %s; ignoring.", self.path)
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k in ALLOWED_KEYS}

    def apply_to(self, settings: Settings) -> dict[str, Any]:
        overrides = self.load()
        for key, value in overrides.items():
            try:
                setattr(settings, key, value)
            except Exception:
                logger.exception("Failed to apply runtime override %s=%r", key, value)
        return overrides

    def update(self, settings: Settings, partial: dict[str, Any]) -> dict[str, Any]:
        """Validate via Settings, mutate the cached instance, persist to disk.

        Settings is a Pydantic BaseSettings so model_copy + re-instantiation
        triggers all field validators and the production-invariants validator
        before we accept the change.
        """
        cleaned = {k: v for k, v in partial.items() if k in ALLOWED_KEYS and v is not None}
        if not cleaned:
            return self.load()

        # Build a candidate config and let Pydantic validate the whole shape.
        candidate = settings.model_dump()
        candidate.update(cleaned)
        # Raises ValidationError if any field is out of range or a model_validator fails.
        Settings(**candidate)

        with self._lock:
            for key, value in cleaned.items():
                setattr(settings, key, value)
            existing = self.load()
            existing.update(cleaned)
            self.path.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
            return existing

    def clear(self, settings: Settings) -> dict[str, Any]:
        """Reset all overrides — restore the values that came from env/defaults."""
        with self._lock:
            if self.path.exists():
                self.path.unlink()
        # Restore by reading env defaults via a fresh Settings (bypasses cache).
        fresh = Settings()
        for key in ALLOWED_KEYS:
            try:
                setattr(settings, key, getattr(fresh, key))
            except Exception:
                logger.exception("Failed to reset %s", key)
        return {}


def _default_path() -> Path:
    return Path("runtime_overrides.json")


@lru_cache
def get_runtime_config_store() -> RuntimeConfigStore:
    return RuntimeConfigStore(_default_path())

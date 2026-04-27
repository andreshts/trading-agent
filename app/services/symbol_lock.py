import asyncio
import threading


class SymbolLockRegistry:
    """Registry of asyncio.Lock per symbol to serialize the
    has_open_position -> validate -> execute -> register pipeline.

    Without this, two concurrent ticks on the same symbol can both pass the
    "no open position" check before either inserts, opening duplicate
    positions and double-counting against max_trades_per_day.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = threading.Lock()

    def get(self, symbol: str) -> asyncio.Lock:
        key = symbol.upper()
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock


_registry = SymbolLockRegistry()


def get_symbol_lock_registry() -> SymbolLockRegistry:
    return _registry

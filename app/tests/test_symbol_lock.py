import asyncio

from app.services.symbol_lock import SymbolLockRegistry


def test_same_symbol_returns_same_lock() -> None:
    reg = SymbolLockRegistry()

    async def get_locks() -> tuple:
        return reg.get("btcusdt"), reg.get("BTCUSDT")

    a, b = asyncio.run(get_locks())
    assert a is b


def test_different_symbols_get_different_locks() -> None:
    reg = SymbolLockRegistry()

    async def get_locks() -> tuple:
        return reg.get("BTCUSDT"), reg.get("ETHUSDT")

    a, b = asyncio.run(get_locks())
    assert a is not b


def test_lock_serializes_concurrent_critical_sections() -> None:
    reg = SymbolLockRegistry()
    order: list[str] = []

    async def section(tag: str, hold: float) -> None:
        async with reg.get("BTCUSDT"):
            order.append(f"start:{tag}")
            await asyncio.sleep(hold)
            order.append(f"end:{tag}")

    async def main() -> None:
        await asyncio.gather(section("a", 0.05), section("b", 0.01))

    asyncio.run(main())

    assert order in (
        ["start:a", "end:a", "start:b", "end:b"],
        ["start:b", "end:b", "start:a", "end:a"],
    )

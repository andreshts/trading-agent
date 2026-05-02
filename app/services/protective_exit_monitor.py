import asyncio
from dataclasses import dataclass, field

from app.schemas.trade import PaperPosition
from app.services.market_service import MarketService
from app.services.paper_trading import PaperTradingExecutor
from app.services.symbol_lock import get_symbol_lock_registry
from app.services.system_state import SystemStateService


@dataclass
class ProtectiveExitEvaluation:
    prices: dict[str, float] = field(default_factory=dict)
    closed_positions: list[PaperPosition] = field(default_factory=list)


async def evaluate_protective_exits(
    executor: PaperTradingExecutor,
    market_service: MarketService,
    system_state: SystemStateService,
    limit: int = 200,
    symbols: list[str] | set[str] | None = None,
    fallback_prices: dict[str, float] | None = None,
    use_symbol_locks: bool = True,
) -> ProtectiveExitEvaluation:
    symbol_filter = {symbol.upper() for symbol in symbols} if symbols else None
    fallback_prices = {symbol.upper(): price for symbol, price in (fallback_prices or {}).items()}
    positions = await asyncio.to_thread(executor.list_positions, "OPEN", limit)
    by_symbol: dict[str, list[PaperPosition]] = {}
    for position in positions:
        symbol = position.symbol.upper()
        if symbol_filter is not None and symbol not in symbol_filter:
            continue
        by_symbol.setdefault(symbol, []).append(position)

    result = ProtectiveExitEvaluation()
    locks = get_symbol_lock_registry()
    for symbol, symbol_positions in by_symbol.items():
        if not symbol_positions:
            continue
        reference_action = symbol_positions[0].action
        price = await market_service.get_exit_reference_price(symbol, reference_action)
        if price is None:
            price = fallback_prices.get(symbol)
            if price is None:
                continue

        result.prices[symbol] = price
        if use_symbol_locks:
            async with locks.get(symbol):
                closed = await asyncio.to_thread(executor.evaluate_open_positions, symbol, price)
        else:
            closed = await asyncio.to_thread(executor.evaluate_open_positions, symbol, price)

        for position in closed:
            system_state.register_closed_position(position.realized_pnl or 0)
        result.closed_positions.extend(closed)

    return result

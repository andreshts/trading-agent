import argparse
import asyncio
from datetime import datetime, timezone

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Loop externo para ejecutar /agent/autonomous/tick periodicamente."
    )
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--symbols", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1H")
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--open-new-position", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


async def run_tick(
    client: httpx.AsyncClient,
    api_base_url: str,
    symbol: str,
    timeframe: str,
    open_new_position: bool,
) -> None:
    market_context = (
        f"Tick autonomo para {symbol}. "
        "Usa precio de mercado del backend y evalua stop_loss/take_profit."
    )
    response = await client.post(
        f"{api_base_url.rstrip('/')}/agent/autonomous/tick",
        json={
            "symbol": symbol,
            "timeframe": timeframe,
            "market_context": market_context,
            "open_new_position": open_new_position,
        },
    )
    response.raise_for_status()
    payload = response.json()
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] {symbol}: {payload['reason']}")


async def main() -> None:
    args = parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    if not symbols:
        raise SystemExit("Debes indicar al menos un simbolo.")

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            for symbol in symbols:
                try:
                    await run_tick(
                        client=client,
                        api_base_url=args.api_base_url,
                        symbol=symbol,
                        timeframe=args.timeframe,
                        open_new_position=args.open_new_position,
                    )
                except httpx.HTTPError as exc:
                    timestamp = datetime.now(timezone.utc).isoformat()
                    print(f"[{timestamp}] {symbol}: error llamando al API: {exc}")

            if args.once:
                break
            await asyncio.sleep(args.interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())

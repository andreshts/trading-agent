import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode

import httpx

from app.db.models import PaperPosition
from app.db.session import SessionLocal
from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.schemas.trade import PaperPosition as PaperPositionSchema
from app.schemas.trade import PaperTradeResult
from app.services.audit_logger import AuditLogger
from app.services.paper_trading import PaperTradingExecutor


class BinanceSpotClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str,
        recv_window: int = 5000,
        timeout_seconds: float = 10,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(
            self.api_key
            and self.api_secret
            and self.api_key != "replace_me"
            and self.api_secret != "replace_me"
        )

    def get_account(self) -> dict:
        return self._signed_request("GET", "/api/v3/account")

    def get_order(self, symbol: str, client_order_id: str) -> dict:
        return self._signed_request(
            "GET",
            "/api/v3/order",
            {
                "symbol": symbol.upper(),
                "origClientOrderId": client_order_id,
            },
        )

    def create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        test_order: bool = False,
        client_order_id: str | None = None,
    ) -> dict:
        path = "/api/v3/order/test" if test_order else "/api/v3/order"
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": self._format_decimal(quantity),
            "newOrderRespType": "FULL",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._signed_request("POST", path, params)

    def create_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
        test_order: bool = False,
        client_order_id: str | None = None,
    ) -> dict:
        path = "/api/v3/order/test" if test_order else "/api/v3/order"
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "LIMIT",
            "timeInForce": time_in_force.upper(),
            "quantity": self._format_decimal(quantity),
            "price": self._format_decimal(price),
            "newOrderRespType": "FULL",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._signed_request(
            "POST",
            path,
            params,
        )

    def _signed_request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ) -> dict:
        if not self.configured:
            raise RuntimeError("Binance API key/secret are not configured.")

        query_params = {
            **(params or {}),
            "recvWindow": self.recv_window,
            "timestamp": int(time.time() * 1000),
        }
        query = urlencode(query_params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_query = f"{query}&signature={signature}"

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.request(
                method,
                f"{self.base_url}{path}?{signed_query}",
                headers={"X-MBX-APIKEY": self.api_key},
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Binance error {response.status_code}: {response.text}")
            return response.json() if response.text else {}

    @staticmethod
    def _format_decimal(value: float) -> str:
        return f"{value:.10f}".rstrip("0").rstrip(".")


class BinanceSpotExecutor(PaperTradingExecutor):
    def __init__(
        self,
        client: BinanceSpotClient,
        execution_mode: str,
        real_trading_enabled: bool,
        default_order_quantity: float,
        allowed_symbols: list[str],
        max_notional_per_order: float,
        order_type: str = "market",
        limit_time_in_force: str = "IOC",
        use_test_order_endpoint: bool = False,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        super().__init__(
            paper_trading_enabled=True,
            real_trading_enabled=False,
            default_order_quantity=default_order_quantity,
            audit_logger=audit_logger,
        )
        self.client = client
        self.execution_mode = execution_mode
        self.real_trading_enabled = real_trading_enabled
        self.allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self.max_notional_per_order = max_notional_per_order
        self.order_type = order_type.lower()
        self.limit_time_in_force = limit_time_in_force.upper()
        self.use_test_order_endpoint = use_test_order_endpoint

    def execute(
        self,
        signal: TradeSignal,
        quantity: float | None = None,
        risk_amount: float | None = None,
    ) -> PaperTradeResult:
        self._ensure_mode_allowed()
        self._validate_symbol(signal.symbol)

        if signal.action == "HOLD":
            raise ValueError("HOLD signals cannot be executed.")
        if signal.action != "BUY":
            raise ValueError("Binance Spot executor only opens BUY positions in this phase.")
        if signal.entry_price is None or signal.stop_loss is None:
            raise ValueError("Executable signals require entry_price and stop_loss.")

        trade_quantity = quantity or self.default_order_quantity
        notional = signal.entry_price * trade_quantity
        if notional > self.max_notional_per_order:
            raise ValueError(
                f"Order notional {notional:g} exceeds MAX_NOTIONAL_PER_ORDER "
                f"{self.max_notional_per_order:g}."
            )

        order = self._place_order_with_reconciliation(
            symbol=signal.symbol,
            side="BUY",
            quantity=trade_quantity,
            price=signal.entry_price,
        )
        fill_price = self._average_fill_price(order) or signal.entry_price
        executed_qty = self._executed_quantity(order)
        if executed_qty is None:
            if not self.use_test_order_endpoint:
                raise RuntimeError("Binance order response did not include executed quantity.")
            executed_qty = trade_quantity
        if executed_qty <= 0:
            raise RuntimeError("Binance order was not filled.")
        stop_loss, take_profit = self._protective_prices_from_fill(signal, fill_price)
        calculated_risk = abs(fill_price - stop_loss) * executed_qty

        with SessionLocal() as db:
            position = PaperPosition(
                symbol=signal.symbol,
                action="BUY",
                status="OPEN",
                quantity=executed_qty,
                entry_price=fill_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=calculated_risk,
                payload={
                    **signal.model_dump(mode="json"),
                    "execution_mode": self.execution_mode,
                    "original_entry_price": signal.entry_price,
                    "original_stop_loss": signal.stop_loss,
                    "original_take_profit": signal.take_profit,
                    "exchange_order_id": self._order_id(order),
                    "exchange_status": order.get("status", "TEST_ORDER"),
                    "exchange_payload": order,
                },
            )
            db.add(position)
            db.commit()
            db.refresh(position)

        result = PaperTradeResult(
            id=position.id,
            symbol=signal.symbol,
            action="BUY",
            quantity=executed_qty,
            entry_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=calculated_risk,
            execution_mode=self.execution_mode,
            exchange_order_id=self._order_id(order),
            exchange_status=order.get("status", "TEST_ORDER"),
        )
        if self.audit_logger:
            self.audit_logger.record("binance_spot_trade", result.model_dump(mode="json"))
        return result

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str = "manual",
    ) -> PaperPositionSchema:
        self._ensure_mode_allowed()

        with SessionLocal() as db:
            position = db.get(PaperPosition, position_id)
            if position is None:
                raise ValueError("Position not found.")
            if position.status != "OPEN":
                raise ValueError("Position is not open.")
            self._validate_symbol(position.symbol)

        order = self._place_order_with_reconciliation(
            symbol=position.symbol,
            side="SELL",
            quantity=position.quantity,
            price=exit_price,
        )
        actual_exit_price = self._average_fill_price(order) or exit_price

        schema = super().close_position(
            position_id=position_id,
            exit_price=actual_exit_price,
            exit_reason=exit_reason,
        )

        with SessionLocal() as db:
            position = db.get(PaperPosition, position_id)
            if position is not None:
                payload = {**(position.payload or {})}
                payload.update(
                    {
                        "close_exchange_order_id": self._order_id(order),
                        "close_exchange_status": order.get("status", "TEST_ORDER"),
                        "close_exchange_payload": order,
                    }
                )
                position.payload = payload
                db.commit()
                schema = self._with_payload_metadata(schema, payload)

        if self.audit_logger:
            self.audit_logger.record(
                "binance_spot_position_closed",
                schema.model_dump(mode="json"),
            )
        return schema

    def get_account_state(self, fallback: AccountState) -> AccountState:
        account = self.client.get_account()
        usdt_equity = self._asset_total(account, "USDT")
        if usdt_equity <= 0:
            return fallback
        peak_equity = fallback.peak_equity if fallback.peak_equity is not None else fallback.equity
        return fallback.model_copy(update={"equity": usdt_equity, "peak_equity": max(peak_equity, usdt_equity)})

    def _place_order_with_reconciliation(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
    ) -> dict:
        client_order_id = self._new_client_order_id(side)

        try:
            if self.order_type == "limit":
                return self.client.create_limit_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    time_in_force=self.limit_time_in_force,
                    test_order=self.use_test_order_endpoint,
                    client_order_id=client_order_id,
                )
            return self.client.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                test_order=self.use_test_order_endpoint,
                client_order_id=client_order_id,
            )
        except Exception as exc:
            if self.use_test_order_endpoint:
                raise
            try:
                order = self.client.get_order(symbol=symbol, client_order_id=client_order_id)
            except Exception:
                raise RuntimeError(
                    f"Binance order request failed and reconciliation did not find order {client_order_id}: {exc}"
                ) from exc
            if self.audit_logger:
                self.audit_logger.record(
                    "binance_order_reconciled_after_error",
                    {"symbol": symbol, "side": side, "client_order_id": client_order_id, "order": order},
                )
            return order

    def _ensure_mode_allowed(self) -> None:
        if self.execution_mode == "binance_live" and not self.real_trading_enabled:
            raise RuntimeError("Binance live trading requires REAL_TRADING_ENABLED=true.")

    def _validate_symbol(self, symbol: str) -> None:
        if symbol.upper() not in self.allowed_symbols:
            raise ValueError(f"Symbol {symbol.upper()} is not in ALLOWED_SYMBOLS.")

    @staticmethod
    def _new_client_order_id(side: str) -> str:
        return f"ocx-{side.lower()}-{secrets.token_hex(8)}"

    @staticmethod
    def _asset_total(account: dict, asset: str) -> float:
        for balance in account.get("balances", []):
            if balance.get("asset") != asset:
                continue
            try:
                return float(balance.get("free") or 0) + float(balance.get("locked") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    @staticmethod
    def _protective_prices_from_fill(signal: TradeSignal, fill_price: float) -> tuple[float, float | None]:
        if signal.entry_price is None or signal.stop_loss is None:
            raise ValueError("Executable signals require entry_price and stop_loss.")

        if signal.action != "BUY":
            raise ValueError("Only BUY protective price recalculation is supported.")

        stop_distance_percent = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
        stop_loss = fill_price * (1 - stop_distance_percent)

        take_profit = None
        if signal.take_profit is not None:
            take_profit_distance_percent = abs(signal.take_profit - signal.entry_price) / signal.entry_price
            take_profit = fill_price * (1 + take_profit_distance_percent)

        return stop_loss, take_profit

    @staticmethod
    def _order_id(order: dict) -> str | None:
        value = order.get("orderId")
        return str(value) if value is not None else None

    @staticmethod
    def _executed_quantity(order: dict) -> float | None:
        try:
            if "executedQty" not in order:
                return None
            return float(order.get("executedQty") or 0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _average_fill_price(order: dict) -> float | None:
        fills = order.get("fills") or []
        total_qty = 0.0
        total_quote = 0.0
        for fill in fills:
            try:
                price = float(fill["price"])
                qty = float(fill["qty"])
            except (KeyError, TypeError, ValueError):
                continue
            total_qty += qty
            total_quote += price * qty
        if total_qty > 0:
            return total_quote / total_qty

        try:
            executed_qty = float(order.get("executedQty") or 0)
            quote_qty = float(order.get("cummulativeQuoteQty") or 0)
        except (TypeError, ValueError):
            return None
        if executed_qty > 0 and quote_qty > 0:
            return quote_qty / executed_qty
        return None

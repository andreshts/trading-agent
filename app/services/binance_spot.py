import hashlib
import hmac
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import httpx
from sqlalchemy import select

from app.db.models import ExchangeOrder, OrderIntent, PaperPosition
from app.db.session import SessionLocal
from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.schemas.trade import PaperPosition as PaperPositionSchema
from app.schemas.trade import PaperTradeResult
from app.services.audit_logger import AuditLogger
from app.services.binance_market_stream import get_market_stream
from app.services.paper_trading import PaperTradingExecutor


class BinanceSpotClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str,
        recv_window: int = 5000,
        timeout_seconds: float = 10,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._symbol_filters_cache: dict[str, dict] = {}

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

    def get_symbol_filters(self, symbol: str) -> dict:
        normalized_symbol = symbol.upper()
        cached = self._symbol_filters_cache.get(normalized_symbol)
        if cached is not None:
            return cached

        response = self._request_with_retries(
            "GET",
            f"{self.base_url}/api/v3/exchangeInfo?{urlencode({'symbol': normalized_symbol})}",
        )
        symbols = response.get("symbols") or []
        if not symbols:
            raise RuntimeError(f"Binance did not return exchange filters for {normalized_symbol}.")
        filters = {
            item.get("filterType"): item
            for item in symbols[0].get("filters", [])
            if item.get("filterType")
        }
        self._symbol_filters_cache[normalized_symbol] = filters
        return filters

    def create_listen_key(self) -> str:
        response = self._api_key_request("POST", "/api/v3/userDataStream")
        listen_key = response.get("listenKey")
        if not listen_key:
            raise RuntimeError("Binance did not return a listenKey.")
        return listen_key

    def keepalive_listen_key(self, listen_key: str) -> None:
        self._api_key_request("PUT", "/api/v3/userDataStream", {"listenKey": listen_key})

    def close_listen_key(self, listen_key: str) -> None:
        self._api_key_request("DELETE", "/api/v3/userDataStream", {"listenKey": listen_key})

    def get_order(self, symbol: str, client_order_id: str) -> dict:
        return self._signed_request(
            "GET",
            "/api/v3/order",
            {
                "symbol": symbol.upper(),
                "origClientOrderId": client_order_id,
            },
        )

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        params: dict = {}
        if symbol:
            params["symbol"] = symbol.upper()
        result = self._signed_request("GET", "/api/v3/openOrders", params)
        if isinstance(result, list):
            return result
        return []

    def get_my_trades(
        self,
        symbol: str,
        start_time_ms: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        params: dict = {"symbol": symbol.upper(), "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        result = self._signed_request("GET", "/api/v3/myTrades", params)
        if isinstance(result, list):
            return result
        return []

    def get_order_list(self, order_list_id: str) -> dict:
        return self._signed_request(
            "GET",
            "/api/v3/orderList",
            {"orderListId": order_list_id},
        )

    def cancel_order_list(self, symbol: str, order_list_id: str) -> dict:
        return self._signed_request(
            "DELETE",
            "/api/v3/orderList",
            {
                "symbol": symbol.upper(),
                "orderListId": order_list_id,
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

    def create_oco_sell_order(
        self,
        symbol: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
        stop_limit_time_in_force: str = "GTC",
        test_order: bool = False,
        list_client_order_id: str | None = None,
    ) -> dict:
        path = "/api/v3/orderList/oco"
        params = {
            "symbol": symbol.upper(),
            "side": "SELL",
            "quantity": self._format_decimal(quantity),
            "aboveType": "LIMIT_MAKER",
            "abovePrice": self._format_decimal(take_profit_price),
            "belowType": "STOP_LOSS_LIMIT",
            "belowStopPrice": self._format_decimal(stop_price),
            "belowPrice": self._format_decimal(stop_limit_price),
            "belowTimeInForce": stop_limit_time_in_force,
            "newOrderRespType": "FULL",
        }
        if list_client_order_id:
            params["listClientOrderId"] = list_client_order_id

        if test_order:
            return {"listClientOrderId": list_client_order_id, "listStatusType": "TEST_ORDER"}

        return self._signed_request("POST", path, params)

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

        return self._request_with_retries(method, f"{self.base_url}{path}?{signed_query}")

    def _api_key_request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ) -> dict:
        if not self.configured:
            raise RuntimeError("Binance API key/secret are not configured.")

        query = urlencode(params or {})
        suffix = f"?{query}" if query else ""
        return self._request_with_retries(method, f"{self.base_url}{path}{suffix}")

    def _request_with_retries(self, method: str, url: str) -> dict:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.request(
                        method,
                        url,
                        headers={"X-MBX-APIKEY": self.api_key},
                    )
                if response.status_code < 400:
                    return response.json() if response.text else {}
                if response.status_code not in {418, 429, 500, 502, 503, 504}:
                    raise RuntimeError(f"Binance error {response.status_code}: {response.text}")
                last_error = RuntimeError(f"Binance error {response.status_code}: {response.text}")
            except httpx.HTTPError as exc:
                last_error = exc

            if attempt < self.max_retries:
                time.sleep(self.retry_backoff_seconds * (2**attempt))

        raise RuntimeError(f"Binance request failed after retries: {last_error}")

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
        place_oco_protection: bool = False,
        stop_limit_slippage_percent: float = 0.1,
        use_test_order_endpoint: bool = False,
        max_signal_price_deviation_percent: float = 0.5,
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
        self.place_oco_protection = place_oco_protection
        self.stop_limit_slippage_percent = stop_limit_slippage_percent
        self.use_test_order_endpoint = use_test_order_endpoint
        self.max_signal_price_deviation_percent = max_signal_price_deviation_percent

    def execute(
        self,
        signal: TradeSignal,
        quantity: float | None = None,
        risk_amount: float | None = None,
        intent_id: str | None = None,
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

        entry_intent_id = intent_id or self._new_intent_id("entry")
        existing = self._existing_position_for_intent(entry_intent_id)
        if existing is not None:
            return existing

        self._reject_if_market_moved_against_signal(signal)

        order = self._place_order_with_reconciliation(
            symbol=signal.symbol,
            side="BUY",
            quantity=trade_quantity,
            price=signal.entry_price,
            intent_id=entry_intent_id,
            role="entry",
        )
        entry_order_record_id = self._persist_exchange_order(
            order=order,
            role="entry",
            symbol=signal.symbol,
            side="BUY",
            order_type=self.order_type.upper(),
            requested_quantity=trade_quantity,
            requested_price=signal.entry_price,
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
        if self.place_oco_protection:
            stop_loss, take_profit = self._round_protective_prices_for_exchange(
                signal.symbol,
                stop_loss,
                take_profit,
            )
        calculated_risk = abs(fill_price - stop_loss) * executed_qty
        protective_order = None
        protective_order_record_id = None

        if self.place_oco_protection:
            if take_profit is None:
                self._emergency_close_after_unprotected_entry(signal.symbol, executed_qty)
                raise RuntimeError("OCO protection requires take_profit.")
            try:
                protective_order = self._place_oco_protection(
                    symbol=signal.symbol,
                    quantity=executed_qty,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    intent_id=f"{entry_intent_id}-oco",
                )
                protective_order_record_id = self._persist_exchange_order(
                    order=protective_order,
                    role="protection",
                    symbol=signal.symbol,
                    side="SELL",
                    order_type="OCO",
                    requested_quantity=executed_qty,
                    requested_price=take_profit,
                )
            except Exception as exc:
                self._audit_oco_protection_failed(
                    symbol=signal.symbol,
                    quantity=executed_qty,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    error=exc,
                )
                self._emergency_close_after_unprotected_entry(signal.symbol, executed_qty)
                raise RuntimeError(f"OCO protection failed; emergency close sent: {exc}") from exc

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
                    "protective_order_list_id": self._order_list_id(protective_order),
                    "protective_order_status": self._order_list_status(protective_order),
                    "protective_order_payload": protective_order,
                },
            )
            db.add(position)
            db.commit()
            db.refresh(position)
            self._attach_exchange_order_to_position(entry_order_record_id, position.id)
            self._attach_exchange_order_to_position(protective_order_record_id, position.id)
            self._attach_intent_to_position(entry_intent_id, position.id)

        result = PaperTradeResult(
            id=position.id,
            symbol=signal.symbol,
            action="BUY",
            market_type="spot",
            intent=signal.intent,
            position_side="long",
            quantity=executed_qty,
            entry_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=calculated_risk,
            execution_mode=self.execution_mode,
            exchange_order_id=self._order_id(order),
            exchange_status=order.get("status", "TEST_ORDER"),
            protective_order_list_id=self._order_list_id(protective_order),
        )
        if self.audit_logger:
            self.audit_logger.record("binance_spot_trade", result.model_dump(mode="json"))
        return result

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str = "manual",
        intent_id: str | None = None,
    ) -> PaperPositionSchema:
        self._ensure_mode_allowed()

        with SessionLocal() as db:
            position = db.get(PaperPosition, position_id)
            if position is None:
                raise ValueError("Position not found.")
            if position.status != "OPEN":
                raise ValueError("Position is not open.")
            self._validate_symbol(position.symbol)
            symbol = position.symbol
            trade_quantity = position.quantity
            protective_order_list_id = (position.payload or {}).get("protective_order_list_id")

        if protective_order_list_id:
            cancellation = self.client.cancel_order_list(symbol, protective_order_list_id)
            self._persist_exchange_order(
                order=cancellation,
                role="protection_cancel",
                symbol=symbol,
                side="SELL",
                order_type="OCO_CANCEL",
                position_id=position_id,
                requested_quantity=trade_quantity,
                requested_price=exit_price,
            )

        exit_intent_id = intent_id or self._new_intent_id(f"exit-{position_id}")
        order = self._place_order_with_reconciliation(
            symbol=symbol,
            side="SELL",
            quantity=trade_quantity,
            price=exit_price,
            intent_id=exit_intent_id,
            role="exit",
        )
        self._persist_exchange_order(
            order=order,
            role="exit",
            symbol=symbol,
            side="SELL",
            order_type=self.order_type.upper(),
            position_id=position_id,
            requested_quantity=trade_quantity,
            requested_price=exit_price,
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

    def evaluate_open_positions(
        self,
        symbol: str,
        current_price: float,
    ) -> list[PaperPositionSchema]:
        from sqlalchemy import select

        closed: list[PaperPositionSchema] = []
        with SessionLocal() as db:
            positions = db.scalars(
                select(PaperPosition).where(
                    PaperPosition.symbol == symbol.upper(),
                    PaperPosition.status == "OPEN",
                )
            ).all()

        for position in positions:
            payload = position.payload or {}
            protective_order_list_id = payload.get("protective_order_list_id")
            if protective_order_list_id:
                closed_position = self._sync_oco_position(position, protective_order_list_id)
                if closed_position:
                    closed.append(closed_position)
                continue

            exit_reason: str | None = None
            if position.action == "BUY":
                if current_price <= position.stop_loss:
                    exit_reason = "stop_loss"
                elif position.take_profit is not None and current_price >= position.take_profit:
                    exit_reason = "take_profit"

            if exit_reason:
                closed.append(self.close_position(position.id, current_price, exit_reason))

        return closed

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
        intent_id: str | None = None,
        role: str = "entry",
    ) -> dict:
        intent_id = intent_id or self._new_intent_id(role)
        client_order_id = self._derive_client_order_id(intent_id, side)

        intent = self._get_or_create_intent(
            intent_id=intent_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            role=role,
            order_type=self.order_type.upper(),
            quantity=quantity,
            requested_price=price,
        )

        if intent.status == "FILLED" and intent.payload:
            if self.audit_logger:
                self.audit_logger.record(
                    "binance_intent_replayed",
                    {"intent_id": intent_id, "client_order_id": client_order_id},
                )
            return intent.payload

        if intent.status in {"PENDING", "ACK"} and not self.use_test_order_endpoint:
            try:
                existing_order = self.client.get_order(
                    symbol=symbol, client_order_id=client_order_id
                )
            except Exception:
                existing_order = None
            if existing_order:
                self._mark_intent_filled(intent_id, existing_order)
                if self.audit_logger:
                    self.audit_logger.record(
                        "binance_intent_recovered_pre_send",
                        {
                            "intent_id": intent_id,
                            "client_order_id": client_order_id,
                            "order": existing_order,
                        },
                    )
                return existing_order

        try:
            if self.order_type == "limit":
                order = self.client.create_limit_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    time_in_force=self.limit_time_in_force,
                    test_order=self.use_test_order_endpoint,
                    client_order_id=client_order_id,
                )
            else:
                order = self.client.create_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    test_order=self.use_test_order_endpoint,
                    client_order_id=client_order_id,
                )
            self._mark_intent_filled(intent_id, order)
            return order
        except Exception as exc:
            if self.use_test_order_endpoint:
                self._mark_intent_rejected(intent_id, str(exc))
                raise
            try:
                order = self.client.get_order(symbol=symbol, client_order_id=client_order_id)
            except Exception:
                self._mark_intent_rejected(intent_id, str(exc))
                raise RuntimeError(
                    f"Binance order request failed and reconciliation did not find order {client_order_id}: {exc}"
                ) from exc
            self._mark_intent_filled(intent_id, order)
            if self.audit_logger:
                self.audit_logger.record(
                    "binance_order_reconciled_after_error",
                    {"symbol": symbol, "side": side, "client_order_id": client_order_id, "order": order},
                )
            return order

    def _persist_exchange_order(
        self,
        order: dict | None,
        role: str,
        symbol: str,
        side: str,
        order_type: str,
        position_id: int | None = None,
        requested_quantity: float | None = None,
        requested_price: float | None = None,
    ) -> int | None:
        if order is None:
            return None

        with SessionLocal() as db:
            row = ExchangeOrder(
                position_id=position_id,
                role=role,
                symbol=symbol.upper(),
                side=side.upper(),
                order_type=order_type.upper(),
                status=self._order_status(order),
                exchange_order_id=self._order_id(order),
                client_order_id=self._client_order_id(order),
                order_list_id=self._order_list_id(order),
                quantity=requested_quantity,
                executed_quantity=self._executed_quantity(order),
                price=requested_price,
                average_price=self._average_fill_price(order) or self._filled_exit_price_from_order_list(order),
                payload=order,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

    @staticmethod
    def _attach_exchange_order_to_position(exchange_order_id: int | None, position_id: int) -> None:
        if exchange_order_id is None:
            return
        with SessionLocal() as db:
            row = db.get(ExchangeOrder, exchange_order_id)
            if row is not None:
                row.position_id = position_id
                db.commit()

    def _place_oco_protection(
        self,
        symbol: str,
        quantity: float,
        take_profit: float,
        stop_loss: float,
        intent_id: str | None = None,
    ) -> dict:
        stop_limit_price = stop_loss * (1 - (self.stop_limit_slippage_percent / 100))
        tick_size = self._price_tick_size(symbol)
        if tick_size is not None:
            stop_limit_price = self._round_down_to_step(stop_limit_price, tick_size)
        oco_intent_id = intent_id or self._new_intent_id("oco")
        list_client_order_id = self._derive_client_order_id(oco_intent_id, "OCO")
        return self.client.create_oco_sell_order(
            symbol=symbol,
            quantity=quantity,
            take_profit_price=take_profit,
            stop_price=stop_loss,
            stop_limit_price=stop_limit_price,
            test_order=self.use_test_order_endpoint,
            list_client_order_id=list_client_order_id,
        )

    def _round_protective_prices_for_exchange(
        self,
        symbol: str,
        stop_loss: float,
        take_profit: float | None,
    ) -> tuple[float, float | None]:
        tick_size = self._price_tick_size(symbol)
        if tick_size is None:
            return stop_loss, take_profit
        rounded_stop_loss = self._round_down_to_step(stop_loss, tick_size)
        rounded_take_profit = (
            self._round_down_to_step(take_profit, tick_size)
            if take_profit is not None
            else None
        )
        return rounded_stop_loss, rounded_take_profit

    def _price_tick_size(self, symbol: str) -> float | None:
        try:
            filters = self.client.get_symbol_filters(symbol)
            price_filter = filters.get("PRICE_FILTER") or {}
            tick_size = float(price_filter.get("tickSize") or 0)
        except Exception as exc:
            if self.audit_logger:
                self.audit_logger.record(
                    "binance_symbol_filters_unavailable",
                    {"symbol": symbol.upper(), "error": str(exc)},
                )
            return None
        return tick_size if tick_size > 0 else None

    @staticmethod
    def _round_down_to_step(value: float, step: float) -> float:
        decimal_value = Decimal(str(value))
        decimal_step = Decimal(str(step))
        units = (decimal_value / decimal_step).to_integral_value(rounding=ROUND_DOWN)
        return float(units * decimal_step)

    def _audit_oco_protection_failed(
        self,
        symbol: str,
        quantity: float,
        take_profit: float,
        stop_loss: float,
        error: Exception,
    ) -> None:
        if not self.audit_logger:
            return
        stop_limit_price = stop_loss * (1 - (self.stop_limit_slippage_percent / 100))
        tick_size = self._price_tick_size(symbol)
        if tick_size is not None:
            stop_limit_price = self._round_down_to_step(stop_limit_price, tick_size)
        self.audit_logger.record(
            "binance_oco_protection_failed",
            {
                "symbol": symbol.upper(),
                "quantity": quantity,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "stop_limit_price": stop_limit_price,
                "stop_limit_slippage_percent": self.stop_limit_slippage_percent,
                "error": str(error),
            },
        )

    def _emergency_close_after_unprotected_entry(self, symbol: str, quantity: float) -> None:
        order = self._place_order_with_reconciliation(
            symbol=symbol,
            side="SELL",
            quantity=quantity,
            price=0.0,
        )
        self._persist_exchange_order(
            order=order,
            role="emergency_exit",
            symbol=symbol,
            side="SELL",
            order_type=self.order_type.upper(),
            requested_quantity=quantity,
        )
        if self.audit_logger:
            self.audit_logger.record(
                "binance_emergency_close_unprotected_entry",
                {"symbol": symbol, "quantity": quantity, "order": order},
            )

    def _sync_oco_position(
        self,
        position: PaperPosition,
        order_list_id: str,
    ) -> PaperPositionSchema | None:
        order_list = self.client.get_order_list(order_list_id)
        list_status = order_list.get("listOrderStatus") or order_list.get("listStatusType")

        with SessionLocal() as db:
            current = db.get(PaperPosition, position.id)
            if current is not None:
                payload = {**(current.payload or {})}
                payload.update(
                    {
                        "protective_order_status": list_status,
                        "protective_order_payload": order_list,
                    }
                )
                current.payload = payload
                db.commit()

        if list_status not in {"ALL_DONE", "ALL_DONE_REJECT", "EXECUTED"}:
            return None

        fill_price = self._filled_exit_price_from_order_list(order_list)
        if fill_price is None:
            return None

        self._persist_exchange_order(
            order=order_list,
            role="protection_fill",
            symbol=position.symbol,
            side="SELL",
            order_type="OCO",
            position_id=position.id,
            requested_quantity=position.quantity,
            requested_price=fill_price,
        )
        exit_reason = self._oco_exit_reason(order_list, position, fill_price)
        schema = PaperTradingExecutor.close_position(
            self,
            position_id=position.id,
            exit_price=fill_price,
            exit_reason=exit_reason,
        )
        if self.audit_logger:
            self.audit_logger.record(
                "binance_spot_oco_position_closed",
                schema.model_dump(mode="json"),
            )
        return schema

    def _ensure_mode_allowed(self) -> None:
        if self.execution_mode == "binance_live" and not self.real_trading_enabled:
            raise RuntimeError("Binance live trading requires REAL_TRADING_ENABLED=true.")

    def _validate_symbol(self, symbol: str) -> None:
        if symbol.upper() not in self.allowed_symbols:
            raise ValueError(f"Symbol {symbol.upper()} is not in ALLOWED_SYMBOLS.")

    def _reject_if_market_moved_against_signal(self, signal: TradeSignal) -> None:
        if signal.entry_price is None:
            return
        stream = get_market_stream()
        if stream is None:
            return
        # For BUY we care about the ask we'd actually cross. Fall back to
        # last_price if we don't have a fresh book.
        reference = stream.get_ask(signal.symbol, max_age_seconds=5.0)
        if reference is None:
            reference = stream.get_last_price(signal.symbol, max_age_seconds=5.0)
        if reference is None:
            return
        deviation = abs(signal.entry_price - reference) / reference * 100
        if deviation <= self.max_signal_price_deviation_percent:
            return
        if self.audit_logger:
            self.audit_logger.record(
                "binance_pre_post_price_drift_rejected",
                {
                    "symbol": signal.symbol,
                    "signal_entry_price": signal.entry_price,
                    "live_reference_price": reference,
                    "deviation_percent": deviation,
                    "max_allowed_percent": self.max_signal_price_deviation_percent,
                },
            )
        raise RuntimeError(
            "Pre-POST price re-check rejected: live price drifted "
            f"{deviation:.2f}% > {self.max_signal_price_deviation_percent:g}% "
            f"(signal {signal.entry_price:g} vs market {reference:g})."
        )

    @staticmethod
    def _new_intent_id(role: str) -> str:
        return f"{role}-{uuid.uuid4().hex}"

    @staticmethod
    def _derive_client_order_id(intent_id: str, side: str) -> str:
        digest = hashlib.sha256(f"{intent_id}|{side.upper()}".encode("utf-8")).hexdigest()[:20]
        return f"ocx-{side.lower()[:1]}-{digest}"

    def _existing_position_for_intent(self, intent_id: str) -> PaperTradeResult | None:
        with SessionLocal() as db:
            intent = db.scalars(
                select(OrderIntent).where(OrderIntent.intent_id == intent_id)
            ).first()
            if intent is None or intent.position_id is None:
                return None
            position = db.get(PaperPosition, intent.position_id)
            if position is None:
                return None
            payload = position.payload or {}
            return PaperTradeResult(
                id=position.id,
                symbol=position.symbol,
                action=position.action,
                market_type=payload.get("market_type", "spot"),
                intent=payload.get("intent", "open"),
                position_side=payload.get(
                    "position_side",
                    "long" if position.action == "BUY" else "short",
                ),
                quantity=position.quantity,
                entry_price=position.entry_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                risk_amount=position.risk_amount,
                execution_mode=payload.get("execution_mode", self.execution_mode),
                exchange_order_id=payload.get("exchange_order_id"),
                exchange_status=payload.get("exchange_status"),
                protective_order_list_id=payload.get("protective_order_list_id"),
            )

    def _get_or_create_intent(
        self,
        intent_id: str,
        client_order_id: str,
        symbol: str,
        side: str,
        role: str,
        order_type: str,
        quantity: float,
        requested_price: float | None,
    ) -> OrderIntent:
        with SessionLocal() as db:
            intent = db.scalars(
                select(OrderIntent).where(OrderIntent.intent_id == intent_id)
            ).first()
            if intent is not None:
                return intent
            intent = OrderIntent(
                intent_id=intent_id,
                client_order_id=client_order_id,
                symbol=symbol.upper(),
                side=side.upper(),
                role=role,
                order_type=order_type.upper(),
                quantity=quantity,
                requested_price=requested_price,
                status="PENDING",
                payload={},
            )
            db.add(intent)
            db.commit()
            db.refresh(intent)
            return intent

    def _mark_intent_filled(self, intent_id: str, order: dict) -> None:
        with SessionLocal() as db:
            intent = db.scalars(
                select(OrderIntent).where(OrderIntent.intent_id == intent_id)
            ).first()
            if intent is None:
                return
            intent.status = "FILLED"
            intent.exchange_order_id = self._order_id(order) or intent.exchange_order_id
            intent.payload = order
            db.commit()

    def _mark_intent_rejected(self, intent_id: str, error: str) -> None:
        with SessionLocal() as db:
            intent = db.scalars(
                select(OrderIntent).where(OrderIntent.intent_id == intent_id)
            ).first()
            if intent is None:
                return
            intent.status = "REJECTED"
            intent.payload = {**(intent.payload or {}), "error": error}
            db.commit()

    @staticmethod
    def _attach_intent_to_position(intent_id: str, position_id: int) -> None:
        with SessionLocal() as db:
            intent = db.scalars(
                select(OrderIntent).where(OrderIntent.intent_id == intent_id)
            ).first()
            if intent is None:
                return
            intent.position_id = position_id
            db.commit()

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
        if not order:
            return None
        value = order.get("orderId")
        return str(value) if value is not None else None

    @staticmethod
    def _client_order_id(order: dict) -> str | None:
        if not order:
            return None
        value = order.get("clientOrderId") or order.get("listClientOrderId")
        return str(value) if value is not None else None

    @staticmethod
    def _order_status(order: dict) -> str | None:
        if not order:
            return None
        return order.get("status") or order.get("listOrderStatus") or order.get("listStatusType")

    @staticmethod
    def _order_list_id(order: dict | None) -> str | None:
        if not order:
            return None
        value = order.get("orderListId")
        return str(value) if value is not None else None

    @staticmethod
    def _order_list_status(order: dict | None) -> str | None:
        if not order:
            return None
        return order.get("listOrderStatus") or order.get("listStatusType")

    @staticmethod
    def _filled_exit_price_from_order_list(order_list: dict) -> float | None:
        reports = order_list.get("orderReports") or []
        for report in reports:
            if report.get("side") != "SELL":
                continue
            if report.get("status") != "FILLED":
                continue
            try:
                executed_qty = float(report.get("executedQty") or 0)
                quote_qty = float(report.get("cummulativeQuoteQty") or 0)
                if executed_qty > 0 and quote_qty > 0:
                    return quote_qty / executed_qty
                price = float(report.get("price") or 0)
                if price > 0:
                    return price
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _oco_exit_reason(order_list: dict, position: PaperPosition, fill_price: float) -> str:
        reports = order_list.get("orderReports") or []
        for report in reports:
            if report.get("side") != "SELL" or report.get("status") != "FILLED":
                continue
            order_type = report.get("type")
            if order_type in {"LIMIT_MAKER", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"}:
                return "take_profit"
            if order_type in {"STOP_LOSS", "STOP_LOSS_LIMIT"}:
                return "stop_loss"

        if position.take_profit is None:
            return "stop_loss"
        distance_to_tp = abs(fill_price - position.take_profit)
        distance_to_sl = abs(fill_price - position.stop_loss)
        return "take_profit" if distance_to_tp <= distance_to_sl else "stop_loss"

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

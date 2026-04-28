from app.db.models import PaperPosition
from app.db.session import SessionLocal
from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.schemas.trade import PaperTradeResult
from app.services.audit_logger import AuditLogger
from app.services.binance_spot import BinanceSpotClient, BinanceSpotExecutor
from app.services.paper_trading import PaperTradingExecutor


class BinanceFuturesClient(BinanceSpotClient):
    def get_account(self) -> dict:
        return self._signed_request("GET", "/fapi/v2/account")

    def create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        test_order: bool = False,
        client_order_id: str | None = None,
        reduce_only: bool = False,
        position_side: str | None = None,
    ) -> dict:
        path = "/fapi/v1/order/test" if test_order else "/fapi/v1/order"
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": self._format_decimal(quantity),
            "newOrderRespType": "RESULT",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if reduce_only:
            params["reduceOnly"] = "true"
        if position_side:
            params["positionSide"] = position_side.upper()
        return self._signed_request("POST", path, params)

    def create_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "GTC",
        test_order: bool = False,
        client_order_id: str | None = None,
        reduce_only: bool = False,
        position_side: str | None = None,
    ) -> dict:
        path = "/fapi/v1/order/test" if test_order else "/fapi/v1/order"
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "LIMIT",
            "timeInForce": time_in_force.upper(),
            "quantity": self._format_decimal(quantity),
            "price": self._format_decimal(price),
            "newOrderRespType": "RESULT",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if reduce_only:
            params["reduceOnly"] = "true"
        if position_side:
            params["positionSide"] = position_side.upper()
        return self._signed_request("POST", path, params)


class BinanceMarginClient(BinanceSpotClient):
    def get_margin_account(self) -> dict:
        return self._signed_request("GET", "/sapi/v1/margin/account")

    def create_margin_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: float | None = None,
        time_in_force: str = "GTC",
        client_order_id: str | None = None,
        isolated: bool = True,
        side_effect_type: str = "AUTO_BORROW_REPAY",
    ) -> dict:
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": self._format_decimal(quantity),
            "isIsolated": "TRUE" if isolated else "FALSE",
            "sideEffectType": side_effect_type,
            "newOrderRespType": "FULL",
        }
        if price is not None:
            params["price"] = self._format_decimal(price)
        if order_type.upper() == "LIMIT":
            params["timeInForce"] = time_in_force.upper()
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._signed_request("POST", "/sapi/v1/margin/order", params)


class _BinanceDirectionalExecutor(PaperTradingExecutor):
    market_type = "futures"

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
        intent_id: str | None = None,
    ) -> PaperTradeResult:
        self._ensure_mode_allowed()
        self._validate_symbol(signal.symbol)
        self._validate_signal(signal)

        trade_quantity = quantity or self.default_order_quantity
        notional = (signal.entry_price or 0) * trade_quantity
        if notional > self.max_notional_per_order:
            raise ValueError(
                f"Order notional {notional:g} exceeds MAX_NOTIONAL_PER_ORDER "
                f"{self.max_notional_per_order:g}."
            )

        entry_intent_id = intent_id or BinanceSpotExecutor._new_intent_id("entry")
        client_order_id = BinanceSpotExecutor._derive_client_order_id(entry_intent_id, signal.action)
        order = self._place_order(signal, trade_quantity, client_order_id)
        fill_price = (
            BinanceSpotExecutor._average_fill_price(order)
            or self._avg_price(order)
            or signal.entry_price
        )
        executed_qty = BinanceSpotExecutor._executed_quantity(order) or trade_quantity
        calculated_risk = risk_amount or abs(fill_price - signal.stop_loss) * executed_qty

        with SessionLocal() as db:
            position = PaperPosition(
                symbol=signal.symbol,
                action=signal.action,
                status="OPEN",
                quantity=executed_qty,
                entry_price=fill_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                risk_amount=calculated_risk,
                payload={
                    **signal.model_dump(mode="json"),
                    "execution_mode": self.execution_mode,
                    "exchange_order_id": BinanceSpotExecutor._order_id(order),
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
            action=signal.action,
            market_type=self.market_type,
            intent=signal.intent,
            position_side=signal.position_side or ("long" if signal.action == "BUY" else "short"),
            quantity=executed_qty,
            entry_price=fill_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            risk_amount=calculated_risk,
            execution_mode=self.execution_mode,
            exchange_order_id=BinanceSpotExecutor._order_id(order),
            exchange_status=order.get("status", "TEST_ORDER"),
        )
        if self.audit_logger:
            self.audit_logger.record(f"binance_{self.market_type}_trade", result.model_dump(mode="json"))
        return result

    def _validate_signal(self, signal: TradeSignal) -> None:
        if signal.action == "HOLD":
            raise ValueError("HOLD signals cannot be executed.")
        if signal.market_type != self.market_type:
            raise ValueError(f"Signal market_type must be {self.market_type}.")
        if signal.intent != "open":
            raise ValueError("Only opening trades are supported by this executor path.")
        if signal.entry_price is None or signal.stop_loss is None:
            raise ValueError("Executable signals require entry_price and stop_loss.")
        if signal.action == "BUY" and signal.position_side != "long":
            raise ValueError("BUY opening trades must be long.")
        if signal.action == "SELL" and signal.position_side != "short":
            raise ValueError("SELL opening trades must be short.")

    def _place_order(self, signal: TradeSignal, quantity: float, client_order_id: str) -> dict:
        raise NotImplementedError

    @staticmethod
    def _avg_price(order: dict) -> float | None:
        try:
            avg_price = float(order.get("avgPrice") or 0)
        except (TypeError, ValueError):
            return None
        return avg_price if avg_price > 0 else None

    def _ensure_mode_allowed(self) -> None:
        if self.execution_mode == "binance_live" and not self.real_trading_enabled:
            raise RuntimeError("Binance live trading requires REAL_TRADING_ENABLED=true.")

    def _validate_symbol(self, symbol: str) -> None:
        if symbol.upper() not in self.allowed_symbols:
            raise ValueError(f"Symbol {symbol.upper()} is not in ALLOWED_SYMBOLS.")


class BinanceFuturesExecutor(_BinanceDirectionalExecutor):
    market_type = "futures"

    def __init__(self, *args, position_mode: str = "one_way", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.position_mode = position_mode

    def _place_order(self, signal: TradeSignal, quantity: float, client_order_id: str) -> dict:
        position_side = None
        if self.position_mode == "hedge":
            position_side = "LONG" if signal.position_side == "long" else "SHORT"
        client: BinanceFuturesClient = self.client  # type: ignore[assignment]
        if self.order_type == "limit":
            return client.create_limit_order(
                symbol=signal.symbol,
                side=signal.action,
                quantity=quantity,
                price=signal.entry_price,
                time_in_force=self.limit_time_in_force,
                test_order=self.use_test_order_endpoint,
                client_order_id=client_order_id,
                position_side=position_side,
            )
        return client.create_market_order(
            symbol=signal.symbol,
            side=signal.action,
            quantity=quantity,
            test_order=self.use_test_order_endpoint,
            client_order_id=client_order_id,
            position_side=position_side,
        )

    def get_account_state(self, fallback: AccountState) -> AccountState:
        try:
            account = self.client.get_account()
            equity = float(
                account.get("totalMarginBalance")
                or account.get("totalWalletBalance")
                or fallback.equity
            )
        except Exception:
            return fallback
        peak_equity = max(fallback.peak_equity, equity)
        return fallback.model_copy(update={"equity": equity, "peak_equity": peak_equity})


class BinanceMarginExecutor(_BinanceDirectionalExecutor):
    market_type = "margin"

    def __init__(self, *args, isolated: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.isolated = isolated

    def _ensure_mode_allowed(self) -> None:
        super()._ensure_mode_allowed()
        if self.execution_mode == "binance_testnet":
            raise RuntimeError("Binance Margin no está soportado por Spot Testnet; usa paper o live.")

    def _place_order(self, signal: TradeSignal, quantity: float, client_order_id: str) -> dict:
        client: BinanceMarginClient = self.client  # type: ignore[assignment]
        order_type = "LIMIT" if self.order_type == "limit" else "MARKET"
        return client.create_margin_order(
            symbol=signal.symbol,
            side=signal.action,
            quantity=quantity,
            order_type=order_type,
            price=signal.entry_price if order_type == "LIMIT" else None,
            time_in_force=self.limit_time_in_force,
            client_order_id=client_order_id,
            isolated=self.isolated,
        )

    def get_account_state(self, fallback: AccountState) -> AccountState:
        try:
            account = self.client.get_margin_account()  # type: ignore[attr-defined]
            equity = float(account.get("totalNetAssetOfBtc") or 0)
            if equity <= 0:
                return fallback
        except Exception:
            return fallback
        return fallback.model_copy(update={"equity": equity, "peak_equity": max(fallback.peak_equity, equity)})

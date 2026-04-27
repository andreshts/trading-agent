import asyncio
import logging
import httpx
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.services.event_bus import get_event_bus

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self):
        settings = get_settings()
        self.enabled = settings.telegram_notifications_enabled
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self._task: asyncio.Task | None = None

    async def start(self):
        if not self.enabled:
            logger.info("Telegram notifications are disabled.")
            return

        if self.token == "replace_me" or self.chat_id == "replace_me":
            logger.warning("Telegram token or chat_id not configured properly.")
            return

        logger.info("Starting Telegram notifier...")
        self._task = asyncio.create_task(self._listen_to_bus())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _listen_to_bus(self):
        bus = get_event_bus()
        queue = await bus.subscribe()
        try:
            while True:
                message = await queue.get()
                await self._process_message(message)
        finally:
            await bus.unsubscribe(queue)

    async def _process_message(self, message: dict[str, Any]):
        event_type = message.get("type")
        data = message.get("data", {})

        if event_type == "audit_event":
            inner_type = data.get("event_type")
            payload = data.get("payload", {})

            if inner_type == "kill_switch_activated":
                await self.send_message(
                    f"🚨 <b>KILL SWITCH ACTIVADO</b>\n\n"
                    f"Razón: {payload.get('reason', 'Desconocida')}\n"
                    f"Hora: {datetime.now().strftime('%H:%M:%S')}"
                )
            
            elif inner_type == "binance_spot_trade":
                # Apertura de posición
                await self.send_message(
                    f"🔵 <b>NUEVA OPERACIÓN</b>\n\n"
                    f"Símbolo: #{payload.get('symbol')}\n"
                    f"Acción: {payload.get('action')}\n"
                    f"Precio: {payload.get('entry_price')}\n"
                    f"Cantidad: {payload.get('quantity')}\n"
                    f"SL: {payload.get('stop_loss')}\n"
                    f"TP: {payload.get('take_profit')}"
                )

            elif inner_type == "binance_spot_position_closed":
                # Cierre de posición
                pnl = payload.get("realized_pnl", 0)
                emoji = "✅" if pnl >= 0 else "❌"
                await self.send_message(
                    f"{emoji} <b>POSICIÓN CERRADA</b>\n\n"
                    f"Símbolo: #{payload.get('symbol')}\n"
                    f"Razón: {payload.get('exit_reason')}\n"
                    f"Precio salida: {payload.get('exit_price')}\n"
                    f"PnL: {pnl:.2f} USDT"
                )

    async def send_message(self, text: str):
        if not self.enabled:
            return

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.base_url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "HTML"
                    },
                    timeout=10.0
                )
                if response.status_code >= 400:
                    logger.error(f"Error sending Telegram message: {response.text}")
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}")

_notifier: TelegramNotifier | None = None

def get_notifier() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier

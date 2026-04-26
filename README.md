# Trading AI Agent

Backend FastAPI para un agente de paper trading basado en señales estructuradas, controles de riesgo determinísticos, kill switch, posiciones simuladas y auditoría persistente.

## Ejecutar local

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
uvicorn app.main:app --reload
```

## Ejecutar web React

```bash
cd ..\frontend
npm install
npm run dev
```

La web usa `http://localhost:8000` como API por defecto. Si necesitas otra URL, define
`VITE_API_BASE_URL`.

## Ejecutar loop autónomo

Con el backend levantado, este script llama periódicamente a `/agent/autonomous/tick` y deja
que el backend obtenga precio, velas e indicadores desde Binance:

```bash
python scripts/autonomous_loop.py --symbols BTCUSDT,ETHUSDT --interval-seconds 60
```

Para probar una sola iteración:

```bash
python scripts/autonomous_loop.py --symbols BTCUSDT --once
```

Para Testnet interactivo, usa `15M` como timeframe inicial. `1H` es más lento y puede
mantener el bot en `HOLD` durante mucho tiempo si el mercado está neutral.

Tambien puedes iniciar/detener el loop desde el dashboard React con los botones
`Iniciar automatico` y `Detener automatico`. El backend expone:

- `POST /agent/autonomous/start`
- `POST /agent/autonomous/stop`
- `GET /agent/autonomous/status`

## Activar Binance Spot Testnet

El sistema tiene tres modos:

```env
EXECUTION_MODE=paper
EXECUTION_MODE=binance_testnet
EXECUTION_MODE=binance_live
```

Para probar órdenes reales contra Binance Spot Testnet:

```env
EXECUTION_MODE=binance_testnet
BINANCE_API_KEY=tu_testnet_api_key
BINANCE_API_SECRET=tu_testnet_api_secret
BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision
REAL_TRADING_ENABLED=false
ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT
MAX_NOTIONAL_PER_ORDER=100
DEFAULT_ORDER_QUANTITY=0.001
```

En esta fase, Spot Testnet abre posiciones `BUY` con orden `MARKET` y cierra posiciones
con una orden `SELL` `MARKET` cuando el loop detecta `stop_loss`, `take_profit` o cierre
manual. Las señales `SELL` no abren shorts porque Binance Spot no opera shorts.

`binance_live` queda bloqueado mientras `REAL_TRADING_ENABLED=false`.

## Contexto de mercado para IA

Cuando `MARKET_DATA_PROVIDER=binance`, el backend consulta datos públicos de Binance antes
de llamar al proveedor de IA. Cada señal recibe:

- precio actual
- velas del timeframe solicitado
- EMA 9, EMA 21 y EMA 50
- RSI 14
- cambio de 1, 3 y 12 velas
- máximo/mínimo de 20 velas
- volumen actual, promedio de 20 velas y ratio de volumen

```env
MARKET_DATA_PROVIDER=binance
MARKET_DATA_TIMEOUT_SECONDS=5
MARKET_DATA_KLINE_LIMIT=100
```

Esto evita depender de texto manual en el dashboard. Si Binance no responde, el sistema
usa el precio que pueda extraer del contexto como fallback.

Endpoints principales:

- `GET /health`
- `POST /agent/signal`
- `POST /agent/run`
- `POST /agent/autonomous/tick`
- `POST /risk/validate`
- `POST /trades/execute`
- `POST /trades/paper`
- `GET /trades/positions`
- `POST /trades/positions/{position_id}/close`
- `GET /system/status`
- `POST /system/kill-switch/activate`
- `POST /system/kill-switch/deactivate`
- `POST /system/trading/disable`
- `POST /system/trading/enable`
- `POST /system/simulation/reset`

## Seguridad

`REAL_TRADING_ENABLED=false` por defecto. El servidor solo ejecuta operaciones simuladas.

## Variables de entorno para Railway

Backend:

```env
APP_NAME=Trading AI Agent
APP_ENV=production
DEBUG=false
CORS_ORIGINS=https://TU-FRONTEND.up.railway.app
DATABASE_URL=${{Postgres.DATABASE_URL}}
AI_PROVIDER=mock
OPENAI_API_KEY=replace_me
OPENAI_MODEL=gpt-4.1-mini
GEMINI_API_KEY=replace_me
GEMINI_MODEL=gemini-1.5-pro
TRADING_ENABLED=true
PAPER_TRADING_ENABLED=true
REAL_TRADING_ENABLED=false
MARKET_DATA_PROVIDER=binance
MARKET_DATA_TIMEOUT_SECONDS=5
MARKET_DATA_KLINE_LIMIT=100
MAX_DAILY_LOSS=30
MAX_WEEKLY_LOSS=80
MAX_TRADES_PER_DAY=5
MAX_RISK_PER_TRADE_PERCENT=1
MIN_CONFIDENCE=0.55
DEFAULT_ORDER_QUANTITY=0.001
KILL_SWITCH_ENABLED=true
```

Railway inyecta `PORT`; el `Dockerfile` ya lo usa automáticamente.

Frontend:

```env
VITE_API_BASE_URL=https://TU-BACKEND.up.railway.app
```

Importante: las variables `VITE_*` se aplican al construir el frontend. Si cambias
`VITE_API_BASE_URL`, vuelve a desplegar el servicio frontend.

## Persistencia y autonomía

El agente persiste señales, decisiones de riesgo, eventos de auditoría, snapshots de cuenta, eventos de kill switch y posiciones paper. Cada tick autónomo puede cerrar posiciones al tocar `stop_loss` o `take_profit`, actualizar PnL/equity y abrir una nueva posición si el RiskManager la aprueba.

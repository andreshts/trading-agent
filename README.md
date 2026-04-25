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

Endpoints principales:

- `GET /health`
- `POST /agent/signal`
- `POST /agent/run`
- `POST /agent/autonomous/tick`
- `POST /risk/validate`
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

## Persistencia y autonomía

El agente persiste señales, decisiones de riesgo, eventos de auditoría, snapshots de cuenta, eventos de kill switch y posiciones paper. Cada tick autónomo puede cerrar posiciones al tocar `stop_loss` o `take_profit`, actualizar PnL/equity y abrir una nueva posición si el RiskManager la aprueba.

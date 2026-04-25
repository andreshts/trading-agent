# Trading AI Agent

Backend FastAPI para un agente de paper trading basado en señales estructuradas, controles de riesgo determinísticos, kill switch y auditoría en memoria.

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
- `POST /risk/validate`
- `POST /trades/paper`
- `GET /system/status`
- `POST /system/kill-switch/activate`
- `POST /system/kill-switch/deactivate`
- `POST /system/trading/disable`
- `POST /system/trading/enable`

## Seguridad

`REAL_TRADING_ENABLED=false` por defecto. El servidor solo ejecuta operaciones simuladas.


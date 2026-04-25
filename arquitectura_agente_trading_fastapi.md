# Arquitectura de agente de IA para trading con FastAPI, GPT/Gemini y controles de riesgo

> **Objetivo del documento:** definir una arquitectura y una guía paso a paso para construir un agente de IA que analice mercado, genere señales y opere primero en **paper trading/testnet**, usando FastAPI como backend y un proveedor de IA vía API como GPT o Gemini.

> **Advertencia importante:** este diseño debe iniciar únicamente en simulación. La capa de ejecución real debe mantenerse deshabilitada hasta que existan pruebas, auditoría, límites de riesgo, monitoreo y revisión legal/financiera. La IA no debe tener control directo sobre dinero real sin una capa externa de validación.

---

## 1. Idea general

El sistema no debe funcionar como una IA que decide y opera libremente. La arquitectura correcta es:

```text
La IA analiza y propone.
El Risk Manager valida.
El Execution Engine ejecuta.
El Kill Switch detiene todo si se alcanza un límite.
El Audit Logger registra cada decisión.
```

El modelo de IA se usa como apoyo para:

- Interpretar contexto del mercado.
- Analizar noticias o sentimiento.
- Generar una justificación estructurada.
- Clasificar señales como BUY, SELL o HOLD.
- Explicar por qué una operación fue aceptada o rechazada.

El modelo **no** debe ser el encargado final de decidir si una orden se ejecuta. Esa responsabilidad debe estar en código determinista.

---

## 2. Arquitectura general

```text
┌────────────────────┐
│     Frontend       │
│ React / Dashboard  │
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│      FastAPI       │
│ API principal      │
└─────────┬──────────┘
          │
          ▼
┌────────────────────────────────────────────────────┐
│                 Application Layer                  │
│                                                    │
│  ┌───────────────┐    ┌────────────────────────┐   │
│  │ Market Service│    │ AI Signal Service       │   │
│  │ Datos mercado │───▶│ GPT / Gemini            │   │
│  └───────────────┘    └───────────┬────────────┘   │
│                                   │                │
│                                   ▼                │
│  ┌─────────────────────────────────────────────┐   │
│  │ Risk Manager                                │   │
│  │ - Límite diario                             │   │
│  │ - Límite semanal                            │   │
│  │ - Máximo trades/día                         │   │
│  │ - Stop loss obligatorio                     │   │
│  │ - Riesgo máximo por operación               │   │
│  └────────────────────┬────────────────────────┘   │
│                       │                            │
│                       ▼                            │
│  ┌─────────────────────────────────────────────┐   │
│  │ Execution Engine                            │   │
│  │ Paper trading / Testnet / Broker adapter    │   │
│  └────────────────────┬────────────────────────┘   │
│                       │                            │
│                       ▼                            │
│  ┌─────────────────────────────────────────────┐   │
│  │ Audit Logger                                │   │
│  │ Registra señales, decisiones y errores      │   │
│  └─────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────┐
│    PostgreSQL      │
│ Operaciones, logs  │
│ señales, métricas  │
└────────────────────┘
```

---

## 3. Componentes principales

### 3.1 FastAPI Backend

Responsable de exponer endpoints para:

- Consultar estado del agente.
- Solicitar análisis de mercado.
- Generar señales.
- Validar operaciones.
- Activar o desactivar trading.
- Consultar logs y métricas.
- Ejecutar paper trades.

### 3.2 AI Signal Service

Servicio que se comunica con GPT o Gemini.

Debe devolver una respuesta estructurada, por ejemplo:

```json
{
  "symbol": "BTCUSDT",
  "action": "BUY",
  "confidence": 0.72,
  "entry_price": 64200.0,
  "stop_loss": 62800.0,
  "take_profit": 67000.0,
  "risk_amount": 10.0,
  "reason": "Tendencia alcista con ruptura de resistencia y volumen creciente."
}
```

La salida del modelo debe validarse con Pydantic antes de enviarla al Risk Manager.

### 3.3 Risk Manager

Responsable de aprobar o rechazar operaciones.

Reglas mínimas:

- Bloquear si se alcanza la pérdida diaria máxima.
- Bloquear si se alcanza la pérdida semanal máxima.
- Bloquear si se supera el número máximo de operaciones diarias.
- Bloquear si no hay stop loss.
- Bloquear si el riesgo por operación supera el porcentaje permitido.
- Bloquear si el sistema está en modo kill switch.

### 3.4 Execution Engine

Responsable de ejecutar operaciones.

Para la primera versión debe tener solo:

- `PaperTradingExecutor`
- `TestnetExecutor`, si aplica

La ejecución real debe quedar detrás de una interfaz y deshabilitada por configuración.

### 3.5 Kill Switch

Mecanismo que detiene el sistema completo cuando ocurre una condición crítica.

Ejemplos:

- Pérdida diaria alcanzada.
- Error repetido de API.
- Señales inconsistentes del modelo.
- Operaciones duplicadas.
- Desviación entre precio esperado y precio ejecutado.
- Latencia excesiva.

### 3.6 Audit Logger

Debe registrar:

- Prompt enviado al modelo.
- Respuesta estructurada del modelo.
- Señal generada.
- Resultado del Risk Manager.
- Motivo de aprobación o rechazo.
- Operación simulada.
- Errores.
- Estado del sistema.

---

## 4. Estructura de carpetas recomendada

```text
trading-ai-agent/
│
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── logger.py
│   │
│   ├── api/
│   │   ├── routes/
│   │   │   ├── health.py
│   │   │   ├── agent.py
│   │   │   ├── risk.py
│   │   │   ├── trades.py
│   │   │   └── system.py
│   │   └── deps.py
│   │
│   ├── schemas/
│   │   ├── market.py
│   │   ├── signal.py
│   │   ├── risk.py
│   │   ├── trade.py
│   │   └── system.py
│   │
│   ├── services/
│   │   ├── market_service.py
│   │   ├── ai_signal_service.py
│   │   ├── risk_manager.py
│   │   ├── execution_engine.py
│   │   ├── paper_trading.py
│   │   ├── kill_switch.py
│   │   └── audit_logger.py
│   │
│   ├── providers/
│   │   ├── ai_provider.py
│   │   ├── openai_provider.py
│   │   └── gemini_provider.py
│   │
│   ├── db/
│   │   ├── session.py
│   │   ├── base.py
│   │   └── models/
│   │       ├── trade.py
│   │       ├── signal.py
│   │       ├── risk_event.py
│   │       └── system_state.py
│   │
│   └── tests/
│       ├── test_risk_manager.py
│       ├── test_kill_switch.py
│       ├── test_signal_schema.py
│       └── test_paper_trading.py
│
├── .env.example
├── docker-compose.yml
├── pyproject.toml
├── README.md
└── ARCHITECTURE.md
```

---

## 5. Variables de entorno

Archivo `.env.example`:

```env
APP_NAME=Trading AI Agent
APP_ENV=development
DEBUG=true

DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/trading_agent

AI_PROVIDER=openai
OPENAI_API_KEY=replace_me
OPENAI_MODEL=gpt-4.1-mini

GEMINI_API_KEY=replace_me
GEMINI_MODEL=gemini-1.5-pro

TRADING_ENABLED=false
PAPER_TRADING_ENABLED=true
REAL_TRADING_ENABLED=false

MAX_DAILY_LOSS=30
MAX_WEEKLY_LOSS=80
MAX_TRADES_PER_DAY=5
MAX_RISK_PER_TRADE_PERCENT=1

KILL_SWITCH_ENABLED=true
```

Regla crítica:

```text
REAL_TRADING_ENABLED=false por defecto.
```

---

## 6. Modelos Pydantic principales

### 6.1 SignalRequest

```python
from pydantic import BaseModel, Field

class SignalRequest(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"])
    timeframe: str = Field(..., examples=["1h"])
    market_context: str
```

### 6.2 TradeSignal

```python
from typing import Literal
from pydantic import BaseModel, Field

class TradeSignal(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(..., ge=0, le=1)
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_amount: float = Field(default=0, ge=0)
    reason: str
```

### 6.3 AccountState

```python
from pydantic import BaseModel, Field

class AccountState(BaseModel):
    equity: float = Field(..., gt=0)
    daily_loss: float = Field(default=0, ge=0)
    weekly_loss: float = Field(default=0, ge=0)
    trades_today: int = Field(default=0, ge=0)
    trading_enabled: bool = True
```

### 6.4 RiskDecision

```python
from pydantic import BaseModel

class RiskDecision(BaseModel):
    approved: bool
    reason: str
```

---

## 7. Risk Manager base

```python
class RiskManager:
    def __init__(self, max_daily_loss, max_weekly_loss, max_trades_per_day):
        self.max_daily_loss = max_daily_loss
        self.max_weekly_loss = max_weekly_loss
        self.max_trades_per_day = max_trades_per_day

    def validate_trade(self, signal, account_state):
        if not account_state.get("trading_enabled", True):
            return False, "Trading bloqueado por kill switch"

        if account_state["daily_loss"] >= self.max_daily_loss:
            return False, "Límite de pérdida diaria alcanzado"

        if account_state["weekly_loss"] >= self.max_weekly_loss:
            return False, "Límite de pérdida semanal alcanzado"

        if account_state["trades_today"] >= self.max_trades_per_day:
            return False, "Máximo de operaciones diarias alcanzado"

        if signal.get("action") in ["BUY", "SELL"] and signal.get("stop_loss") is None:
            return False, "Operación bloqueada: no tiene stop loss"

        if signal["risk_amount"] > account_state["equity"] * 0.01:
            return False, "Riesgo por operación superior al 1%"

        return True, "Operación aprobada"
```

Mejora recomendada para producción:

- Recibir `max_risk_per_trade_percent` por configuración.
- Usar objetos Pydantic en lugar de diccionarios.
- Registrar cada validación.
- Bloquear señales con campos incompletos.
- Bloquear señales con `confidence` menor al umbral mínimo.

---

## 8. Flujo principal de operación

```text
1. Usuario o scheduler solicita análisis.
2. MarketService obtiene datos de mercado.
3. AISignalService envía contexto al modelo GPT/Gemini.
4. El modelo devuelve JSON estructurado.
5. Pydantic valida el JSON.
6. RiskManager evalúa la señal.
7. Si se aprueba, PaperTradingExecutor simula la operación.
8. AuditLogger registra todo.
9. Dashboard muestra resultado.
10. KillSwitch detiene el sistema si se alcanza un límite.
```

---

## 9. Endpoints recomendados

### Health

```http
GET /health
```

Respuesta:

```json
{
  "status": "ok"
}
```

### Generar señal

```http
POST /agent/signal
```

Body:

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "market_context": "Precio en tendencia alcista, volumen creciente, RSI 58."
}
```

### Validar operación

```http
POST /risk/validate
```

### Ejecutar paper trade

```http
POST /trades/paper
```

### Ver estado del sistema

```http
GET /system/status
```

### Activar kill switch manual

```http
POST /system/kill-switch/activate
```

### Desactivar trading

```http
POST /system/trading/disable
```

---

## 10. Prompt base para GPT/Gemini

El prompt debe exigir JSON estructurado.

```text
Eres un asistente de análisis de mercado para un sistema de paper trading.

Tu tarea es analizar el contexto recibido y devolver una señal estructurada.

Reglas obligatorias:
- Responde únicamente en JSON válido.
- No incluyas texto fuera del JSON.
- Si no hay suficiente información, usa action = "HOLD".
- Nunca sugieras una operación sin stop_loss.
- Nunca inventes precios si no están en el contexto.
- Incluye una justificación breve en el campo reason.

Formato esperado:
{
  "symbol": "string",
  "action": "BUY | SELL | HOLD",
  "confidence": number entre 0 y 1,
  "entry_price": number o null,
  "stop_loss": number o null,
  "take_profit": number o null,
  "risk_amount": number,
  "reason": "string"
}

Contexto de mercado:
{market_context}
```

---

## 11. Interfaz para proveedores de IA

### 11.1 Contrato base

```python
from abc import ABC, abstractmethod
from app.schemas.signal import TradeSignal

class AIProvider(ABC):
    @abstractmethod
    async def generate_signal(self, market_context: str) -> TradeSignal:
        pass
```

### 11.2 OpenAIProvider

```python
class OpenAIProvider(AIProvider):
    async def generate_signal(self, market_context: str) -> TradeSignal:
        # 1. Construir prompt
        # 2. Llamar API de OpenAI
        # 3. Parsear JSON
        # 4. Validar con Pydantic
        # 5. Retornar TradeSignal
        pass
```

### 11.3 GeminiProvider

```python
class GeminiProvider(AIProvider):
    async def generate_signal(self, market_context: str) -> TradeSignal:
        # 1. Construir prompt
        # 2. Llamar API de Gemini
        # 3. Parsear JSON
        # 4. Validar con Pydantic
        # 5. Retornar TradeSignal
        pass
```

---

## 12. Implementación paso a paso

### Fase 1: Crear proyecto base

Tareas:

- Crear proyecto FastAPI.
- Configurar entorno virtual.
- Configurar `.env`.
- Crear endpoint `/health`.
- Agregar Docker y docker-compose.

Prompt para Codex/Copilot:

```text
Crea un proyecto FastAPI llamado trading-ai-agent con estructura modular.
Incluye app/main.py, app/core/config.py, app/api/routes/health.py y docker-compose.yml.
Usa Pydantic Settings para leer variables de entorno.
Agrega un endpoint GET /health que devuelva {"status": "ok"}.
No implementes trading real.
```

---

### Fase 2: Crear schemas

Tareas:

- Crear `TradeSignal`.
- Crear `SignalRequest`.
- Crear `AccountState`.
- Crear `RiskDecision`.

Prompt:

```text
Crea los modelos Pydantic para un sistema de paper trading:
SignalRequest, TradeSignal, AccountState y RiskDecision.
Valida que confidence esté entre 0 y 1.
Valida que equity sea mayor a 0.
La acción debe ser BUY, SELL o HOLD.
Usa typing Literal y Field.
```

---

### Fase 3: Implementar RiskManager

Tareas:

- Crear `app/services/risk_manager.py`.
- Implementar reglas de pérdida diaria, semanal, trades diarios, stop loss y riesgo máximo por operación.
- Crear tests unitarios.

Prompt:

```text
Implementa un RiskManager en Python para FastAPI.
Debe recibir max_daily_loss, max_weekly_loss, max_trades_per_day y max_risk_per_trade_percent.
Debe tener un método validate_trade(signal: TradeSignal, account_state: AccountState) -> RiskDecision.
Debe bloquear:
1. trading_enabled=false,
2. daily_loss >= max_daily_loss,
3. weekly_loss >= max_weekly_loss,
4. trades_today >= max_trades_per_day,
5. BUY/SELL sin stop_loss,
6. risk_amount superior al porcentaje permitido del equity.
Crea tests unitarios con pytest para cada caso.
```

---

### Fase 4: Crear AIProvider

Tareas:

- Crear interfaz `AIProvider`.
- Crear implementación para OpenAI.
- Crear implementación para Gemini.
- Validar salida con Pydantic.
- Manejar errores si la IA devuelve JSON inválido.

Prompt:

```text
Crea una capa de proveedores de IA para FastAPI.
Define una clase abstracta AIProvider con generate_signal(market_context: str) -> TradeSignal.
Crea OpenAIProvider y GeminiProvider como implementaciones.
La respuesta del modelo debe parsearse como JSON y validarse con el schema TradeSignal.
Si la respuesta es inválida, retorna una señal HOLD con reason indicando error de validación.
No ejecutes operaciones reales.
```

---

### Fase 5: Crear AISignalService

Tareas:

- Seleccionar proveedor según `AI_PROVIDER`.
- Generar prompt.
- Solicitar señal.
- Retornar `TradeSignal`.

Prompt:

```text
Crea AISignalService.
Debe recibir un AIProvider por inyección de dependencias.
Debe construir un prompt seguro para paper trading.
Debe pedir salida JSON válida.
Debe retornar un TradeSignal validado.
Si no hay suficiente información, debe retornar HOLD.
```

---

### Fase 6: Crear PaperTradingExecutor

Tareas:

- Simular ejecución.
- Registrar operación.
- No conectar broker real.
- Devolver resultado simulado.

Prompt:

```text
Crea PaperTradingExecutor.
Debe recibir una TradeSignal aprobada y crear una operación simulada.
Debe devolver symbol, action, entry_price, stop_loss, take_profit, status="simulated" y timestamp.
Debe rechazar señales HOLD.
No debe conectarse a ningún broker real.
```

---

### Fase 7: Crear KillSwitchService

Tareas:

- Mantener estado de trading habilitado/deshabilitado.
- Activar por pérdida diaria o error crítico.
- Exponer endpoints para activar/desactivar.

Prompt:

```text
Crea KillSwitchService.
Debe tener métodos activate(reason), deactivate(), is_active() y get_status().
Cuando esté activo, RiskManager debe bloquear cualquier operación.
Crea endpoints POST /system/kill-switch/activate, POST /system/kill-switch/deactivate y GET /system/status.
```

---

### Fase 8: Crear endpoint principal `/agent/run`

Tareas:

- Recibir símbolo y contexto.
- Generar señal con IA.
- Validar con RiskManager.
- Ejecutar paper trade si se aprueba.
- Guardar auditoría.
- Retornar resultado completo.

Prompt:

```text
Crea un endpoint POST /agent/run.
Flujo:
1. Recibe SignalRequest.
2. Usa AISignalService para generar TradeSignal.
3. Obtiene AccountState simulado.
4. Usa RiskManager para validar.
5. Si se aprueba, ejecuta PaperTradingExecutor.
6. Si se rechaza, retorna la razón.
7. Registra todo con AuditLogger.
La respuesta debe incluir signal, risk_decision y execution_result.
No debe existir ejecución real.
```

---

### Fase 9: Persistencia con PostgreSQL

Tareas:

- Crear modelos SQLAlchemy.
- Guardar señales.
- Guardar decisiones de riesgo.
- Guardar operaciones simuladas.
- Guardar eventos del kill switch.

Prompt:

```text
Agrega persistencia con PostgreSQL y SQLAlchemy.
Crea modelos para SignalLog, RiskDecisionLog, PaperTrade y SystemEvent.
Cada registro debe guardar timestamp, symbol, action, payload JSON y status.
Crea migraciones con Alembic.
```

---

### Fase 10: Dashboard futuro

Tareas:

- Ver estado del agente.
- Ver señales generadas.
- Ver operaciones simuladas.
- Ver pérdidas acumuladas.
- Ver si el kill switch está activo.

Prompt:

```text
Crea un dashboard en React para consultar el backend FastAPI.
Debe mostrar:
- Estado del sistema.
- Trading habilitado o bloqueado.
- Últimas señales.
- Últimas operaciones simuladas.
- Motivos de rechazo del RiskManager.
No debe permitir trading real.
```

---

## 13. Pruebas mínimas obligatorias

### RiskManager

Casos:

- Aprueba una operación válida.
- Rechaza si daily_loss alcanza el límite.
- Rechaza si weekly_loss alcanza el límite.
- Rechaza si supera trades diarios.
- Rechaza BUY sin stop loss.
- Rechaza SELL sin stop loss.
- Rechaza riesgo por operación mayor al permitido.
- Rechaza si kill switch está activo.

### AIProvider

Casos:

- Devuelve TradeSignal válido.
- Si la IA responde JSON inválido, retorna HOLD.
- Si faltan campos obligatorios, retorna HOLD.

### PaperTradingExecutor

Casos:

- Simula BUY aprobado.
- Simula SELL aprobado.
- Rechaza HOLD.

### KillSwitch

Casos:

- Activa correctamente.
- Bloquea operaciones.
- Guarda razón de bloqueo.
- Permite desactivar manualmente solo si se decide permitirlo.

---

## 14. Reglas de seguridad del sistema

Estas reglas deben estar en código, no solo en prompts:

```text
1. REAL_TRADING_ENABLED=false por defecto.
2. Ninguna operación BUY/SELL sin stop_loss.
3. Ninguna operación si kill switch está activo.
4. Ninguna operación si se alcanzó pérdida diaria.
5. Ninguna operación si se alcanzó pérdida semanal.
6. Ninguna operación si se superó el máximo de trades diarios.
7. Ninguna operación si la respuesta de IA no valida contra Pydantic.
8. Toda decisión debe quedar registrada.
9. Todo fallo crítico activa modo seguro.
10. El modelo nunca ejecuta directamente una orden.
```

---

## 15. Criterios de aceptación

El proyecto se considera funcional cuando:

- Existe un endpoint `/health` funcional.
- El agente puede generar señales estructuradas.
- El RiskManager aprueba o rechaza señales correctamente.
- El sistema ejecuta únicamente operaciones simuladas.
- El KillSwitch bloquea operaciones.
- Existen tests unitarios para las reglas críticas.
- Se guardan logs de señales y decisiones.
- El sistema no tiene credenciales hardcodeadas.
- El trading real está deshabilitado por defecto.

---

## 16. Roadmap sugerido

```text
Semana 1:
- FastAPI base
- Schemas Pydantic
- RiskManager
- Tests unitarios

Semana 2:
- Integración con GPT/Gemini
- Validación de salida estructurada
- Endpoint /agent/run

Semana 3:
- PaperTradingExecutor
- PostgreSQL
- AuditLogger

Semana 4:
- KillSwitch
- Dashboard básico
- Métricas

Semana 5+:
- Backtesting
- Mejoras de estrategia
- Alertas
- Monitoreo
```

---

## 17. Fuentes recomendadas

- FastAPI - Bigger Applications: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- FastAPI - Dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/
- OpenAI API - Code generation: https://developers.openai.com/api/docs/guides/code-generation
- GitHub Copilot Documentation: https://docs.github.com/copilot
- GitHub Copilot Coding Agent: https://docs.github.com/copilot/concepts/agents/coding-agent/about-coding-agent
- Gemini API - Structured Outputs: https://ai.google.dev/gemini-api/docs/structured-output
- Gemini API Reference: https://ai.google.dev/api

---

## 18. Conclusión

La implementación recomendada no es un bot de trading libre, sino un sistema controlado:

```text
GPT/Gemini genera señales.
FastAPI orquesta.
Pydantic valida.
RiskManager decide.
PaperTradingExecutor simula.
KillSwitch protege.
AuditLogger registra.
```

La primera versión debe enfocarse en aprendizaje, simulación, pruebas y control de riesgo. Solo después de validar resultados, métricas, seguridad y cumplimiento regulatorio tendría sentido considerar una capa de ejecución real.

# CT4 Monitor v8 — Documentación Completa

## ¿Qué es?
Un bot de trading automatizado de criptomonedas que analiza el mercado 24/7, detecta oportunidades de compra (LONG) y venta (SHORT), y ejecuta operaciones simuladas o reales en Binance.

---

## Arquitectura General

```
┌─────────────────────────────────────────────────┐
│              monitor_server.py                   │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  Scanner  │→ │ Analyzer │→ │    Trader     │  │
│  │  (ccxt)   │  │ (11 ind) │  │ Paper / Live  │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│       ↓             ↓              ↓              │
│  51+ coins     Score 0-100    Open/Close pos     │
│  cada 60s      LONG + SHORT   TP/SL/Trailing     │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Telegram │  │Dashboard │  │  Kill Switch  │  │
│  │  Alerts  │  │ API:8080 │  │  + Audit Log  │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────────────────────────────┘
```

---

## Ciclo de Operación (cada 60 segundos)

### 1. Escaneo
- Descarga velas de **1 hora** (OHLCV) de **51+ coins** via `ccxt` (Binance público).
- Incluye coins base (`BASE_WATCH`) + coins "calientes" descubiertas dinámicamente.

### 2. Análisis — Scoring Dual (LONG + SHORT)
Cada moneda recibe dos puntuaciones independientes (0-100):

| Indicador | Qué mide | Puntos LONG | Puntos SHORT |
|:---|:---|:---:|:---:|
| **RSI 14** | Sobreventa/sobrecompra | RSI < 25 → +25 | RSI > 75 → +25 |
| **RSI 7** | Impulso rápido | RSI7 < 20 → +10 | RSI7 > 80 → +10 |
| **Bollinger Bands** | Posición en rango | Close < BBL → +20 | Close > BBU → +20 |
| **EMA 9/21** | Tendencia corta | EMA9 > EMA21 → +10 | EMA9 < EMA21 → +10 |
| **EMA 50/200** | Tendencia macro | Bullish → filtro | Bearish → filtro |
| **Volumen** | Actividad | Vol > 2× SMA → +10 | Vol > 2× SMA → +10 |
| **MACD** | Momentum | MACD-H > 0 → +5 | MACD-H < 0 → +5 |
| **Patrones Vela** | Formaciones | Hammer → +15 | Shooting Star → +15 |
| **ROC (Rate of Change)** | Velocidad de precio | ROC positivo → +10 | ROC negativo → +10 |
| **Cambio 1h/24h** | Contexto | Caída fuerte → +20 | Subida débil → +15 |
| **Noticias** (CryptoPanic) | Sentimiento | Positivas → +15 | Negativas → +15 |

### 3. Filtro EMA (seguridad)
- Para abrir LONG → EMA50 > EMA200 (tendencia alcista) **O** Score ≥ 70 (override).
- Para abrir SHORT → EMA50 < EMA200 (tendencia bajista) **O** Score ≥ 70 (override).

### 4. Modos de Mercado (Fear & Greed Index)
El bot adapta su agresividad según el sentimiento del mercado:

| F&G Index | Modo | Score Mínimo | Take Profit | Stop Loss |
|:---:|:---|:---:|:---:|:---:|
| < 25 | 🔴 **CAUTIOUS** | 55 | 5.0% | 3.0% |
| 25-49 | 🟡 NORMAL | 50 | 3.0% | 2.0% |
| ≥ 50 | 🟢 AGGRESSIVE | 45 | 2.0% | 1.5% |

---

## Gestión de Posiciones

### Apertura
- Máximo **3 posiciones simultáneas**.
- Tamaño fijo: `min($CAPITAL / 3, balance × 0.33)` ≈ **$10 por trade** con $30.
- **Cooldown**: 30 min entre trades en la misma moneda.
- **SL Ban**: 2 Stop Loss consecutivos → ban de 2 horas en esa moneda.

### Cierre (4 mecanismos)
1. **Take Profit (TP)**: Precio alcanza el % objetivo → Cierre con ganancia.
2. **Stop Loss (SL)**: Precio cae al % límite → Cierre con pérdida controlada.
3. **Trailing Stop**: Si el precio sube ≥ 1.5%, el SL se mueve a *breakeven* (precio de entrada) y luego sigue al precio top a -1% de distancia. Protege ganancias.
4. **Timeout**: Si después de 4 horas el PnL es < 0.5%, cierra. Libera capital.

---

## Seguridad (Kill Switch)

| Protección | Límite | Acción |
|:---|:---:|:---|
| **Pérdida diaria** | -5% del capital | Bot para de operar ese día |
| **Drawdown máximo** | -15% desde el pico | Bot para completamente |
| **Archivo KILL_SWITCH** | Crear `/opt/ct4/KILL_SWITCH` | Bot para al instante |
| **Persistencia** | `state/trader_state.json` | Recupera posiciones tras reinicios |
| **Audit Log** | `logs/trades.csv` | Registro de cada trade para análisis |

---

## Modos de Trading

Controlado por `TRADING_MODE` en `.env`:

| Modo | Qué hace |
|:---|:---|
| `paper` | **Simulación** — No toca dinero real. Usa precios reales pero trades virtuales. |
| `live` | **Dinero real** — Ejecuta órdenes reales en Binance Spot via API. |

---

## Infraestructura

| Componente | Ubicación |
|:---|:---|
| **Servidor** | Hetzner VPS `95.217.158.7` (Linux) |
| **Proceso** | `monitor_server.py` corriendo 24/7 con `nohup` |
| **Dashboard** | `http://95.217.158.7:8080` (FastAPI + HTML) |
| **Alertas** | Telegram Bot → Abre/cierra posiciones en tu chat |
| **Estado** | `/opt/ct4/state/trader_state.json` |
| **Logs** | `/opt/ct4/logs/monitor.log` + `trades.csv` |

---

## Despliegue

```bash
# Desde tu PC (Windows):
python deploy.py          # Sube código + reinicia bot
python start_bot.py       # Solo reiniciar
```

---

## Rendimiento Histórico (Paper)

| Periodo | Config | Trades | Win Rate | PnL |
|:---|:---|:---:|:---:|:---:|
| Mar 10-11 | CAUTIOUS 72% | 29 | **72.4%** | +$1.17 |
| Mar 12-16 | NORMAL 28% | 35 | 28.5% | -$3.08 |
| Mar 19+ | CAUTIOUS (restaurada) | En curso | En curso | En curso |

**Lección**: La config CAUTIOUS (SL 3%, TP 5%, trailing 1.5%) funciona. La NORMAL fue demasiado agresiva.

---

## Resumen en una frase

> El bot escanea 51+ criptomonedas cada minuto, puntúa cada una con 11 indicadores técnicos, y abre posiciones LONG o SHORT solo cuando la puntuación supera un umbral adaptado al miedo/codicia del mercado, protegiendo el capital con trailing stops, timeouts, y un kill switch automático.

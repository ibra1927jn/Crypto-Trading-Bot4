# Análisis Profundo — Crypto-Trading-Bot4
**Fecha:** 2026-03-27

---

## 1. Módulos/Sistemas Completamente Implementados

### Main Bot — Sniper Rotativo (main.py)
- Clase `TradingBot` completamente implementada con ciclo de vida completo: startup → loop → shutdown
- Patrón "Sniper Rotativo": vigila 5 monedas (XRP, DOGE, AVAX, SHIB, SOL), concentra 90% del capital en la mejor señal, cierra, rota
- Secuencia de arranque con wake-up sequence que reconcilia estado exchange ↔ local
- Dashboard web integrado en puerto 8080 via FastAPI/Uvicorn

### Execution Engine (engines/execution_engine.py)
- Conexión async a Binance (Testnet o Live) via CCXT
- Wake-up sequence: reconciliación bidireccional exchange ↔ SQLite
- Órdenes OCO (Hard SL/TP) en el servidor del exchange
- Reintentos con backoff exponencial (MAX_RETRIES=5)
- Emergency shutdown: cancel all + close all
- Gestión de posiciones: open/close/orphaned

### Alpha Engine (engines/alpha_engine.py)
- Sistema de scoring de señales 0-100 por moneda
- Indicadores: RSI7, RSI14, volumen ratio, MACD, Stochastic K, Bollinger Bands
- Dos estrategias validadas:
  - AllIn RSI<15: funciona con BONK, NEAR, TIA
  - MomBurst+: funciona con SAND, DOGE
- Selección automática de la mejor moneda para disparar

### Data Engine (engines/data_engine.py)
- Warmup multi-moneda: descarga historial de N monedas × 250 velas
- WebSocket multi-stream para recibir velas en tiempo real de todas las monedas simultáneamente
- Cálculo automático de indicadores técnicos (RSI, MACD, BB, ATR, ADX, Stochastic) via pandas-ta
- Detección de cierre de vela para triggers de señal

### Risk Engine (engines/risk_engine.py)
- Kill Switch global: se activa si drawdown diario > 10% o errores consecutivos > 5
- Position sizing: 90% all-in en la mejor señal
- SL/TP basados en porcentaje (-3% / +5%) con trailing stop (2%)
- Reset automático del kill switch al nuevo día UTC
- Validación de señales del Alpha Engine

### News Engine (engines/news_engine.py)
- Integración con CryptoPanic API para sentiment
- Filtrado de noticias por moneda
- Async HTTP via aiohttp

### Telegram Engine (engines/telegram_engine.py)
- Alertas de trades vía Telegram
- Notificaciones de arranque, posiciones, errores
- python-telegram-bot integrado

### Base de Datos (db/database.py)
- SQLite async con WAL mode (escritura concurrente sin locks)
- Tablas: positions, orders, daily_pnl
- Funciones: init_db, get_open_positions, save_position, close_position, mark_position_orphaned, save_order, get_daily_pnl, upsert_daily_pnl

### API Dashboard (api/server.py, api_dashboard.py, dashboard.html)
- FastAPI server con endpoints de estado
- Dashboard HTML interactivo (34KB)
- Deploy del dashboard como web estática

### Configuración Centralizada (config/settings.py)
- Todas las variables en un solo fichero con env overrides
- Parámetros de estrategia documentados
- WebSocket URLs para múltiples exchanges (Binance, MEXC, KuCoin)
- Modo sandbox/live configurable

### Backtesting (backtest_v12.py, backtest_v14_compare.py)
- Motor de backtesting con datos reales (Sep 2025 → Mar 2026)
- Comparación de estrategias v12 vs v14
- Generación de reportes

### Scoring AI (scoring_ai/)
- Auto-learning de señales (auto_learn.py)
- Collector de datos para ML (collector.py)
- Scorer de estrategias (scorer.py)
- Similarity analysis (similarity.py)
- Vector DB local (vector_db.json)

### Scripts de Lab Extensivos (scripts/)
- 50+ scripts de laboratorio para probar estrategias: lab_arena.py, lab_battle.py, lab_stress_test.py, lab_mega_matrix.py, lab_sniper.py, etc.
- Comparativas de monedas y timeframes
- Scripts de diagnóstico y monitoreo

---

## 2. Módulos a Medias o Estructura Vacía

### Monitor Engine (engines/monitor_engine.py)
- Existe pero su integración con el ciclo principal no está clara — puede estar parcialmente integrado

### Backtest Engine (engines/backtest_engine.py)
- Existe como módulo separado pero hay backtests standalone (backtest_v12.py, backtest_v14_compare.py) que podrían duplicar funcionalidad

### Tests Formales (tests/)
- Solo 3 ficheros de test: `__init__.py`, `chaos_network_test.py`, `demon3_gaslighting_test.py`
- No hay tests unitarios para los engines principales
- Los "tests" reales son los 50+ scripts de lab/ que no siguen pytest conventions

### Web Dashboard (web/index.html)
- Existe pero es separado del dashboard.html principal — posible duplicación

### Deploy Scripts
- Múltiples versiones: deploy_v12.py, deploy_v15.py, upload_v15.py — fragmentación de versiones

### v15 Scalper (v15_scalper.py)
- Parece una versión alternativa/experimental del bot con estrategia de scalping — no integrada en main.py

---

## 3. Problemas Técnicos a Primera Vista

### Credenciales hardcodeadas en scripts de deploy
- `set up/scripts/deploy_ct4.py` contiene IP, usuario root y contraseña en texto plano
- Riesgo de seguridad crítico si se commitea

### Fragmentación de versiones
- Hay ficheros v12, v14, v15 mezclados sin documentación clara de cuál es la versión activa
- `main.py` parece ser la versión actual (Sniper Rotativo) pero hay código legacy conviviendo

### Ficheros de output sueltos
- `check_out.txt`, `clean_output.txt`, `current_status.txt`, `pnl_out.txt`, `states_out.txt`, `test_out.txt` — basura de ejecuciones anteriores en el repo

### Sin CI/CD
- No hay GitHub Actions, no hay Dockerfile — el deploy es manual via scripts Python

### Sandbox vs Live
- EXCHANGE_SANDBOX=true por defecto — el bot solo ha corrido en testnet. El salto a live requiere validación adicional

### SQLite en producción
- SQLite es single-writer — si el bot escala o necesita concurrencia real, necesitará migrar a PostgreSQL

### Sin rate limiting propio
- Depende 100% del rate limiter de CCXT — si CCXT falla, no hay protección adicional

### Logging disperso
- 50+ scripts de lab generan logs a ficheros temporales sin rotación ni cleanup

---

## 4. Librerías y Herramientas Exactas

### Core
- **Python 3.x** (no especifica versión mínima)
- **FastAPI >= 0.110.0** — API web + dashboard
- **Uvicorn >= 0.30.0** — ASGI server

### Exchange
- **CCXT >= 4.2.0** — Librería multi-exchange (Binance, MEXC, KuCoin)
- **websockets >= 12.0** — WebSocket streaming de velas en tiempo real

### Data / ML
- **Pandas >= 2.2.0** — DataFrames para datos OHLCV
- **pandas-ta >= 0.3.14b0** — Indicadores técnicos (RSI, MACD, BB, ATR, ADX, Stochastic)

### Base de Datos
- **aiosqlite >= 0.20.0** — SQLite async con WAL mode

### Comunicación
- **python-telegram-bot >= 21.0** — Alertas vía Telegram
- **aiohttp >= 3.9.0** — HTTP async para News Engine (CryptoPanic)

### Testing
- **pytest >= 8.0.0** — Framework de testing
- **pytest-asyncio >= 0.23.5** — Testing async

### Configuración
- **python-dotenv >= 1.0.1** — Variables de entorno desde .env

---

## 5. Ficheros Más Importantes

| Fichero | Descripción |
|---------|-------------|
| `main.py` | Punto de entrada — clase TradingBot con ciclo Sniper Rotativo |
| `config/settings.py` | Configuración centralizada — estrategias, risk params, exchange |
| `engines/execution_engine.py` | Motor de ejecución — conexión exchange, órdenes, reconciliación |
| `engines/alpha_engine.py` | Motor de señales — scoring multi-moneda 0-100 |
| `engines/data_engine.py` | Motor de datos — WebSocket multi-stream + indicadores |
| `engines/risk_engine.py` | Motor de riesgo — kill switch, position sizing, SL/TP |
| `engines/telegram_engine.py` | Alertas Telegram |
| `db/database.py` | Base de datos SQLite WAL — positions, orders, daily_pnl |
| `api/server.py` | FastAPI dashboard backend |
| `backtest_v12.py` | Motor de backtesting con datos reales |
| `scoring_ai/scorer.py` | ML scoring de estrategias |
| `requirements.txt` | Dependencias Python |

---

## 6. Lo Que Falta Para Ser un Producto Completo

### Seguridad
- Eliminar credenciales hardcodeadas de todos los scripts
- Implementar gestión segura de API keys (vault, env vars en server)
- Audit trail de todas las operaciones del bot

### Testing real
- Tests unitarios para cada engine (alpha, data, risk, execution)
- Tests de integración con exchange mock
- Test de failover: qué pasa si WebSocket se cae, si exchange responde lento, si SQLite se corrompe

### Deploy automatizado
- Dockerfile con todas las dependencias
- docker-compose para bot + dashboard
- CI/CD: build → test → deploy a VPS

### Monitoreo en producción
- Métricas de performance (latencia de órdenes, websocket lag)
- Alertas de degradación (no solo errores)
- Dashboard de PnL en tiempo real (no solo logs)

### Gestión de capital real
- El bot está en testnet. Para dinero real necesita:
  - Validación exhaustiva con paper trading real (no backtest)
  - Límites de pérdida absolutos (no solo porcentuales)
  - Kill switch manual instantáneo desde Telegram
  - Auditoría de todas las órdenes ejecutadas

### Multi-exchange
- Configurado para Binance/MEXC/KuCoin pero solo testado en Binance testnet
- Cada exchange tiene quirks diferentes que necesitan manejo específico

### Cleanup
- Eliminar los 50+ scripts de lab del directorio raíz
- Consolidar versiones (v12, v14, v15) — quedarse con una
- Eliminar ficheros de output (.txt) del repo

### Documentación
- Manual de operaciones: cómo arrancar, parar, monitorear
- Documentación de estrategias con resultados de backtest
- Runbook de incidentes: qué hacer si el kill switch se activa

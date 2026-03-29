# Crypto-Trading-Bot4 — Bot de trading crypto (Sniper Rotativo)

## Stack
Python 3.10+ | FastAPI + Uvicorn | CCXT async | aiosqlite (WAL mode)
WebSocket streaming (binance, mexc, kucoin, bybit)
pandas + pandas-ta (indicadores tecnicos) | pytest + pytest-asyncio

## Commands
- `python main.py` — Bot principal (Sniper Rotativo, 5 monedas, dashboard :8080)
- `pytest tests/` — Tests (chaos network + exchange gaslighting)
- `python scripts/lab.py` — Backtest standard
- `python scripts/lab_arena.py` — Torneo de estrategias
- `python scripts/backtest/backtest_runner.py` — Backtest con scoring engine
- `python scripts/daily_report.py` — Reporte diario PnL
- `python bots/v12_shadow_bot.py` — Bot shadow independiente
- `python bots/v15_scalper.py` — Scalper 15min independiente

## Architecture
- `engines/` — 9 motores: alpha, backtest, data, execution, monitor, news, risk, scoring, telegram
- `api/server.py` — FastAPI dashboard (puerto 8080, auth X-API-Key)
- `config/settings.py` — Configuracion centralizada (.env overrides, TESTNET support)
- `db/database.py` — SQLite async WAL mode
- `scoring_ai/` — ML scoring (collector, scorer, auto_learn, vector_db.json)
- `utils/` — logger dual (consola+archivo), ssh_helper centralizado
- `scripts/` — 68+ scripts: lab/, deploy/ (9), diagnostics/ (15), backtest/ (2)
- `bots/` — Bots independientes (v12_shadow, v15_scalper)
- `web/index.html` — Dashboard interactivo (47KB)

## Project rules
- Leer ERRORES.md antes de empezar cualquier tarea
- Actualizar PROGRESS.md cuando una tarea quede completada
- TESTNET=true o EXCHANGE_SANDBOX=true en .env controla sandbox mode
- Nunca exponer API_KEY ni API_SECRET (solo nombres de keys, nunca valores)
- Retry con backoff exponencial para operaciones de exchange
- Risk engine: kill switch si drawdown > MAX_DAILY_DRAWDOWN
- No tocar training_data.csv sin backup previo
- Codigo en ingles, comentarios en espanol, commits en ingles

## Environment variables (keys only)
EXCHANGE_ID, EXCHANGE_SANDBOX, TESTNET, API_KEY, API_SECRET,
SYMBOL, SYMBOLS, TIMEFRAME, ACTIVE_STRATEGY, TRADING_MODE, CAPITAL,
DAILY_LOSS_LIMIT, MAX_DRAWDOWN_LIMIT, SLIPPAGE_MAX,
CRYPTOPANIC_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_PASS,
DASHBOARD_API_KEY

## Current state (2026-03-29)
- Sniper Rotativo operativo: vigila 5 monedas, compra la mejor senal, rota
- Scoring engine + backtest runner: validacion en testnet al 50%
- Pendiente: integrar scoring_engine en alpha_engine para decisiones en vivo
- Deploy: Hetzner CX43 (Ubuntu), /opt/ct4, systemd services ct4-bot y ct4-monitor

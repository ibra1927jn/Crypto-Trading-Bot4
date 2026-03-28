# Crypto-Trading-Bot4 — Bot de trading crypto

## Stack
Python 3.10+ + FastAPI + CCXT (async) + aiosqlite
WebSocket streaming (binance, mexc, kucoin, bybit)
Pandas + pandas-ta para indicadores tecnicos
Scoring AI: vector DB 20D + auto_learn daemon (60s cycle)

## Comandos
- `python main.py` — Inicia el bot principal (Sniper Rotativo, 5 monedas)
- `pytest tests/` — Tests (chaos network + exchange gaslighting)
- `python bots/v12_shadow_bot.py` — Bot shadow independiente
- `python bots/v15_scalper.py` — Scalper 15min independiente
- `python scripts/lab.py` — Backtest standard
- `python scripts/lab_arena.py` — Torneo de estrategias
- `python scripts/daily_report.py` — Reporte diario PnL
- `python scripts/backtest/backtest_runner.py` — Backtest con scoring engine
- `python -m engines.scoring_engine` — Test scoring engine (demo)

## Estructura clave
- engines/ — 9 motores core (alpha, backtest, data, execution, monitor, news, risk, scoring, telegram)
- engines/scoring_engine.py — Scoring basado en reglas (RSI, volumen, momentum, MACD, BB, ADX)
- api/server.py — FastAPI dashboard (puerto 8080, protegido con X-API-Key)
- config/settings.py — Configuracion centralizada (env overrides, TESTNET support)
- db/database.py — SQLite async WAL mode
- scoring_ai/ — ML scoring (collector, scorer, auto_learn, vector_db.json)
- utils/ssh_helper.py — Helper SSH centralizado (lee DEPLOY_* de .env)
- utils/logger.py — Logger dual (consola + archivo)
- scripts/deploy/ — Scripts de deploy, restart, fix (9 scripts)
- scripts/diagnostics/ — Scripts de diagnostico y fetch (15 scripts)
- scripts/backtest/ — Backtests (V12, V14 compare, backtest_runner con scoring)
- scripts/ — 68+ scripts de laboratorio
- bots/ — Bots independientes (v12_shadow_bot.py, v15_scalper.py)
- web/index.html — Dashboard interactivo (47KB)
- logs/ — Logs y archivos de estado

## Reglas del proyecto
- TESTNET=true o EXCHANGE_SANDBOX=true en .env controla testnet/sandbox mode
- Nunca exponer API_KEY ni API_SECRET
- Retry con backoff exponencial para operaciones de exchange
- Solo ordenes Market para entradas, OCO para salidas
- Risk engine: kill switch si drawdown > MAX_DAILY_DRAWDOWN
- Logs duales: consola + archivo (utils/logger.py)
- No tocar training_data.csv sin backup previo

## Variables de entorno (solo keys)
- EXCHANGE_ID, EXCHANGE_SANDBOX, TESTNET
- API_KEY, API_SECRET
- SYMBOL, SYMBOLS, TIMEFRAME
- ACTIVE_STRATEGY, TRADING_MODE, CAPITAL
- DAILY_LOSS_LIMIT, MAX_DRAWDOWN_LIMIT, SLIPPAGE_MAX
- CRYPTOPANIC_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_PASS
- DASHBOARD_API_KEY

## Deploy produccion
- Oracle Cloud VM (Ubuntu): systemd services ct4-bot y ct4-monitor
- Script: scripts/deploy_oracle.sh

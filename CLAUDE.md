# Crypto-Trading-Bot4 — Bot de trading crypto

## Stack
Python 3.10+ + FastAPI + CCXT (async) + aiosqlite
WebSocket streaming (binance, mexc, kucoin, bybit)
Pandas + pandas-ta para indicadores tecnicos
Scoring AI: vector DB 20D + auto_learn daemon (60s cycle)

## Comandos
- `python main.py` — Inicia el bot principal (Sniper Rotativo, 5 monedas)
- `pytest tests/` — Tests (chaos network + exchange gaslighting)
- `python v12_shadow_bot.py` — Bot shadow independiente
- `python v15_scalper.py` — Scalper 15min independiente
- `python scripts/lab.py` — Backtest standard
- `python scripts/lab_arena.py` — Torneo de estrategias
- `python scripts/daily_report.py` — Reporte diario PnL

## Estructura clave
- engines/ — 8 motores core (alpha, backtest, data, execution, monitor, news, risk, telegram)
- api/server.py — FastAPI dashboard (puerto 8080, protegido con X-API-Key)
- config/settings.py — Configuracion centralizada (env overrides)
- db/database.py — SQLite async WAL mode
- scoring_ai/ — ML scoring (collector, scorer, auto_learn, vector_db.json)
- utils/ssh_helper.py — Helper SSH centralizado (lee DEPLOY_* de .env)
- utils/logger.py — Logger dual (consola + archivo)
- scripts/deploy/ — Scripts de deploy, restart, fix (9 scripts)
- scripts/diagnostics/ — Scripts de diagnostico y fetch (15 scripts)
- scripts/backtest/ — Backtests remotos (V12, V14 compare)
- scripts/ — 68+ scripts de laboratorio
- bots/ — Bots independientes (preparado para v12_shadow_bot, v15_scalper)
- web/index.html — Dashboard interactivo (47KB)
- logs/ — Logs y archivos de estado

## Reglas del proyecto
- EXCHANGE_SANDBOX en .env controla si es testnet o live
- Nunca exponer API_KEY ni API_SECRET
- Retry con backoff exponencial para operaciones de exchange
- Solo ordenes Market para entradas, OCO para salidas
- Risk engine: kill switch si drawdown > MAX_DAILY_DRAWDOWN
- Logs duales: consola + archivo (utils/logger.py)
- No tocar training_data.csv sin backup previo

## Variables de entorno (solo keys)
- EXCHANGE_ID, EXCHANGE_SANDBOX
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

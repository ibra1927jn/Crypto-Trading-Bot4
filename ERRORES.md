# ERRORES.md — Lo que no volvemos a hacer

## Formato
[Fecha] | [Archivo afectado] | [Error] | [Fix aplicado]

---

## TypeScript
- [2026-03-27] | global | Usar ny en tipos → errores en runtime silenciosos
  FIX: tipar siempre explícitamente, especialmente payloads de DB

## Seguridad
- [2026-03-28] | deploy_v15.py, scripts/daily_report.py, scripts/test_telegram.py, scripts/telegram_monitor.py | Credenciales hardcodeadas (IP, password, Telegram token) en codigo fuente | Migrado a os.getenv() + dotenv. Quedan ~20 scripts mas con el mismo patron (check_*, deploy_*, diag_*, fetch_*, fix_*, etc.) — limpiar progresivamente
- [2026-03-28] | 22 scripts raiz (check_*, deploy_*, diag_*, fetch_*, fix_*, full_nuke, get_pnl, inspect_states, restart_*, test_api, upload_v15, backtest_v12, backtest_v14_compare) | Credenciales SSH hardcodeadas en cada script | Creado utils/ssh_helper.py centralizado. Todos los scripts migrados a usar get_ssh_client() con .env vars
- [2026-03-28] | api/server.py | Dashboard API sin autenticacion — cualquiera con la IP podia ver el estado del bot | Agregado middleware ApiKeyMiddleware que valida X-API-Key header. /api/health queda publico. DASHBOARD_API_KEY en .env

## Estabilización crítica (2026-03-28)
- [2026-03-28] | engines/execution_engine.py | _wait_for_fill usaba variable `symbol` sin recibirla como parámetro → NameError en runtime | Añadido param `symbol` a la firma y pasado desde execute_market_order
- [2026-03-28] | engines/execution_engine.py | _reconcile y get_balance usaban SYMBOL global en vez del símbolo de cada posición → reconciliación incorrecta en modo multi-coin | Cambiado a usar pos['symbol'] por posición y aceptar param symbol en get_balance
- [2026-03-28] | api/server.py | _calculate_equity referenciaba data_engine.current_price (no existe) → AttributeError | Cambiado a data_engine.current_prices.get(SYMBOL, 0) (dict multi-coin)
- [2026-03-28] | requirements.txt | Línea 3 tenía `fastapi>=0.110.0 ===` (malformado) → pip install fallaba | Limpiado a `fastapi>=0.110.0`
- [2026-03-28] | .gitignore | Archivo corrupto con encoding roto, faltaban reglas críticas | Reescrito con cobertura: __pycache__/, *.pyc, .env, db/*.db, *.csv, *.txt, scoring_ai/vector_db.json, build/

## Risk Management (2026-03-28)
- [2026-03-28] | config/settings.py | POSITION_RISK_PCT=0.90 (90% all-in) — 3-4 SL consecutivos activan kill switch, quemando el dia de trading | Reducido a 0.10 (10%) con override via env var. Supervivencia > agresividad
- [2026-03-28] | engines/alpha_engine.py, scoring_engine.py, backtest_engine.py | Sin filtro de tendencia — el bot compraba RSI oversold en tendencias bajistas (caida libre) | Agregado filtro EMA50 < EMA200*0.98 → score=0. Aplicado en alpha, scoring y backtest
- [2026-03-28] | engines/backtest_engine.py | Backtest ejecutaba a precio de cierre exacto sin slippage — resultados irreales vs live | Agregado SLIPPAGE_PCT=0.1% en entrada (+) y salida (-). Configurable via BACKTEST_SLIPPAGE env var

## General
- [TEMPLATE] | cualquier módulo | Marcar tarea como done sin tests
  FIX: tests en verde antes de actualizar PROGRESS.md

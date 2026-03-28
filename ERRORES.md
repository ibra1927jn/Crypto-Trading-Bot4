# ERRORES.md — Lo que no volvemos a hacer

## Formato
[Fecha] | [Archivo afectado] | [Error] | [Fix aplicado]

---

## TypeScript
- [2026-03-27] | global | Usar ny en tipos → errores en runtime silenciosos
  FIX: tipar siempre explícitamente, especialmente payloads de DB

## Seguridad
- [2026-03-28] | deploy_v15.py, scripts/daily_report.py, scripts/test_telegram.py, scripts/telegram_monitor.py | Credenciales hardcodeadas (IP, password, Telegram token) en codigo fuente | Migrado a os.getenv() + dotenv. Quedan ~20 scripts mas con el mismo patron (check_*, deploy_*, diag_*, fetch_*, fix_*, etc.) — limpiar progresivamente

## Estabilización crítica (2026-03-28)
- [2026-03-28] | engines/execution_engine.py | _wait_for_fill usaba variable `symbol` sin recibirla como parámetro → NameError en runtime | Añadido param `symbol` a la firma y pasado desde execute_market_order
- [2026-03-28] | engines/execution_engine.py | _reconcile y get_balance usaban SYMBOL global en vez del símbolo de cada posición → reconciliación incorrecta en modo multi-coin | Cambiado a usar pos['symbol'] por posición y aceptar param symbol en get_balance
- [2026-03-28] | api/server.py | _calculate_equity referenciaba data_engine.current_price (no existe) → AttributeError | Cambiado a data_engine.current_prices.get(SYMBOL, 0) (dict multi-coin)
- [2026-03-28] | requirements.txt | Línea 3 tenía `fastapi>=0.110.0 ===` (malformado) → pip install fallaba | Limpiado a `fastapi>=0.110.0`
- [2026-03-28] | .gitignore | Archivo corrupto con encoding roto, faltaban reglas críticas | Reescrito con cobertura: __pycache__/, *.pyc, .env, db/*.db, *.csv, *.txt, scoring_ai/vector_db.json, build/

## General
- [TEMPLATE] | cualquier módulo | Marcar tarea como done sin tests
  FIX: tests en verde antes de actualizar PROGRESS.md

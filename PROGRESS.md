---
# PROGRESS.md — Crypto-Trading-Bot4

## En curso
- [2026-03-28] | Validacion scoring_engine + backtest_runner en testnet | 50%

## Completado
- [2026-03-28] | Limpieza credenciales: deploy_v15.py, daily_report.py, test_telegram.py, telegram_monitor.py migrados a env vars
- [2026-03-28] | Estabilizacion critica: 5 bugs corregidos (ver ERRORES.md)
- [2026-03-28] | SSH helper centralizado: utils/ssh_helper.py creado. 22 scripts migrados
- [2026-03-28] | Auth API dashboard: middleware X-API-Key en api/server.py
- [2026-03-28] | Reorganizacion scripts: copias creadas en scripts/deploy/ (9), scripts/diagnostics/ (15), scripts/backtest/ (2)
- [2026-03-28] | Borrar scripts duplicados en raiz — 10 scripts eliminados + 12 archivos output limpiados
- [2026-03-28] | Mover bots a bots/ — v12_shadow_bot.py y v15_scalper.py movidos
- [2026-03-28] | TESTNET support — TESTNET=true en .env.example, set_sandbox_mode() en execution_engine
- [2026-03-28] | Scoring Engine — engines/scoring_engine.py (reglas ponderadas: RSI, volumen, momentum, MACD, BB, ADX)
- [2026-03-28] | Backtest Runner — scripts/backtest/backtest_runner.py (PnL, win rate, drawdown, Sharpe, JSON output)
- [2026-03-28] | .gitignore reparado (estaba corrupto con encoding roto)

## Pendiente
- Ejecucion completa con agentes de IA autonomos | Prioridad: baja
- Actualizacion de paquetes | Prioridad: baja
- Integrar scoring_engine en alpha_engine para decisiones en vivo | Prioridad: alta
- CI/CD local (Ollama + Claude Code) | Prioridad: media

## Bloqueado

---

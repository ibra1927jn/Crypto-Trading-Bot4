---
# PROGRESS.md — Crypto-Trading-Bot4

## Estado actual
[El proyecto principal está en fase de despliegue local o migración. Las funciones core están estables pero faltan integraciones finales.]

## Completado ✅
- Estructura base completada.
- Archivos iniciales configurados.
- [2026-03-28] | Limpieza credenciales: deploy_v15.py, daily_report.py, test_telegram.py, telegram_monitor.py migrados a env vars
- [2026-03-28] | Estabilización crítica: 5 bugs corregidos (ver ERRORES.md) — _wait_for_fill param, _reconcile/get_balance multi-coin, server.py current_prices, requirements.txt malformado, .gitignore corrupto
- [2026-03-28] | SSH helper centralizado: utils/ssh_helper.py creado. 22 scripts migrados de credenciales hardcodeadas a get_ssh_client() + .env
- [2026-03-28] | Auth API dashboard: middleware X-API-Key en api/server.py, /api/health publico, DASHBOARD_API_KEY en .env.example
- [2026-03-28] | Reorganización scripts: copias creadas en scripts/deploy/ (9 scripts), scripts/diagnostics/ (15 scripts), scripts/backtest/ (2 scripts), bots/ (dir preparado)

## En progreso 🔄
- Implementación de CI/CD local en AgenticOS (Ollama + Claude Code).
- Limpieza de contexto.
- [2026-03-28] | Borrar scripts duplicados en raíz (originales ya copiados a scripts/*) | 75% — falta ejecutar `rm` de los originales

## Pendiente ⏳
- Ejecución completa con agentes de IA autónomos.
- Actualización de paquetes.
- Borrar originales de raíz tras confirmar que las copias en scripts/* funcionan | Prioridad: alta
- Mover v12_shadow_bot.py y v15_scalper.py a bots/ | Prioridad: media

## Bloqueado 🚫

---

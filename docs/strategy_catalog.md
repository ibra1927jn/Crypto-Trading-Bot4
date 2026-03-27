# 📋 CT4 Strategy Catalog — Testnet Deployments

> **Última actualización**: 16 Mar 2026  
> **Servidor testnet**: 95.217.156.7:8060

---

## Estado Rápido

| Estrategia | Estado | WR% | PnL | Notas |
|:---|:---:|:---:|:---:|:---|
| **V7 CAUTIOUS (72% WR)** | ✅ RESTAURADA | 72.4% | +$1.17 | Config ganadora Mar 10-11 |
| V7 NORMAL (28% WR) | ❌ RETIRADA | 28.5% | -$3.08 | Colapsó Mar 11-16 |
| Lab: HOUR_FILTER | 🧪 LAB ONLY | ~55% | +$2.90 | Skip horas 04-08 UTC |
| Lab: CANDLE_PAT | 🧪 LAB ONLY | ~52% | +$2.86 | Patrones vela en scoring |
| Lab: CORR_FILTER | 🧪 LAB ONLY | ~53% | +$2.38 | Max 1 pos/grupo |
| Lab: ULTRA_V3 | 🧪 LAB ONLY | — | — | Combina todos los features |
| v2: AllIn RSI<15 | 📦 ARCHIVADA | 67% | +$29.9 | Solo BONK, bear market |
| v2: MomBurst+ | 📦 ARCHIVADA | 51% | +$25.6 | Solo SAND, momentum |
| v2: Combo Killer | 📦 ARCHIVADA | — | +$10.5 | FIL/APT, baja DD |

---

## Fase 1: Battle Royale (v1) — BTC 5min
*Scripts: `lab.py`, `lab_best_report.py`*

| Estrategia | Enfoque | Periodo | Resultado |
|:---|:---|:---|:---|
| Momentum Adaptativa | RSI rebote + EMA200 + ADX | 3.5 días BTC | 🥇 +1.74% |
| Mean Reversion BB | Bollinger < 0.15 + Vol | 3.5 días BTC | 🥈 +0.66% |
| Grid Trading | Compra/venta en rangos | 3.5 días BTC | 🥉 +0.31% |
| Multi-Asset Rotation | Rotar entre coins | 3.5 días BTC | 💀 -0.48% |

**Status**: 📦 Todas archivadas — testnet basadas en BTC 5m, no extrapolables.

---

## Fase 2: Walk-Forward Test Ciego (v2)
*Script: `lab_blind_test.py`*

8 estrategias testeadas con split In-Sample/Out-of-Sample en BTC 5m testnet.

| Estrategia | In-Sample | OOS | Veredicto |
|:---|:---:|:---:|:---|
| A. Original V1 | — | — | Pocas señales |
| B. Momentum V2 | ✅ | ✅ | ✅ REAL |
| C. V2.1 Producción ★ | ✅ | ✅ | ✅ REAL (con trailing) |
| D. Bollinger Bounce | — | — | Variable |
| E. BB Squeeze | — | — | Breakout, pocas señales |
| F. MACD Momentum | — | — | Variable |
| G. Stochastic RSI | — | — | Variable |
| H. Ultimate V2 | ✅ | ✅ | ✅ REAL (adaptativo) |

**Status**: 📦 Archivadas — usaban BTC testnet 5m con capital $10K.

---

## Fase 3: Real Data Validation (6 meses mainnet)
*Script: `lab_real_data.py` — 120 combinaciones (10 estrategias × 12 coins)*

| Estrategia | Avg PnL (3m) | Mejor Coin | Status |
|:---|:---:|:---|:---|
| **AllIn RSI<15** | -$1.3 avg | BONK: **+$29.9 (+30%)** 🏆 | 📦 Archivada |
| **MomBurst+** | -$1.0 avg | SAND: **+$25.6 (+26%)** | 📦 Archivada |
| Combo Killer | -$5.2 avg | FIL: +$10.5 | 📦 Archivada |
| BB Agresivo | -$9.7 avg | — | 💀 Muerta |
| Breakout | -$34.8 avg | — | 💀 Muerta |

**Config AllIn RSI<15** (la mejor de v2):
```
Entry: RSI_14 < 15 + RSI rebotando + Price > EMA50 × 0.95
Position: 80% del capital
SL: -4.0% | TP: +8.0% | Trail: 2.0%
Exit: RSI > 70 ó EMA5 < EMA13
```

**Status**: 📦 Archivadas — no son compatibles con el monitor dual-direction V7.

---

## Fase 4: Monitor Server V7 — Configs Desplegadas

### ✅ CONFIG A: "CAUTIOUS 72%" — RESTAURADA
*Desplegada: 10-11 Mar 2026 | Retirada: ~12 Mar | Restaurada: 16 Mar*

```python
# MODES
fear:    min_score=55, tp=5.0%, sl=3.0%     # ← Config ganadora
normal:  min_score=50, tp=3.0%, sl=2.0%
greed:   min_score=45, tp=2.0%, sl=1.5%

# RISK
EMA_OVERRIDE_SCORE = 70
TRAILING_TRIGGER   = 1.5     # Activar trailing temprano
MAX_POSITIONS      = 3
AMOUNT/TRADE       = $10 fijo (CAPITAL/MAX_POSITIONS)  # ← FIXED (era 95% balance)
TIMEOUT_HOURS      = 4
TIMEOUT_MIN_GAIN   = 0.5%
COOLDOWN_MIN       = 30
MAX_SL_STRIKES     = 2
SL_BAN_HOURS       = 2
```

**Resultados** (29 trades, Mar 10 04:04 → Mar 11 00:12):
- **WR: 72.4%** (21W / 8L) 🔥
- PnL: +$1.17 | Equity: $31.17
- Trailing: 16/29 trades (55%) cerraron por trailing → **+$2.94**
- TPs: 2 trades → +$0.99
- SLs: 8 trades → -$2.89
- 90% trades fueron **shorts** (mercado Fear)

---

### ❌ CONFIG B: "NORMAL 28%" — RETIRADA
*Desplegada: ~12-16 Mar 2026*

```python
fear:    min_score=55, tp=5.0%, sl=2.0%     # SL más tight
normal:  min_score=50, tp=3.0%, sl=2.0%     # ← Se activó este modo
greed:   min_score=45, tp=2.0%, sl=1.5%

TRAILING_TRIGGER = 2.5       # Trailing más lento
AMOUNT/TRADE     = balance / slots_free * 0.95  # ← SUICIDA
```

**Resultados** (35 trades total, Mar 10 → Mar 16):
- **WR: 28.5%** (10W / 25L) 💀
- PnL: -$3.08 | Balance: $0.45
- Max DD: 70.6%

**¿Por qué falló?** El SL 2% era demasiado tight + trailing tardío + position sizing consumía todo el balance.

---

## Fase 5: Lab Arena — Perfiles Testeados (Backtest)
*Script: `lab_arena.py` — 30 días, 8 coins, $30 capital*

| Perfil | Config Clave | PnL | Trades |
|:---|:---|:---:|:---:|
| 🥇 **HOUR_FILTER** | Skip horas 04-08 UTC | **+$2.90** | 32 |
| 🥈 **CANDLE_PAT** | Patterns en scoring | **+$2.86** | 55 |
| 🥉 **CORR_FILTER** | Max 1 pos/grupo | **+$2.38** | 34 |
| BASELINE | sl=2, tp=5, score=55 | +$2.36 | ~35 |
| CONF_SIZING | $8/$12 por score | +$2.06 | ~35 |
| DYNAMIC_TP | TP basado en ATR | +$1.94 | 36 |
| AUTO_BAN | Ban tras 3 SLs | — | — |
| 🏆 ULTRA_V3 | Combina todo | — | — |

**Status**: 🧪 Ninguno desplegado en testnet aún.

**Candidatos para próximo deploy**:
1. **HOUR_FILTER** — Simple, +23% mejor que baseline
2. **CANDLE_PAT** — Más trades, +21% mejor que baseline

---

## Próximos Pasos

- [ ] Desplegar CONFIG A restaurada al servidor
- [ ] Monitorear 48h para validar WR > 60%
- [ ] Si se estabiliza, añadir HOUR_FILTER (skip 04-08 UTC)
- [ ] Testear CANDLE_PAT en lab con más datos (90 días)
- [ ] Considerar subir EMA_OVERRIDE_SCORE a 85

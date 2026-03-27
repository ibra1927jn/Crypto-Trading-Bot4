# 🤖 Scoring AI v2 — 20-Dimension Risk Intelligence

**Version:** 2.0  
**Status:** Standalone module — does NOT modify the trading bot  
**Requires:** Python 3.10+, NumPy, Pandas

---

## What's New in v2

| Feature | v1 | v2 |
|---|---|---|
| Vector dimensions | 9 | **20** |
| Similarity engine | Basic cosine | **Weighted cosine + euclidean composite** |
| Feature weighting | None | **Per-dimension weights** (RSI, F&G, regime = 2x) |
| Normalization | None | **Min-max [0,1] normalization** |
| Market regime | None | **Bull/Bear/Lateral auto-detect** |
| Bollinger position | None | **0-1 band position** |
| MACD momentum | None | **Normalized histogram** |
| Time patterns | None | **Hour + day of week** |
| News sentiment | None | **Placeholder (Phase 3)** |
| Risk thresholds | 40/60/80 | **30/50/70** (more sensitive) |

---

## Vector Dimensions (20)

| # | Name | Range | Weight | Description |
|---|---|---|---|---|
| 0 | `adx` | 0-80 | 1.5x | Trend strength |
| 1 | `rsi` | 0-100 | **2.0x** | RSI 14 — top predictor |
| 2 | `atr_pct` | 0-15% | 1.5x | Volatility (ATR/Price) |
| 3 | `ema50_dist` | -20/+20% | 1.2x | Distance to EMA50 |
| 4 | `ema200_dist` | -40/+40% | 1.0x | Distance to EMA200 |
| 5 | `btc_corr` | 0-1 | 1.8x | BTC correlation |
| 6 | `volume_ratio` | 0-5 | 1.3x | Volume vs 20-MA |
| 7 | `side_int` | ±1 | **2.5x** | LONG(+1) vs SHORT(-1) |
| 8 | `hold_hours` | 0-200 | 0.5x | Position duration |
| 9 | `funding_rate` | ±0.1 | 1.8x | Crowd positioning |
| 10 | `oi_change_pct` | ±50% | 1.5x | Open interest change |
| 11 | `hour_of_day` | 0-23 | 0.8x | Trading hour |
| 12 | `day_of_week` | 0-6 | 0.5x | Day of week |
| 13 | `fear_greed` | 0-100 | **2.0x** | Market sentiment |
| 14 | `btc_dominance` | 40-70% | 1.0x | Alt season indicator |
| 15 | `market_regime` | -1/0/+1 | **2.5x** | Bull/Bear/Lateral |
| 16 | `bb_position` | 0-1 | 1.2x | Bollinger Band position |
| 17 | `macd_hist_norm` | -1/+1 | 1.0x | Momentum direction |
| 18 | `consec_candles` | -5/+5 | 1.0x | Green/red streak |
| 19 | `news_sentiment` | -1/+1 | 1.5x | News sentiment (Phase 3) |

---

## Risk Scale

| Score | Verdict | Action | Size Multiplier |
|---|---|---|---|
| 0-29 | 🟢 SAFE | Full position | 100% |
| 30-49 | 🟡 CAUTION | Reduce 25% | 75% |
| 50-69 | 🟠 RISKY | Reduce 50% | 50% |
| 70-100 | 🔴 VETO | Skip trade | 0% |

---

## Usage

### 1. Rebuild vector database
```bash
python scoring_ai/collector.py --csv scoring_ai/training_data.csv
```

### 2. Score a trade signal
```bash
# Safe scenario: oversold RSI in bull market
python scoring_ai/scorer.py --preset demo

# Risky scenario: overbought in extreme fear
python scoring_ai/scorer.py --preset risky

# Custom signal
python scoring_ai/scorer.py --adx 22 --rsi 65 --side LONG --fear_greed 25 --market_regime 1
```

### 3. Generate fresh training data (runs on Hetzner, ~6 min)
```bash
python generate_multi_strategy.py
python scoring_ai/collector.py --csv scoring_ai/training_data.csv
```

---

## Architecture

```
scoring_ai/
├── collector.py       # Builds 20-dim vector DB from trade CSV
├── similarity.py      # Weighted cosine + euclidean composite engine
├── scorer.py          # Risk assessment 0-100
├── report.py          # HTML visualization
├── vector_db.json     # Generated database (9,596 trades)
├── training_data.csv  # Multi-strategy training data
└── README.md          # This file
```

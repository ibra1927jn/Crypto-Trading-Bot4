<p align="center">
  <h1>🎯 CT4 — Crypto Trading Bot v4</h1>
  <p><b>Quantitative Sniper Strategy • RSI Pullback • Binance Testnet</b></p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Exchange-Binance_Testnet-yellow?logo=binance" alt="Binance">
  <img src="https://img.shields.io/badge/Strategy-RSI35_Pullback-green" alt="Strategy">
  <img src="https://img.shields.io/badge/Status-Live_Testing-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/Dashboard-Premium_v4-purple" alt="Dashboard">
</p>

---

## 📖 Overview

CT4 is an algorithmic trading bot designed for BTC/USDT on Binance Testnet. It implements a **"Sniper" RSI Pullback** strategy that only opens long positions when **all 4 confluence laws** are met simultaneously, ensuring extremely high-probability entries.

The bot runs 24/7, monitoring the market via WebSocket, evaluating conditions every 5-minute candle, and executing trades when the moment is perfect.

### Philosophy: The Sniper 🎯
>
> *"A sniper doesn't shoot at everything that moves. They wait for the perfect shot."*

The bot rejects 95%+ of market conditions. It only fires when 4 independent filters align — this is **by design**, not a bug.

---

## ⚡ The 4 Laws of the Sniper

Every trade must pass **all 4 laws** before execution:

| # | Law | Condition | Purpose |
|---|-----|-----------|---------|
| 🌊 | **La Marea** | Price > EMA 200 | Only trade WITH the macro uptrend |
| 💪 | **La Fuerza** | ADX > 20 | Confirm a real trend (not sideways) |
| 🐋 | **Las Ballenas** | Volume > SMA(20) | Ensure institutional participation |
| 🩸 | **El Pullback** | RSI < 35 + Bounce | Buy the dip, not the crash |

When all 4 lights are green → **FIRE**. Otherwise → **WAIT**.

---

## 🏗️ Architecture

```
CT4/
├── main.py                 # Entry point — orchestrator
├── config/
│   └── settings.py         # Strategy parameters & thresholds
├── engines/
│   ├── data_engine.py      # WebSocket + REST candle data
│   ├── alpha_engine.py     # Strategy logic (4 Laws evaluation)
│   ├── execution_engine.py # Order placement (Market + SL/TP)
│   ├── risk_engine.py      # Position sizing, drawdown, kill switch
│   └── backtest_engine.py  # Historical backtesting framework
├── api/
│   └── server.py           # HTTP API + static dashboard
├── web/
│   └── index.html          # Premium dashboard (glassmorphism UI)
├── db/
│   └── database.py         # SQLite persistence (trades, state)
├── scripts/
│   ├── telegram_monitor.py # Real-time Telegram alerts
│   ├── daily_report.py     # Periodic performance reports
│   ├── lab.py              # Backtesting laboratory
│   └── lab_extended.py     # Extended parameter sweeps
├── tests/
│   ├── chaos_network_test.py    # Network failure simulation
│   └── demon3_gaslighting_test.py # Exchange error injection
├── utils/
│   └── logger.py           # Structured logging with colors
└── requirements.txt
```

---

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone <repo-url>
cd Crypto-Trading-Bot4
python -m venv venv
.\venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your Binance Testnet API keys:

```env
BINANCE_API_KEY=your_testnet_api_key
BINANCE_API_SECRET=your_testnet_api_secret
BINANCE_TESTNET=true
```

> 🔑 Get testnet keys at: <https://testnet.binance.vision/>

### 3. Run the Bot

```bash
python main.py
```

The bot will:

1. 🔗 Connect to Binance Testnet
2. 📊 Download 250 historical candles (warm-up)
3. 🔌 Establish WebSocket for real-time data
4. 📡 Start dashboard at `http://localhost:8080`
5. 🎯 Begin evaluating every 5-minute candle

### 4. Open Dashboard

Navigate to **<http://localhost:8080>** in your browser.

---

## 📊 Dashboard

The dashboard is a **premium-grade trading terminal** with:

- **Score Strip** — BTC price, Equity, Drawdown, Signals, Kill Switch
- **SVG Sparkline Chart** — Live price with EMA200 reference line
- **RSI Gauge** — Circular indicator with zone alerts
- **4 Laws Panel** — Real-time status of each law
- **Distance Bars** — How close each condition is to triggering
- **Indicators** — EMA 9/21/200, ADX, RSI, ATR, Volume
- **Risk Engine** — USDT balance, BTC holdings, equity bar
- **Trade History** — Detailed entries with timestamps and PnL

Mobile-responsive layout adapts to all screen sizes.

---

## 📱 Telegram Alerts

Real-time notifications on your phone:

```bash
python scripts/telegram_monitor.py
```

### Alert Types

| Alert | When |
|-------|------|
| 🟢 **Online** | Monitor starts |
| 🎯 **Signal** | Trade executed |
| ⚡ **Laws Change** | 3/4 or 4/4 activated |
| 🚨 **Kill Switch** | Emergency stop triggered |
| 💣 **Volatility** | ATR spikes 3× |
| 📊 **Hourly Report** | Every 60 min summary |
| 🔴 **Offline** | Bot disconnected |

### Setup

1. Create a bot via `@BotFather` on Telegram
2. Get your Chat ID from `@userinfobot`
3. Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in the script or `.env`

---

## 📊 Auto-Reports

Generate comprehensive performance reports:

```bash
# One-shot report
python scripts/daily_report.py

# Auto-report every 6 hours
python scripts/daily_report.py --loop
```

Reports include: Market data, Portfolio PnL, Law status, Trade history, System health.

---

## 🛡️ Risk Management

| Feature | Value |
|---------|-------|
| **Position Size** | 30% of free USDT |
| **Stop Loss** | 1.5× ATR below entry |
| **Take Profit** | 3.0× ATR above entry (2:1 RR) |
| **Max Drawdown** | 5% → Kill Switch |
| **Max Open** | 1 position at a time |
| **Kill Switch** | Auto-halt if drawdown > 5% |

---

## 🔬 Backtesting Lab

Run historical simulations:

```bash
python scripts/lab.py           # Standard parameter sweep
python scripts/lab_extended.py  # Extended analysis
```

> ⚠️ **Warning**: Over-optimization (curve fitting) is the #1 risk. The lab is for validation, not for finding "magic numbers". See the [Quant Rules](#-quant-rules) section.

---

## ⚠️ Quant Rules

Rules to prevent self-deception:

1. **No Curve Fitting** — Don't torture the data to find a "perfect" strategy
2. **Walk-Forward Validation** — Test on unseen data before deploying
3. **Orthogonal Strategies** — Each new strategy must use different signals
4. **Suspicion Protocol** — If Sharpe > 2.0 on backtest, it's probably fake
5. **One Change at a Time** — Never change multiple parameters simultaneously
6. **Friday Review** — Weekly review of live performance vs backtest

---

## 🧪 Testing

### Chaos Tests (Network)

```bash
python tests/chaos_network_test.py
```

Simulates: API timeouts, WebSocket drops, exchange errors, rate limiting.

### Gaslighting Tests (Exchange)

```bash
python tests/demon3_gaslighting_test.py
```

Simulates: Phantom fills, order rejections, balance discrepancies.

---

## ⚙️ Configuration

Key parameters in `config/settings.py`:

```python
SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"
RSI_PERIOD = 14
RSI_THRESHOLD = 35
ADX_THRESHOLD = 20
EMA_PERIOD = 200
POSITION_SIZE_PCT = 0.30
SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0
MAX_DRAWDOWN = 0.05
```

---

## 📋 Dependencies

```
ccxt>=4.0         # Exchange connectivity
aiohttp>=3.9      # Async HTTP + WebSocket
websockets>=12.0  # WebSocket client
aiosqlite>=0.20   # Async SQLite
pandas>=2.0       # Data manipulation
numpy>=1.26       # Numerical computing
```

---

## 🗺️ Roadmap

- [x] V1: RSI Pullback strategy (live)
- [x] Premium dashboard with sparkline chart
- [x] Telegram real-time alerts
- [x] Auto-report system
- [x] Chaos & gaslighting test suites
- [ ] SHORT strategy (RSI > 65 + Down trend)
- [ ] StochRSI Momentum strategy (V2)
- [ ] Pendulum mean-reversion strategy (V3)
- [ ] Multi-bot tournament framework
- [ ] Mainnet deployment

---

## 📄 License

Educational and personal use. Not financial advice. Trading cryptocurrency involves significant risk.

---

<p align="center">
  <b>Built with 🎯 precision and ☕ coffee</b><br>
  <sub>CT4 Quant Terminal v1.0 — RSI Pullback Strategy</sub>
</p>

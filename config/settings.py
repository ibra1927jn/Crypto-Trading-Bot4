"""
Crypto-Trading-Bot4 — Configuración Centralizada v3 (Sniper Rotativo)
======================================================================
Vigila 5 monedas, pone TODO en la mejor señal, cierra, rota.
Estrategia RSI7<25 validada en lab con datos reales.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

# --- RUTA BASE DEL PROYECTO ---
BASE_DIR = Path(__file__).resolve().parent.parent

# --- EXCHANGE ---
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance")
# TESTNET y EXCHANGE_SANDBOX son sinonimos — cualquiera activa sandbox mode
_testnet = os.getenv("TESTNET", "").lower() == "true"
_sandbox = os.getenv("EXCHANGE_SANDBOX", "true").lower() == "true"
EXCHANGE_SANDBOX = _testnet or _sandbox

# --- CREDENCIALES ---
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")

# --- PARÁMETROS DE MERCADO (Sniper Rotativo) ---
# 5 monedas validadas en lab agresivo + francotirador
SYMBOLS = os.getenv("SYMBOLS", "XRP/USDT,DOGE/USDT,AVAX/USDT,SHIB/USDT,SOL/USDT").split(",")
SYMBOL = SYMBOLS[0]  # Compatibilidad con código antiguo
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
WARMUP_CANDLES = 250

# --- ESTRATEGIAS DISPONIBLES ---
# Validadas con datos REALES (Sep 2025 → Mar 2026):
#   AllIn RSI<15:  BONK +$30, NEAR +$18, TIA +$5.5
#   MomBurst+:     SAND +$26, DOGE +$14.5
ACTIVE_STRATEGY = os.getenv("ACTIVE_STRATEGY", "ALLIN_RSI")  # ALLIN_RSI | MOMBURST | COMBO

# --- REGLAS DEL RISK ENGINE ---
POSITION_RISK_PCT = 0.90      # 90% all-in en la mejor señal (Sniper Rotativo)
MAX_DAILY_DRAWDOWN = 0.10     # Kill Switch: apagar si perdemos >10% en un día
MAX_CONSECUTIVE_ERRORS = 5
ATR_PERIOD = 14
ADX_PERIOD = 14
ADX_THRESHOLD = 15

# --- ESTRATEGIA: RSI7<25→30 Sniper (Optimizada) ---
RSI_EXTREME_THRESHOLD = 30    # RSI7 < 30 → compra (sweep óptimo: 13 trades, 62% WR)
RSI_EXIT_THRESHOLD = 70       # RSI > 70 → venta
SL_PCT = -3.0                 # Stop Loss: -3% (R:R 1:1.67)
TP_PCT = 5.0                  # Take Profit: +5%
TRAIL_PCT = 2.0               # Trailing stop: 2%

# --- ESTRATEGIA: MomBurst+ ---
MOMBURST_CANDLE_PCT = 0.8     # Vela verde > 0.8%
MOMBURST_VOL_RATIO = 2.5      # Volumen 2.5x sobre media
MOMBURST_SL_PCT = -2.0        # SL más ajustado para momentum
MOMBURST_TP_PCT = 4.0         # TP más rápido

# --- BOLLINGER BANDS (para análisis) ---
BB_PERIOD = 20
BB_STD = 2
BB_ENTRY_PCT = 0.15
BB_EXIT_PCT = 0.95

# --- COMPATIBILIDAD (legacy) ---
LONG_ENABLED = True
SHORT_ENABLED = False
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
RSI_SHORT_EXIT = 50
LONG_SL_ATR_MULT = 1.5
LONG_TP_ATR_MULT = 3.0
SHORT_SL_ATR_MULT = 1.5
SHORT_TP_ATR_MULT = 3.0

# --- EJECUCIÓN ---
MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0

# --- RUTAS ---
DB_PATH = str(BASE_DIR / "db" / "bot_database.db")
LOG_DIR = str(BASE_DIR / "logs")

# --- WEBSOCKET ---
WS_URLS = {
    'binance': 'wss://stream.binance.com:9443/ws',
    'binance_testnet': 'wss://stream.testnet.binance.vision/ws',
    'mexc': 'wss://wbs.mexc.com/ws',
    'kucoin': 'wss://ws-api-spot.kucoin.com',
}

BINANCE_WS_BASE = WS_URLS.get(
    f"{EXCHANGE_ID}_testnet" if EXCHANGE_SANDBOX else EXCHANGE_ID,
    WS_URLS['binance_testnet']
)

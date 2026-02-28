"""
Crypto-Trading-Bot4 — Configuración Centralizada
=================================================
Todas las variables de calibración del bot viven aquí.
Cero números mágicos sueltos en el código.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

# --- RUTA BASE DEL PROYECTO ---
BASE_DIR = Path(__file__).resolve().parent.parent

# --- EXCHANGE ---
# Exchanges sin KYC para trading real: MEXC, KuCoin, Bybit
# Para testnet usamos Binance (no requiere KYC)
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance")
EXCHANGE_SANDBOX = os.getenv("EXCHANGE_SANDBOX", "true").lower() == "true"

# --- CREDENCIALES ---
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")

# --- PARÁMETROS DE MERCADO ---
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
WARMUP_CANDLES = 250          # Velas históricas (mínimo 200 para EMA 200)

# --- REGLAS DEL RISK ENGINE ---
POSITION_RISK_PCT = 0.01     # Arriesgar max 1% del capital por operación
MAX_DAILY_DRAWDOWN = 0.05    # Kill Switch: apagar si perdemos >5% en un día
MAX_CONSECUTIVE_ERRORS = 5   # Kill Switch: apagar tras 5 errores de API seguidos
ATR_PERIOD = 14              # Período del ATR para SL dinámico
ADX_PERIOD = 14              # Período del ADX para filtro de tendencia
ADX_THRESHOLD = 25           # ADX mínimo para considerar que hay tendencia

# --- EJECUCIÓN ---
MAX_RETRIES = 5              # Reintentos con backoff exponencial
RETRY_BASE_DELAY = 1.0       # Delay inicial en segundos (1s, 2s, 4s, 8s, 16s)

# --- RUTAS DE INFRAESTRUCTURA ---
DB_PATH = str(BASE_DIR / "db" / "bot_database.db")
LOG_DIR = str(BASE_DIR / "logs")

# --- WEBSOCKET ---
# URLs de WebSocket por exchange (se selecciona automáticamente)
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

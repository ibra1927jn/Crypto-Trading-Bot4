#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv
import asyncio
import logging
import colorlog
from datetime import datetime
import ccxt.async_support as ccxt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, '.env'), override=True)

SYMBOLS = [s.strip() for s in os.getenv('TRADING_SYMBOLS', 'BTC/USDT').split(',')]
API_KEY = os.getenv('BINANCE_API_KEY')
SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from modules.data_manager import DataManager
from modules.indicators import TechnicalIndicators
from modules.ai_predictor import AI_Predictor
from strategies.strategy import HybridStrategy

def setup_logging():
    formatter = colorlog.ColoredFormatter("%(log_color)s%(asctime)s %(levelname)s: %(message)s", datefmt='%H:%M:%S', log_colors={'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red'})
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger

logger = setup_logging()
logger.info("=" * 50)
logger.info("RADAR IA ACTIVADO")
logger.info("=" * 50)

class CryptoRadar:
    def __init__(self):
        self.managers = {}
        self.timeframe = os.getenv('TIMEFRAME', '1m')

    async def initialize(self):
        self.exchange = ccxt.binance({
            'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        # Parche URLs
        base = 'https://testnet.binancefuture.com'
        self.exchange.urls['api'] = {k: f'{base}/fapi/v1' for k in ['fapiPublic','fapiPrivate','public','private']}
        self.exchange.urls['api'].update({'sapi': f'{base}/sapi/v1', 'dapiPublic': f'{base}/dapi/v1', 'dapiPrivate': f'{base}/dapi/v1'})
        
        await self.exchange.load_markets()
        logger.info("✅ CONEXIÓN EXITOSA")
        
        self.indicators = TechnicalIndicators({})
        self.ai_predictor = AI_Predictor({})
        
        self.strategies = {}
        for sym in SYMBOLS:
            mgr = DataManager(self.exchange, sym, self.timeframe, historical_bars=300)
            self.managers[sym] = mgr
            self.strategies[sym] = HybridStrategy(mgr, self.indicators, self.ai_predictor, {})
        return True

    async def run(self):
        logger.info(f"🟢 RADAR GIRANDO ({len(SYMBOLS)} Pares)...")
        while True:
            try:
                await self._scan()
                logger.info("⏳ Esperando 60s...")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(5)

    async def _scan(self):
        logger.info(f"\n📡 --- {datetime.now().strftime('%H:%M:%S')} ---")
        for symbol in SYMBOLS:
            try:
                mgr = self.managers[symbol]
                await mgr.update_data()
                df = mgr.get_latest_data()
                if df is None or len(df) < 200: continue

                df = self.indicators.calculate_all(df)
                price = df['close'].iloc[-1]

                signal, _, _ = self.strategies[symbol].get_signal(df)
                
                icon = "🟢" if signal.value == "BUY" else "🔴" if signal.value == "SELL" else "⚪"
                logger.info(f"{icon} {symbol:<10} ${price:<10.2f} | Señal: {signal.value}")
            except Exception as e:
                logger.error(f"Error {symbol}: {e}")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    radar = CryptoRadar()
    if loop.run_until_complete(radar.initialize()):
        try: loop.run_until_complete(radar.run())
        except KeyboardInterrupt: pass
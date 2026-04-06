#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
from datetime import datetime

import ccxt.async_support as ccxt
import colorlog
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, '.env'), override=True)

SYMBOLS = [
    s.strip()
    for s in os.getenv('TRADING_SYMBOLS', 'BTC/USDT').split(',')
]
API_KEY = os.getenv('BINANCE_API_KEY')
SECRET_KEY = os.getenv('BINANCE_API_SECRET')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from modules.ai_predictor import AI_Predictor  # noqa: E402
from modules.data_manager import DataManager  # noqa: E402
from modules.indicators import TechnicalIndicators  # noqa: E402
from strategies.strategy import HybridStrategy  # noqa: E402


def setup_logging():
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s %(levelname)s: %(message)s",
        datefmt='%H:%M:%S',
        log_colors={'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red'},
    )
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
        self.exchange.urls['api'] = {
            k: f'{base}/fapi/v1'
            for k in ['fapiPublic', 'fapiPrivate', 'public', 'private']
        }
        self.exchange.urls['api'].update({
            'sapi': f'{base}/sapi/v1',
            'dapiPublic': f'{base}/dapi/v1',
            'dapiPrivate': f'{base}/dapi/v1',
        })

        await self.exchange.load_markets()
        logger.info("✅ CONEXIÓN EXITOSA")

        self.indicators = TechnicalIndicators({})
        self.ai_predictor = AI_Predictor({})

        self.strategies = {}
        for sym in SYMBOLS:
            mgr = DataManager(
                self.exchange, sym, self.timeframe,
                historical_bars=300,
            )
            self.managers[sym] = mgr
            self.strategies[sym] = HybridStrategy(
                mgr, self.indicators, self.ai_predictor, {}
            )
        return True

    async def run(self):
        logger.info("🟢 RADAR GIRANDO (%s Pares)...", len(SYMBOLS))
        while True:
            try:
                await self._scan()
                logger.info("⏳ Esperando 60s...")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error("Error: %s", e)
                await asyncio.sleep(5)

    async def _scan(self):
        logger.info("\n📡 --- %s ---", datetime.now().strftime("%H:%M:%S"))
        for symbol in SYMBOLS:
            try:
                mgr = self.managers[symbol]
                await mgr.update_data()
                df = mgr.get_latest_data()
                if df is None or len(df) < 200:
                    continue

                df = self.indicators.calculate_all(df)
                price = df['close'].iloc[-1]

                signal, _, _ = self.strategies[symbol].get_signal(df)

                if signal.value == "BUY":
                    icon = "🟢"
                elif signal.value == "SELL":
                    icon = "🔴"
                else:
                    icon = "⚪"
                logger.info(
                    "%s %-10s $%-10.2f | Señal: %s",
                    icon, symbol, price, signal.value,
                )
            except Exception as e:
                logger.error("Error %s: %s", symbol, e)


async def _main():
    radar = CryptoRadar()
    if await radar.initialize():
        await radar.run()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass

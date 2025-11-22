#!/usr/bin/env python3
"""
🤖 CRYPTO TRADING BOT - TESTNET FINAL (FULL URL PATCH)
"""
import os
import sys
from dotenv import load_dotenv

# ======================================================
# 1. SISTEMA DE ARRANQUE Y CARGA DE LLAVES
# ======================================================
print("\n" + "="*50)
print("🔧 SISTEMA DE ARRANQUE (MODO DEMO)")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH, override=True)

API_KEY = os.getenv('BINANCE_API_KEY')
SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')

if API_KEY and SECRET_KEY:
    # Mostramos los primeros caracteres para que verifiques
    if API_KEY.startswith("DCZ"):
         print(f"✅ Llaves de TESTNET detectadas: {API_KEY[:5]}...")
    else:
         print(f"⚠️ CUIDADO: La llave {API_KEY[:5]}... no parece de Testnet (debería empezar por DCZ).")
else:
    print("❌ ERROR: Faltan las llaves en el archivo .env")
    sys.exit(1)
print("="*50 + "\n")
# ======================================================

import asyncio
import logging
import colorlog
from datetime import datetime
import pandas as pd
import ccxt.async_support as ccxt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from modules.data_manager import DataManager
from modules.indicators import TechnicalIndicators
from modules.ai_predictor import AI_Predictor
from strategies.strategy import HybridStrategy

def setup_logging():
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s %(levelname)s: %(message)s",
        datefmt='%H:%M:%S',
        log_colors={'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red'}
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = colorlog.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger

logger = setup_logging()

class CryptoTradingBot:
    def __init__(self):
        self.exchange = None
        self.running = False
        self.symbol = "BTC/USDT"
        self.timeframe = "1m"

    async def initialize(self):
        logger.info("🚀 INICIANDO BOT...")

        try:
            # Configuración ESPECÍFICA para Binance Futures Testnet
            self.exchange = ccxt.binance({
                'apiKey': API_KEY,
                'secret': SECRET_KEY,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future', 
                }
            })

            # --- PARCHE COMPLETO DE URLS (SOLUCIÓN AL ERROR dapi/sapi) ---
            # Definimos TODAS las rutas posibles para que CCXT no falle
            testnet_url = 'https://testnet.binancefuture.com'
            self.exchange.urls['api'] = {
                'fapiPublic': f'{testnet_url}/fapi/v1',
                'fapiPrivate': f'{testnet_url}/fapi/v1',
                'public': f'{testnet_url}/fapi/v1',
                'private': f'{testnet_url}/fapi/v1',
                'sapi': f'{testnet_url}/sapi/v1',
                # ESTAS SON LAS QUE FALTABAN Y DABAN ERROR:
                'dapiPublic': f'{testnet_url}/dapi/v1',
                'dapiPrivate': f'{testnet_url}/dapi/v1',
                'eapiPublic': f'{testnet_url}/eapi/v1',
                'eapiPrivate': f'{testnet_url}/eapi/v1',
            }
            # ------------------------------------------------------

            logger.info("🔄 Conectando a Binance Futures Testnet...")
            await self.exchange.load_markets()
            logger.info("✅ ¡CONEXIÓN EXITOSA!")
            
        except Exception as e:
            logger.error(f"❌ Error de conexión: {e}")
            return False

        # Inicializar módulos
        self.data_manager = DataManager(self.exchange, self.symbol, self.timeframe)
        self.indicators = TechnicalIndicators({})
        self.ai_predictor = AI_Predictor({})
        self.strategy = HybridStrategy(self.data_manager, self.indicators, self.ai_predictor, {})

        await self._check_balance()
        return True

    async def _check_balance(self):
        try:
            balance = await self.exchange.fetch_balance()
            # En testnet el saldo suele estar directamente en el diccionario 'free' o 'total'
            usdt = balance.get('USDT', {}).get('free', 0)
            # Si falla, probamos la estructura estándar
            if usdt == 0:
                usdt = balance.get('total', {}).get('USDT', 0)
                
            logger.info(f"💰 SALDO FICTICIO: ${usdt:.2f} USDT")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo leer el saldo (Error menor): {e}")

    async def run(self):
        self.running = True
        logger.info("🟢 BOT OPERATIVO. Escaneando mercado...")
        while self.running:
            try:
                await self._cycle()
                logger.info("⏳ Esperando 60 segundos...")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(5)

    async def _cycle(self):
        logger.info(f"\n📊 --- {datetime.now().strftime('%H:%M:%S')} ---")
        
        await self.data_manager.update_data()
        df = self.data_manager.get_latest_data()
        
        if df is None or len(df) < 20:
            logger.warning("⏳ Recopilando velas...")
            return

        df = self.indicators.calculate_all(df)
        price = df['close'].iloc[-1]
        logger.info(f"💹 {self.symbol}: ${price:.2f}")

        signal, conf, _ = self.strategy.get_signal(df)
        if signal.value != "NEUTRAL":
            logger.info(f"🚨 SEÑAL: {signal.value} (Confianza: {conf:.0%})")
        else:
            logger.info("💤 Mercado tranquilo")

async def main():
    bot = CryptoTradingBot()
    if await bot.initialize():
        try:
            await bot.run()
        except KeyboardInterrupt:
            logger.info("\n👋 Apagando...")
            if bot.exchange: await bot.exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
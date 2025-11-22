#!/usr/bin/env python3
"""
🤖 CRYPTO TRADING BOT - RADAR EDITION (MULTI-PAIR)
"""
import os
import sys
from dotenv import load_dotenv

# 1. Carga de Configuración
print("\n" + "="*50)
print("📡 INICIANDO RADAR DE MERCADO")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH, override=True)

# Leer lista de monedas
symbols_env = os.getenv('TRADING_SYMBOLS', 'BTC/USDT')
# Limpiamos espacios por si acaso
SYMBOLS = [s.strip() for s in symbols_env.split(',')]
print(f"📋 Objetivos: {SYMBOLS}")

API_KEY = os.getenv('BINANCE_API_KEY')
SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')

if not API_KEY:
    print("❌ ERROR: Faltan las claves en .env")
    sys.exit(1)
print("="*50 + "\n")

import asyncio
import logging
import colorlog
from datetime import datetime
import ccxt.async_support as ccxt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from modules.data_manager import DataManager
from modules.indicators import TechnicalIndicators
from modules.ai_predictor import AI_Predictor
from strategies.strategy import HybridStrategy

# Configurar Logger
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

class CryptoRadar:
    def __init__(self):
        self.exchange = None
        self.running = False
        self.managers = {} # Aquí guardamos un gestor para cada moneda
        self.timeframe = os.getenv('TIMEFRAME', '1m')

    async def initialize(self):
        logger.info("🚀 CARGANDO SISTEMAS...")
        try:
            self.exchange = ccxt.binance({
                'apiKey': API_KEY,
                'secret': SECRET_KEY,
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            })
            
            # Parche URLs Testnet
            testnet_url = 'https://testnet.binancefuture.com'
            self.exchange.urls['api'] = {
                'fapiPublic': f'{testnet_url}/fapi/v1',
                'fapiPrivate': f'{testnet_url}/fapi/v1',
                'public': f'{testnet_url}/fapi/v1',
                'private': f'{testnet_url}/fapi/v1',
                'sapi': f'{testnet_url}/sapi/v1',
                'dapiPublic': f'{testnet_url}/dapi/v1',
                'dapiPrivate': f'{testnet_url}/dapi/v1',
                'eapiPublic': f'{testnet_url}/eapi/v1',
                'eapiPrivate': f'{testnet_url}/eapi/v1',
            }

            await self.exchange.load_markets()
            logger.info("✅ CONEXIÓN MULTI-PAR LISTA")
            
        except Exception as e:
            logger.error(f"❌ Error conexión: {e}")
            return False

        # Inicializar componentes compartidos
        self.indicators = TechnicalIndicators({})
        self.ai_predictor = AI_Predictor({})
        
        # Inicializar UN GESTOR POR MONEDA
        logger.info(f"📦 Desplegando {len(SYMBOLS)} sondas...")
        for sym in SYMBOLS:
            self.managers[sym] = DataManager(self.exchange, sym, self.timeframe)
            
        # Estrategia base (la iremos reutilizando)
        self.strategy = HybridStrategy(None, self.indicators, self.ai_predictor, {})
        
        return True

    async def run(self):
        self.running = True
        logger.info("🟢 RADAR GIRANDO... (Ctrl+C para parar)")
        
        while self.running:
            try:
                await self._scan_round()
                logger.info("⏳ Enfriando radar (60s)...")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error ciclo: {e}")
                await asyncio.sleep(5)

    async def _scan_round(self):
        logger.info(f"\n📡 --- ESCANEO {datetime.now().strftime('%H:%M:%S')} ---")
        
        for symbol in SYMBOLS:
            try:
                manager = self.managers[symbol]
                # 1. Actualizar datos
                await manager.update_data()
                df = manager.get_latest_data()
                
                if df is None or len(df) < 20:
                    continue

                # 2. Calcular
                df = self.indicators.calculate_all(df)
                price = df['close'].iloc[-1]
                
                # 3. Analizar con Estrategia
                self.strategy.data_manager = manager # Cambiamos el foco de la estrategia
                signal, conf, _ = self.strategy.get_signal(df)
                
                # 4. Visualización
                icon = "⚪"
                if signal.value == "BUY": icon = "🟢"
                if signal.value == "SELL": icon = "🔴"
                
                print(f"{icon} {symbol:<10} ${price:<10.2f} | Señal: {signal.value} ({conf:.0%})")
                
                # Si hay señal fuerte, aquí meteríamos la orden
                if signal.value != "NEUTRAL":
                    logger.info(f"🚨 ¡ALERTA EN {symbol}! Oportunidad detectada.")

            except Exception as e:
                logger.error(f"Error en {symbol}: {e}")

async def main():
    radar = CryptoRadar()
    if await radar.initialize():
        try:
            await radar.run()
        except KeyboardInterrupt:
            logger.info("\n🛑 Apagando radar...")
            if radar.exchange: await radar.exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
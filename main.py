#!/usr/bin/env python3
"""
🤖 CRYPTO TRADING BOT CON IA
=============================
Bot de trading de criptomonedas con arquitectura modular y soporte para ML.

Características:
- Conexión a Binance via CCXT
- Indicadores técnicos (RSI, MACD, Bollinger)
- Módulo de IA preparado para PyTorch/TensorFlow
- Estrategia híbrida adaptativa:
  * Alta volatilidad → Scalping con indicadores
  * Baja volatilidad → Swing con IA
- Ejecución asíncrona con asyncio
- Optimizado para GPU RTX 5080

Autor: Crypto Trading Bot ML
Versión: 1.0.0
"""

import asyncio
import sys
import os
import signal
from datetime import datetime
from typing import Optional
import colorlog
import logging

# ⚠️ IMPORTANTE: Cargar variables de entorno ANTES de importar módulos propios
from dotenv import load_dotenv
load_dotenv()  # Cargar .env PRIMERO

# Añadir src al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Importar módulos del bot (DESPUÉS de cargar .env)
from config import Config
from modules.data_manager import DataManager
from modules.indicators import TechnicalIndicators
from modules.ai_predictor import AI_Predictor
from strategies.strategy import HybridStrategy, Signal

import ccxt.async_support as ccxt

# Configurar logging con colores
def setup_logging():
    """Configura el sistema de logging con colores"""

    # Crear formatter con colores
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )

    # Configurar handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Configurar logger raíz
    logger = colorlog.getLogger()
    logger.addHandler(console_handler)
    logger.setLevel(getattr(logging, Config.LOG_LEVEL))

    return logger


logger = setup_logging()


class CryptoTradingBot:
    """
    Bot principal de trading de criptomonedas

    Integra todos los módulos y gestiona el ciclo de trading completo.
    """

    def __init__(self):
        """Inicializa el bot de trading"""

        self.config = Config
        self.exchange: Optional[ccxt.Exchange] = None
        self.data_manager: Optional[DataManager] = None
        self.indicators: Optional[TechnicalIndicators] = None
        self.ai_predictor: Optional[AI_Predictor] = None
        self.strategy: Optional[HybridStrategy] = None

        # Estado del bot
        self.running = False
        self.positions = []  # Posiciones abiertas
        self.balance = 0.0

        logger.info("="*60)
        logger.info("🤖 CRYPTO TRADING BOT INITIALIZING")
        logger.info("="*60)

    async def initialize(self):
        """Inicializa todos los componentes del bot"""

        try:
            # Mostrar configuración
            self.config.print_config()

            # Validar configuración
            if not self.config.validate_config():
                logger.error("❌ Configuration validation failed")
                return False

            # Inicializar exchange
            logger.info("🔄 Connecting to exchange...")
            await self._initialize_exchange()

            # Inicializar gestor de datos
            logger.info("📊 Initializing data manager...")
            self.data_manager = DataManager(
                exchange=self.exchange,
                symbol=self.config.SYMBOL,
                timeframe=self.config.TIMEFRAME,
                historical_bars=self.config.DATA_CONFIG['historical_bars']
            )

            # Descargar datos iniciales
            await self.data_manager.update_data()

            # Inicializar indicadores técnicos
            logger.info("📈 Initializing technical indicators...")
            self.indicators = TechnicalIndicators(self.config.INDICATORS_CONFIG)

            # Inicializar predictor de IA
            logger.info("🤖 Initializing AI predictor...")
            self.ai_predictor = AI_Predictor(self.config.AI_CONFIG)

            # Inicializar estrategia
            logger.info("🎯 Initializing trading strategy...")
            self.strategy = HybridStrategy(
                data_manager=self.data_manager,
                indicators=self.indicators,
                ai_predictor=self.ai_predictor,
                config={
                    'VOLATILITY_THRESHOLD': self.config.VOLATILITY_THRESHOLD,
                    'SCALPING_CONFIG': self.config.SCALPING_CONFIG,
                    'SWING_CONFIG': self.config.SWING_CONFIG
                }
            )

            # Obtener balance
            await self._update_balance()

            logger.info("="*60)
            logger.info("✅ BOT INITIALIZED SUCCESSFULLY")
            logger.info("="*60)

            return True

        except Exception as e:
            logger.error(f"❌ Error initializing bot: {e}")
            return False

    async def _initialize_exchange(self):
        """Inicializa la conexión con el exchange"""

        try:
            # Crear instancia del exchange
            exchange_class = getattr(ccxt, self.config.EXCHANGE)
            self.exchange = exchange_class(self.config.get_exchange_config())

            # Cargar mercados
            await self.exchange.load_markets()

            logger.info(f"✅ Connected to {self.config.EXCHANGE}")

            # Verificar símbolo
            if self.config.SYMBOL not in self.exchange.markets:
                raise ValueError(f"Symbol {self.config.SYMBOL} not found in {self.config.EXCHANGE}")

        except Exception as e:
            logger.error(f"❌ Error connecting to exchange: {e}")
            raise

    async def _update_balance(self):
        """Actualiza el balance de la cuenta"""

        try:
            balance = await self.exchange.fetch_balance()

            # Obtener balance en USDT
            if 'USDT' in balance['total']:
                self.balance = balance['total']['USDT']
                logger.info(f"💰 Balance: ${self.balance:.2f} USDT")
            else:
                logger.warning("⚠️  USDT balance not found")
                self.balance = 0.0

        except Exception as e:
            logger.error(f"❌ Error fetching balance: {e}")

    async def run(self):
        """Ejecuta el ciclo principal del bot"""

        self.running = True
        logger.info("🚀 Starting trading loop...")

        try:
            while self.running:
                await self._trading_cycle()

                # Esperar antes del próximo ciclo
                interval = self.strategy.get_check_interval()
                logger.debug(f"⏳ Waiting {interval}s until next check...")
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info("⏹️  Trading loop cancelled")
        except Exception as e:
            logger.error(f"❌ Error in trading loop: {e}")
            raise
        finally:
            await self.shutdown()

    async def _trading_cycle(self):
        """Ejecuta un ciclo completo de análisis y trading"""

        try:
            logger.info("\n" + "="*60)
            logger.info(f"📊 TRADING CYCLE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("="*60)

            # 1. Actualizar datos
            logger.info("🔄 Updating market data...")
            await self.data_manager.update_data()

            # 2. Obtener datos actuales
            df = self.data_manager.get_latest_data()

            if df is None or len(df) < 50:
                logger.warning("⚠️  Not enough data for analysis")
                return

            # 3. Calcular indicadores
            logger.info("📈 Calculating technical indicators...")
            df = self.indicators.calculate_all(df)

            # 4. Mostrar resumen de datos
            data_summary = self.data_manager.get_data_summary()
            logger.info(f"💹 Price: ${data_summary['latest_price']:.2f}")
            logger.info(f"📊 Volatility: {data_summary['volatility']:.2f}%")
            logger.info(f"📈 24h Change: {data_summary['price_change_24h']:.2f}%")

            # 5. Mostrar indicadores
            indicators_summary = self.indicators.get_indicators_summary(df)
            if 'rsi' in indicators_summary and indicators_summary['rsi'] is not None:
                logger.info(f"📊 RSI: {indicators_summary['rsi']:.2f}")
            if 'macd' in indicators_summary and indicators_summary['macd'] is not None:
                logger.info(f"📊 MACD: {indicators_summary['macd']:.4f}")

            # 6. Obtener señal de trading
            logger.info("🎯 Analyzing trading signals...")
            signal, confidence, details = self.strategy.get_signal(df)

            logger.info(f"🎯 Strategy: {details.get('strategy_used', 'UNKNOWN')}")
            logger.info(f"🎯 Signal: {signal.value} (confidence: {confidence:.2%})")

            # 7. Gestionar posiciones
            await self._manage_positions(signal, confidence, df)

            # 8. Mostrar resumen
            strategy_summary = self.strategy.get_strategy_summary()
            logger.info("\n📋 Status Summary:")
            logger.info(f"   Market Condition: {strategy_summary['current_condition']}")
            logger.info(f"   Active Positions: {len(self.positions)}")
            logger.info(f"   Balance: ${self.balance:.2f} USDT")

        except Exception as e:
            logger.error(f"❌ Error in trading cycle: {e}", exc_info=True)

    async def _manage_positions(self, signal: Signal, confidence: float, df):
        """
        Gestiona la apertura y cierre de posiciones

        Args:
            signal: Señal de trading
            confidence: Confianza de la señal
            df: DataFrame con datos e indicadores
        """

        try:
            current_price = df['close'].iloc[-1]

            # Verificar si se debe abrir nueva posición
            should_open = self.strategy.should_open_position(
                signal=signal,
                confidence=confidence,
                current_positions=len(self.positions),
                max_positions=self.config.MAX_POSITIONS
            )

            if should_open and signal != Signal.NEUTRAL:
                logger.info(f"\n💡 Opening {signal.value} position...")

                # Calcular tamaño de posición
                quantity = self.strategy.calculate_position_size(
                    balance=self.balance,
                    position_size_percent=self.config.POSITION_SIZE,
                    price=current_price
                )

                # Calcular SL y TP
                stop_loss, take_profit = self.strategy.calculate_stop_loss_take_profit(
                    entry_price=current_price,
                    signal=signal,
                    stop_loss_percent=self.config.STOP_LOSS_PERCENT,
                    take_profit_percent=self.config.TAKE_PROFIT_PERCENT
                )

                # Crear orden (en modo demo, solo simular)
                if self.config.TESTNET:
                    logger.info("📝 DEMO MODE - Order simulation:")
                    logger.info(f"   Type: {signal.value}")
                    logger.info(f"   Quantity: {quantity:.8f}")
                    logger.info(f"   Entry: ${current_price:.2f}")
                    logger.info(f"   Stop Loss: ${stop_loss:.2f}")
                    logger.info(f"   Take Profit: ${take_profit:.2f}")

                    # Simular posición
                    position = {
                        'type': signal.value,
                        'quantity': quantity,
                        'entry_price': current_price,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'timestamp': datetime.now()
                    }
                    self.positions.append(position)
                else:
                    # TODO: Implementar órdenes reales
                    logger.warning("⚠️  Real trading not implemented yet")

            # Verificar posiciones abiertas (SL/TP)
            await self._check_open_positions(current_price)

        except Exception as e:
            logger.error(f"❌ Error managing positions: {e}")

    async def _check_open_positions(self, current_price: float):
        """
        Verifica y gestiona posiciones abiertas

        Args:
            current_price: Precio actual del activo
        """

        try:
            positions_to_close = []

            for i, position in enumerate(self.positions):
                position_type = position['type']
                entry_price = position['entry_price']
                stop_loss = position['stop_loss']
                take_profit = position['take_profit']

                # Verificar SL/TP
                should_close = False
                reason = ""

                if position_type == 'BUY':
                    if current_price <= stop_loss:
                        should_close = True
                        reason = "STOP LOSS"
                    elif current_price >= take_profit:
                        should_close = True
                        reason = "TAKE PROFIT"

                elif position_type == 'SELL':
                    if current_price >= stop_loss:
                        should_close = True
                        reason = "STOP LOSS"
                    elif current_price <= take_profit:
                        should_close = True
                        reason = "TAKE PROFIT"

                if should_close:
                    # Calcular P&L
                    if position_type == 'BUY':
                        pnl = (current_price - entry_price) / entry_price * 100
                    else:
                        pnl = (entry_price - current_price) / entry_price * 100

                    logger.info(f"\n🔔 Closing position: {reason}")
                    logger.info(f"   Type: {position_type}")
                    logger.info(f"   Entry: ${entry_price:.2f}")
                    logger.info(f"   Exit: ${current_price:.2f}")
                    logger.info(f"   P&L: {pnl:.2f}%")

                    positions_to_close.append(i)

            # Cerrar posiciones
            for i in reversed(positions_to_close):
                self.positions.pop(i)

        except Exception as e:
            logger.error(f"❌ Error checking positions: {e}")

    async def shutdown(self):
        """Cierra el bot de forma ordenada"""

        logger.info("\n" + "="*60)
        logger.info("⏹️  SHUTTING DOWN BOT")
        logger.info("="*60)

        try:
            # Cerrar conexión con exchange
            if self.exchange:
                await self.exchange.close()
                logger.info("✅ Exchange connection closed")

            # Mostrar resumen final
            logger.info(f"\n📊 Final Summary:")
            logger.info(f"   Open Positions: {len(self.positions)}")
            logger.info(f"   Final Balance: ${self.balance:.2f} USDT")

        except Exception as e:
            logger.error(f"❌ Error during shutdown: {e}")

        logger.info("="*60)
        logger.info("👋 BOT SHUTDOWN COMPLETE")
        logger.info("="*60)

    def stop(self):
        """Detiene el bot"""
        logger.info("🛑 Stop signal received")
        self.running = False


# =====================
# FUNCIONES DE CONTROL
# =====================

async def main():
    """Función principal"""

    # Crear instancia del bot
    bot = CryptoTradingBot()

    # Manejar señales de sistema
    def signal_handler(sig, frame):
        logger.info(f"\n🛑 Signal {sig} received")
        bot.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Inicializar bot
        if not await bot.initialize():
            logger.error("❌ Bot initialization failed")
            return 1

        # Ejecutar bot
        await bot.run()

        return 0

    except KeyboardInterrupt:
        logger.info("\n⏹️  Interrupted by user")
        return 0

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    """Punto de entrada del programa"""

    try:
        # Ejecutar bot con asyncio
        exit_code = asyncio.run(main())
        sys.exit(exit_code)

    except KeyboardInterrupt:
        logger.info("\n👋 Goodbye!")
        sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        sys.exit(1)

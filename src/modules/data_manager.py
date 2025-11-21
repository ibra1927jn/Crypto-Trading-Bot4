"""
Módulo de Gestión de Datos
===========================
Este módulo se encarga de:
- Descargar datos históricos del exchange
- Mantener datos actualizados en tiempo real
- Proporcionar datos limpios y estructurados
- Calcular volatilidad para determinar estrategia
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import asyncio
from colorlog import getLogger
import logging

# Configurar logger con colores
logger = getLogger(__name__)


class DataManager:
    """
    Clase para gestionar la descarga y actualización de datos del mercado
    """

    def __init__(self, exchange: ccxt.Exchange, symbol: str, timeframe: str, historical_bars: int = 500):
        """
        Inicializa el gestor de datos

        Args:
            exchange: Instancia de ccxt exchange
            symbol: Par de trading (ej: 'BTC/USDT')
            timeframe: Marco temporal (ej: '5m', '15m', '1h')
            historical_bars: Cantidad de velas históricas a mantener
        """
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.historical_bars = historical_bars

        # DataFrame para almacenar datos OHLCV
        self.df: Optional[pd.DataFrame] = None

        # Caché de datos
        self.last_update: Optional[datetime] = None
        self.update_lock = asyncio.Lock()

        logger.info(f"📊 DataManager initialized: {symbol} @ {timeframe}")

    async def fetch_historical_data(self) -> pd.DataFrame:
        """
        Descarga datos históricos del exchange

        Returns:
            DataFrame con columnas: timestamp, open, high, low, close, volume
        """
        try:
            logger.info(f"⬇️  Fetching {self.historical_bars} historical bars for {self.symbol}")

            # Descargar datos OHLCV
            ohlcv = await asyncio.to_thread(
                self.exchange.fetch_ohlcv,
                self.symbol,
                self.timeframe,
                limit=self.historical_bars
            )

            # Convertir a DataFrame
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )

            # Convertir timestamp a datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

            # Asegurar que los datos estén ordenados
            df.sort_index(inplace=True)

            logger.info(f"✅ Fetched {len(df)} bars - Range: {df.index[0]} to {df.index[-1]}")

            return df

        except Exception as e:
            logger.error(f"❌ Error fetching historical data: {e}")
            raise

    async def update_data(self) -> bool:
        """
        Actualiza los datos con la última vela

        Returns:
            True si se actualizó correctamente, False en caso contrario
        """
        async with self.update_lock:
            try:
                # Si no hay datos, descargar históricos completos
                if self.df is None or len(self.df) == 0:
                    self.df = await self.fetch_historical_data()
                    self.last_update = datetime.now()
                    return True

                # Descargar última vela
                ohlcv = await asyncio.to_thread(
                    self.exchange.fetch_ohlcv,
                    self.symbol,
                    self.timeframe,
                    limit=1
                )

                if not ohlcv:
                    logger.warning("⚠️  No new data available")
                    return False

                # Crear nuevo registro
                new_bar = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                new_bar['timestamp'] = pd.to_datetime(new_bar['timestamp'], unit='ms')
                new_bar.set_index('timestamp', inplace=True)

                # Verificar si es una nueva vela o actualización de la actual
                last_timestamp = self.df.index[-1]
                new_timestamp = new_bar.index[0]

                if new_timestamp > last_timestamp:
                    # Nueva vela - agregar
                    self.df = pd.concat([self.df, new_bar])

                    # Mantener solo las últimas N velas
                    if len(self.df) > self.historical_bars:
                        self.df = self.df.iloc[-self.historical_bars:]

                    logger.debug(f"📈 New bar added: {new_timestamp}")
                else:
                    # Actualizar vela actual
                    self.df.loc[new_timestamp] = new_bar.iloc[0]
                    logger.debug(f"🔄 Current bar updated: {new_timestamp}")

                self.last_update = datetime.now()
                return True

            except Exception as e:
                logger.error(f"❌ Error updating data: {e}")
                return False

    def get_latest_data(self, bars: Optional[int] = None) -> pd.DataFrame:
        """
        Retorna los últimos N registros de datos

        Args:
            bars: Número de velas a retornar (None = todas)

        Returns:
            DataFrame con los datos solicitados
        """
        if self.df is None or len(self.df) == 0:
            logger.warning("⚠️  No data available")
            return pd.DataFrame()

        if bars is None:
            return self.df.copy()

        return self.df.iloc[-bars:].copy()

    def get_latest_price(self) -> float:
        """
        Retorna el precio de cierre más reciente

        Returns:
            Precio de cierre actual
        """
        if self.df is None or len(self.df) == 0:
            logger.warning("⚠️  No data available for price")
            return 0.0

        return float(self.df['close'].iloc[-1])

    def calculate_volatility(self, window: int = 20) -> float:
        """
        Calcula la volatilidad histórica usando desviación estándar de los retornos

        Args:
            window: Ventana de tiempo para el cálculo

        Returns:
            Volatilidad como porcentaje
        """
        if self.df is None or len(self.df) < window:
            logger.warning("⚠️  Not enough data for volatility calculation")
            return 0.0

        try:
            # Calcular retornos logarítmicos
            returns = np.log(self.df['close'] / self.df['close'].shift(1))

            # Calcular desviación estándar de los últimos N retornos
            volatility = returns.iloc[-window:].std()

            # Convertir a porcentaje anualizado (aproximado)
            # Multiplicar por raíz cuadrada del número de periodos en un año
            periods_per_day = {
                '1m': 1440,
                '5m': 288,
                '15m': 96,
                '1h': 24,
                '4h': 6,
                '1d': 1
            }

            periods = periods_per_day.get(self.timeframe, 24)
            annualized_vol = volatility * np.sqrt(periods * 365) * 100

            logger.debug(f"📊 Volatility ({window} bars): {annualized_vol:.2f}%")

            return float(annualized_vol)

        except Exception as e:
            logger.error(f"❌ Error calculating volatility: {e}")
            return 0.0

    def is_high_volatility(self, threshold: float) -> bool:
        """
        Determina si la volatilidad actual es alta

        Args:
            threshold: Umbral de volatilidad

        Returns:
            True si la volatilidad es alta, False en caso contrario
        """
        current_vol = self.calculate_volatility()
        return current_vol > threshold

    def get_data_summary(self) -> Dict[str, Any]:
        """
        Retorna un resumen del estado actual de los datos

        Returns:
            Diccionario con información de los datos
        """
        if self.df is None or len(self.df) == 0:
            return {
                'status': 'No data',
                'bars': 0,
                'latest_price': 0.0,
                'volatility': 0.0
            }

        return {
            'status': 'OK',
            'bars': len(self.df),
            'latest_price': self.get_latest_price(),
            'latest_timestamp': str(self.df.index[-1]),
            'volatility': self.calculate_volatility(),
            'last_update': str(self.last_update) if self.last_update else 'Never',
            'price_change_24h': self._calculate_price_change()
        }

    def _calculate_price_change(self) -> float:
        """
        Calcula el cambio de precio en las últimas 24 horas (aproximado)

        Returns:
            Cambio porcentual
        """
        if self.df is None or len(self.df) < 2:
            return 0.0

        try:
            # Tomar el número aproximado de velas en 24h
            periods_24h = {
                '1m': 1440,
                '5m': 288,
                '15m': 96,
                '1h': 24,
                '4h': 6,
                '1d': 1
            }

            bars_24h = periods_24h.get(self.timeframe, 24)
            bars_24h = min(bars_24h, len(self.df))

            old_price = self.df['close'].iloc[-bars_24h]
            new_price = self.df['close'].iloc[-1]

            change = ((new_price - old_price) / old_price) * 100

            return float(change)

        except Exception as e:
            logger.error(f"❌ Error calculating price change: {e}")
            return 0.0

    async def start_auto_update(self, interval: int = 60):
        """
        Inicia actualización automática de datos

        Args:
            interval: Intervalo de actualización en segundos
        """
        logger.info(f"🔄 Starting auto-update every {interval} seconds")

        while True:
            try:
                await self.update_data()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("⏹️  Auto-update stopped")
                break
            except Exception as e:
                logger.error(f"❌ Error in auto-update: {e}")
                await asyncio.sleep(interval)


# =====================
# FUNCIONES DE UTILIDAD
# =====================

def timeframe_to_seconds(timeframe: str) -> int:
    """
    Convierte un timeframe a segundos

    Args:
        timeframe: Timeframe en formato ccxt (ej: '5m', '1h')

    Returns:
        Número de segundos
    """
    multipliers = {
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800
    }

    unit = timeframe[-1]
    value = int(timeframe[:-1])

    return value * multipliers.get(unit, 60)

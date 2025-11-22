import pandas as pd
import numpy as np
import logging
import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)

class DataManager:
    def __init__(self, exchange, symbol, timeframe, historical_bars=100):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.limit = historical_bars
        self.data = None

    async def update_data(self):
        """Descarga datos del mercado (Versión Arreglada)"""
        try:
            logger.info(f"⬇️  Descargando {self.limit} velas de {self.symbol}...")
            
            # Esta línea es la clave que arreglamos antes
            if self.exchange.has['fetchOHLCV']:
                ohlcv = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=self.limit)
            else:
                logger.error("❌ El exchange no soporta OHLCV")
                return

            if ohlcv and len(ohlcv) > 0:
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                self.data = df
                
                latest = df['close'].iloc[-1]
                logger.info(f"✅ Datos recibidos. Precio: ${latest:.2f}")
            else:
                logger.warning("⚠️ Lista de datos vacía.")

        except Exception as e:
            logger.error(f"❌ Error descargando datos: {e}")

    def get_latest_data(self):
        return self.data

    def calculate_volatility(self, window=20):
        """
        Calcula la volatilidad.
        ESTA ES LA FUNCIÓN QUE ECHABA DE MENOS TU BOT.
        """
        if self.data is None or len(self.data) < window:
            return 0.0

        try:
            # Matemática financiera para ver cuánto se mueve el precio
            df = self.data
            # Retorno logarítmico
            returns = np.log(df['close'] / df['close'].shift(1))
            # Desviación estándar
            vol = returns.tail(window).std()
            # Anualizar (para que sea un número legible en %)
            annualized_vol = vol * np.sqrt(365 * 24 * 60) * 100
            return float(annualized_vol)
            
        except Exception as e:
            logger.error(f"❌ Error matemáticas volatilidad: {e}")
            return 0.0

    def get_data_summary(self):
        """Resumen para los logs"""
        if self.data is None or self.data.empty:
            return {'latest_price': 0.0, 'volatility': 0.0}
            
        latest = self.data.iloc[-1]
        return {
            'latest_price': latest['close'],
            'volatility': self.calculate_volatility()
        }
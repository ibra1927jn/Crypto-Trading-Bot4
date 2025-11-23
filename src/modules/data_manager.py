import pandas as pd
import numpy as np
import logging
import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)

class DataManager:
    def __init__(self, exchange, symbol, timeframe, historical_bars=300):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.limit = historical_bars
        self.data = None

    async def update_data(self):
        try:
            if self.exchange.has['fetchOHLCV']:
                ohlcv = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=self.limit)
            else: return

            if ohlcv:
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                # Intentar bajar funding
                try:
                    funding = await self.exchange.fetch_funding_rate(self.symbol)
                    df['funding_rate'] = funding['fundingRate']
                except:
                    df['funding_rate'] = 0.0
                    
                self.data = df
        except Exception as e: logger.error(f"Error datos: {e}")

    def get_latest_data(self): return self.data
    
    def calculate_volatility(self, window=20):
        if self.data is None: return 0.0
        returns = np.log(self.data['close'] / self.data['close'].shift(1))
        return float(returns.tail(window).std() * np.sqrt(365*24*60) * 100)
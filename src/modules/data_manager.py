import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


class DataManager:
    def __init__(self, exchange, symbol, timeframe, historical_bars=300):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.limit = historical_bars
        self.data = None

    async def update_data(self) -> None:
        try:
            if self.exchange.has['fetchOHLCV']:
                ohlcv = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=self.limit)
            else:
                return

            if ohlcv:
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

                # Intentar bajar funding
                try:
                    funding = await self.exchange.fetch_funding_rate(self.symbol)
                    df['funding_rate'] = funding['fundingRate']
                except Exception as e:
                    logger.warning(f"⚠️ Funding rate no disponible: {e}")
                    df['funding_rate'] = 0.0

                self.data = df
        except Exception as e:
            logger.error(f"Error datos: {e}")

    def get_latest_data(self) -> pd.DataFrame | None:
        return self.data

    BARS_PER_YEAR = {
        '1m': 365 * 24 * 60,
        '5m': 365 * 24 * 12,
        '15m': 365 * 24 * 4,
        '1h': 365 * 24,
        '4h': 365 * 6,
        '1d': 365,
    }

    def calculate_volatility(self, window: int = 20) -> float:
        if self.data is None or len(self.data) < 2:
            return 0.0
        returns = np.log(self.data['close'] / self.data['close'].shift(1))
        bars_per_year = self.BARS_PER_YEAR.get(self.timeframe, 365 * 24 * 60)
        vol = returns.tail(window).std() * np.sqrt(bars_per_year) * 100
        return 0.0 if np.isnan(vol) else float(vol)

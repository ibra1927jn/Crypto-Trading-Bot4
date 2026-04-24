"""Gestor de datos OHLCV: descarga y mantiene el DataFrame del mercado."""
from __future__ import annotations

import logging
from typing import Any, ClassVar

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_BARS_FOR_RETURNS = 2


class DataManager:
    """Fetch OHLCV data from an exchange and expose it as a pandas DataFrame."""

    def __init__(
        self,
        exchange: Any,
        symbol: str,
        timeframe: str,
        historical_bars: int = 300,
    ) -> None:
        """Store exchange/symbol/timeframe and number of historical bars to fetch."""
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.limit = historical_bars
        self.data: pd.DataFrame | None = None

    async def update_data(self) -> None:
        """Fetch the latest OHLCV (and funding rate) into ``self.data``."""
        try:
            if self.exchange.has["fetchOHLCV"]:
                ohlcv = await self.exchange.fetch_ohlcv(
                    self.symbol, self.timeframe, limit=self.limit,
                )
            else:
                return

            if ohlcv:
                df = pd.DataFrame(
                    ohlcv,
                    columns=[
                        "timestamp", "open", "high",
                        "low", "close", "volume",
                    ],
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

                # Intentar bajar funding
                try:
                    funding = await self.exchange.fetch_funding_rate(
                        self.symbol,
                    )
                    df["funding_rate"] = funding["fundingRate"]
                # ccxt raises varied exceptions; log and fall back to 0.0
                except Exception as e:  # noqa: BLE001
                    logger.warning("⚠️ Funding rate no disponible: %s", e)
                    df["funding_rate"] = 0.0

                self.data = df
        except Exception:
            logger.exception("Error datos")

    def get_latest_data(self) -> pd.DataFrame | None:
        """Return the most recently fetched OHLCV DataFrame (or ``None``)."""
        return self.data

    BARS_PER_YEAR: ClassVar[dict[str, int]] = {
        "1m": 365 * 24 * 60,
        "5m": 365 * 24 * 12,
        "15m": 365 * 24 * 4,
        "1h": 365 * 24,
        "4h": 365 * 6,
        "1d": 365,
    }

    def calculate_volatility(self, window: int = 20) -> float:
        """Return annualized std-dev of log returns over the last ``window`` bars."""
        if self.data is None or len(self.data) < MIN_BARS_FOR_RETURNS:
            return 0.0
        returns = np.log(
            self.data["close"] / self.data["close"].shift(1),
        )
        bars_per_year = self.BARS_PER_YEAR.get(
            self.timeframe, self.BARS_PER_YEAR["1m"],
        )
        vol = returns.tail(window).std() * np.sqrt(bars_per_year) * 100
        return 0.0 if np.isnan(vol) else float(vol)

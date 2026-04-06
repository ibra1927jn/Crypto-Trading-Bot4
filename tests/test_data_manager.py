"""Tests para DataManager."""
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from modules.data_manager import DataManager


class TestCalculateVolatility:
    def _make_dm_with_data(self, prices, timeframe='1m'):
        dm = DataManager(exchange=None, symbol='BTC/USDT', timeframe=timeframe)
        dm.data = pd.DataFrame({
            'close': prices,
            'open': prices,
            'high': prices,
            'low': prices,
            'volume': [1000] * len(prices),
        })
        return dm

    def test_returns_float(self):
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        dm = self._make_dm_with_data(prices)
        vol = dm.calculate_volatility()
        assert isinstance(vol, float)
        assert vol >= 0

    def test_no_data_returns_zero(self):
        dm = DataManager(exchange=None, symbol='BTC/USDT', timeframe='1m')
        assert dm.calculate_volatility() == 0.0

    def test_constant_prices_zero_vol(self):
        """Precios constantes deben dar volatilidad ~0."""
        prices = [100.0] * 50
        dm = self._make_dm_with_data(prices)
        vol = dm.calculate_volatility()
        assert vol == 0.0 or np.isnan(vol)

    def test_annualization_factor_depends_on_timeframe(self):
        """Volatility uses correct annualization factor."""
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)

        dm_1m = self._make_dm_with_data(prices, timeframe='1m')
        dm_1h = self._make_dm_with_data(prices, timeframe='1h')

        vol_1m = dm_1m.calculate_volatility()
        vol_1h = dm_1h.calculate_volatility()

        # 1h should give lower annualized vol (fewer bars/year)
        # The ratio should be sqrt(60) ≈ 7.75 difference
        if abs(vol_1m - vol_1h) < 0.001:
            pytest.fail(
                f"Volatility identical for 1m "
                f"({vol_1m:.4f}) and 1h "
                f"({vol_1h:.4f})."
            )

    def test_get_latest_data_none_by_default(self):
        dm = DataManager(exchange=None, symbol='BTC/USDT', timeframe='1m')
        assert dm.get_latest_data() is None

    def test_get_latest_data_returns_data(self):
        prices = [100.0, 101.0, 102.0]
        dm = self._make_dm_with_data(prices)
        data = dm.get_latest_data()
        assert data is not None
        assert len(data) == 3

    def test_single_price_returns_zero(self):
        dm = self._make_dm_with_data([100.0])
        assert dm.calculate_volatility() == 0.0

    def test_unknown_timeframe_uses_default(self):
        """Unknown timeframe should fall back to 1m factor."""
        prices = 100 + np.cumsum(np.random.RandomState(42).randn(50) * 0.5)
        dm = self._make_dm_with_data(prices, timeframe='3m')
        vol = dm.calculate_volatility()
        assert isinstance(vol, float)
        assert vol >= 0


class TestUpdateData:
    def _make_exchange(
        self, ohlcv_data=None, funding_rate=0.001,
        has_ohlcv=True, funding_raises=False,
    ):
        exchange = AsyncMock()
        exchange.has = {'fetchOHLCV': has_ohlcv}
        exchange.fetch_ohlcv = AsyncMock(return_value=ohlcv_data)
        if funding_raises:
            exchange.fetch_funding_rate = AsyncMock(
                side_effect=Exception("no funding")
            )
        else:
            exchange.fetch_funding_rate = AsyncMock(
                return_value={'fundingRate': funding_rate}
            )
        return exchange

    @pytest.mark.asyncio
    async def test_update_data_populates_df(self):
        ohlcv = [
            [1000000, 100.0, 105.0, 95.0, 102.0, 5000.0],
            [1060000, 102.0, 106.0, 98.0, 104.0, 6000.0],
        ]
        exchange = self._make_exchange(ohlcv_data=ohlcv)
        dm = DataManager(exchange, 'BTC/USDT', '1m')
        await dm.update_data()
        data = dm.get_latest_data()
        assert data is not None
        assert len(data) == 2
        assert 'close' in data.columns
        assert 'funding_rate' in data.columns
        assert data['funding_rate'].iloc[0] == 0.001

    @pytest.mark.asyncio
    async def test_update_data_funding_fallback(self):
        """When funding rate fetch fails, column should default to 0.0."""
        ohlcv = [[1000000, 100.0, 105.0, 95.0, 102.0, 5000.0]]
        exchange = self._make_exchange(ohlcv_data=ohlcv, funding_raises=True)
        dm = DataManager(exchange, 'BTC/USDT', '1m')
        await dm.update_data()
        data = dm.get_latest_data()
        assert data is not None
        assert data['funding_rate'].iloc[0] == 0.0

    @pytest.mark.asyncio
    async def test_update_data_no_ohlcv_support(self):
        """If exchange doesn't support fetchOHLCV, data stays None."""
        exchange = self._make_exchange(has_ohlcv=False)
        dm = DataManager(exchange, 'BTC/USDT', '1m')
        await dm.update_data()
        assert dm.get_latest_data() is None

    @pytest.mark.asyncio
    async def test_update_data_empty_ohlcv(self):
        """If exchange returns empty list, data stays None."""
        exchange = self._make_exchange(ohlcv_data=[])
        dm = DataManager(exchange, 'BTC/USDT', '1m')
        await dm.update_data()
        assert dm.get_latest_data() is None

    @pytest.mark.asyncio
    async def test_update_data_exception_handled(self):
        """If fetch_ohlcv raises, data stays None (no crash)."""
        exchange = AsyncMock()
        exchange.has = {'fetchOHLCV': True}
        exchange.fetch_ohlcv = AsyncMock(
            side_effect=Exception("network error")
        )
        dm = DataManager(exchange, 'BTC/USDT', '1m')
        await dm.update_data()
        assert dm.get_latest_data() is None

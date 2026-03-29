"""Tests para DataManager."""
import pytest
import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
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
        """La volatilidad debe usar factor de anualización correcto según timeframe.
        Si el timeframe es 1h, el factor sqrt(365*24) != sqrt(365*24*60)."""
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)

        dm_1m = self._make_dm_with_data(prices, timeframe='1m')
        dm_1h = self._make_dm_with_data(prices, timeframe='1h')

        vol_1m = dm_1m.calculate_volatility()
        vol_1h = dm_1h.calculate_volatility()

        # Bug: currently both return the same value because factor is hardcoded
        # After fix, 1h should give lower annualized vol (fewer bars/year)
        # This test documents the bug - if factor is hardcoded, both are equal
        # The ratio should be sqrt(60) ≈ 7.75 difference
        if abs(vol_1m - vol_1h) < 0.001:
            pytest.fail(
                f"Volatility is identical for 1m ({vol_1m:.4f}) and 1h ({vol_1h:.4f}). "
                "Annualization factor is hardcoded and does not account for timeframe."
            )

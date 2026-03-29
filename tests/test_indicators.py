"""Tests para TechnicalIndicators"""
import pytest
import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from modules.indicators import TechnicalIndicators


def make_ohlcv(n=100, base_price=100.0, seed=42):
    """Genera DataFrame OHLCV sintético."""
    np.random.seed(seed)
    close = base_price + np.cumsum(np.random.randn(n) * 0.5)
    close = np.maximum(close, 1.0)
    df = pd.DataFrame({
        'open': close + np.random.randn(n) * 0.1,
        'high': close + abs(np.random.randn(n) * 0.3),
        'low': close - abs(np.random.randn(n) * 0.3),
        'close': close,
        'volume': np.random.randint(100, 10000, n).astype(float),
    })
    return df


@pytest.fixture
def indicators():
    return TechnicalIndicators({})


@pytest.fixture
def df_with_indicators(indicators):
    df = make_ohlcv(200)
    return indicators.calculate_all(df)


class TestCalculateAll:
    def test_adds_rsi_column(self, indicators):
        df = make_ohlcv(100)
        result = indicators.calculate_all(df)
        assert 'rsi' in result.columns

    def test_adds_macd_columns(self, indicators):
        df = make_ohlcv(100)
        result = indicators.calculate_all(df)
        macd_cols = [c for c in result.columns if 'MACD' in c]
        assert len(macd_cols) >= 2

    def test_adds_bollinger_columns(self, indicators):
        df = make_ohlcv(100)
        result = indicators.calculate_all(df)
        bb_cols = [c for c in result.columns if c.startswith('BB')]
        assert len(bb_cols) >= 3

    def test_none_input(self, indicators):
        result = indicators.calculate_all(None)
        assert result is None

    def test_empty_input(self, indicators):
        result = indicators.calculate_all(pd.DataFrame())
        assert result is not None and result.empty


class TestMACDSignal:
    def test_returns_tuple(self, indicators, df_with_indicators):
        result = indicators.get_macd_signal(df_with_indicators)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_signal_values(self, indicators, df_with_indicators):
        signal, conf = indicators.get_macd_signal(df_with_indicators)
        assert signal in ('BUY', 'SELL', 'NEUTRAL')
        assert 0.0 <= conf <= 1.0

    def test_none_input(self, indicators):
        signal, conf = indicators.get_macd_signal(None)
        assert signal == 'NEUTRAL'

    def test_crossover_buy(self, indicators):
        """Simula cruce MACD alcista."""
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        macd_col = [c for c in df.columns if c.startswith('MACD_')][0]
        signal_col = [c for c in df.columns if c.startswith('MACDs_')][0]
        # Forzar cruce alcista
        df.iloc[-2, df.columns.get_loc(macd_col)] = -1.0
        df.iloc[-2, df.columns.get_loc(signal_col)] = 0.0
        df.iloc[-1, df.columns.get_loc(macd_col)] = 1.0
        df.iloc[-1, df.columns.get_loc(signal_col)] = 0.0
        sig, conf = indicators.get_macd_signal(df)
        assert sig == 'BUY'
        assert conf == 0.8

    def test_crossover_sell(self, indicators):
        """Simula cruce MACD bajista."""
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        macd_col = [c for c in df.columns if c.startswith('MACD_')][0]
        signal_col = [c for c in df.columns if c.startswith('MACDs_')][0]
        df.iloc[-2, df.columns.get_loc(macd_col)] = 1.0
        df.iloc[-2, df.columns.get_loc(signal_col)] = 0.0
        df.iloc[-1, df.columns.get_loc(macd_col)] = -1.0
        df.iloc[-1, df.columns.get_loc(signal_col)] = 0.0
        sig, conf = indicators.get_macd_signal(df)
        assert sig == 'SELL'
        assert conf == 0.8


class TestBollingerSignal:
    def test_returns_tuple(self, indicators, df_with_indicators):
        result = indicators.get_bollinger_signal(df_with_indicators)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_buy_below_lower_band(self, indicators):
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        bbl_col = [c for c in df.columns if c.startswith('BBL')][0]
        df.iloc[-1, df.columns.get_loc('close')] = df[bbl_col].iloc[-1] - 5
        sig, conf = indicators.get_bollinger_signal(df)
        assert sig == 'BUY'
        assert conf == 0.9

    def test_sell_above_upper_band(self, indicators):
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        bbu_col = [c for c in df.columns if c.startswith('BBU')][0]
        df.iloc[-1, df.columns.get_loc('close')] = df[bbu_col].iloc[-1] + 5
        sig, conf = indicators.get_bollinger_signal(df)
        assert sig == 'SELL'
        assert conf == 0.9


class TestCombinedSignal:
    def test_returns_tuple(self, indicators, df_with_indicators):
        result = indicators.get_combined_signal(df_with_indicators)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_oversold_rsi_gives_buy(self, indicators):
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        df.iloc[-1, df.columns.get_loc('rsi')] = 20.0
        # Ensure Bollinger is neutral
        bbl_col = [c for c in df.columns if c.startswith('BBL')][0]
        bbu_col = [c for c in df.columns if c.startswith('BBU')][0]
        mid = (df[bbl_col].iloc[-1] + df[bbu_col].iloc[-1]) / 2
        df.iloc[-1, df.columns.get_loc('close')] = mid
        sig, conf = indicators.get_combined_signal(df)
        assert sig == 'BUY'

    def test_overbought_rsi_gives_sell(self, indicators):
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        df.iloc[-1, df.columns.get_loc('rsi')] = 80.0
        bbl_col = [c for c in df.columns if c.startswith('BBL')][0]
        bbu_col = [c for c in df.columns if c.startswith('BBU')][0]
        mid = (df[bbl_col].iloc[-1] + df[bbu_col].iloc[-1]) / 2
        df.iloc[-1, df.columns.get_loc('close')] = mid
        sig, conf = indicators.get_combined_signal(df)
        assert sig == 'SELL'


class TestGetIndicatorsSummary:
    def test_returns_dict_with_rsi(self, indicators, df_with_indicators):
        result = indicators.get_indicators_summary(df_with_indicators)
        assert isinstance(result, dict)
        assert 'rsi' in result

    def test_none_input_returns_empty(self, indicators):
        result = indicators.get_indicators_summary(None)
        assert result == {}

    def test_empty_input_returns_empty(self, indicators):
        result = indicators.get_indicators_summary(pd.DataFrame())
        assert result == {}


class TestBollingerSignalNeutral:
    def test_neutral_when_between_bands(self, indicators):
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        bbl_col = [c for c in df.columns if c.startswith('BBL')][0]
        bbu_col = [c for c in df.columns if c.startswith('BBU')][0]
        mid = (df[bbl_col].iloc[-1] + df[bbu_col].iloc[-1]) / 2
        df.iloc[-1, df.columns.get_loc('close')] = mid
        sig, conf = indicators.get_bollinger_signal(df)
        assert sig == 'NEUTRAL'
        assert conf == 0.0


class TestCombinedSignalNeutral:
    def test_mid_rsi_neutral_bollinger(self, indicators):
        """RSI in 30-70 range with neutral Bollinger should give NEUTRAL."""
        df = make_ohlcv(200)
        df = indicators.calculate_all(df)
        df.iloc[-1, df.columns.get_loc('rsi')] = 50.0
        bbl_col = [c for c in df.columns if c.startswith('BBL')][0]
        bbu_col = [c for c in df.columns if c.startswith('BBU')][0]
        mid = (df[bbl_col].iloc[-1] + df[bbu_col].iloc[-1]) / 2
        df.iloc[-1, df.columns.get_loc('close')] = mid
        sig, conf = indicators.get_combined_signal(df)
        assert sig == 'NEUTRAL'
        assert conf == 0.0

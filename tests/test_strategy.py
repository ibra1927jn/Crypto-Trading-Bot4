"""Tests para HybridStrategy"""
import pytest
import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from strategies.strategy import HybridStrategy, Signal, MarketCondition


class MockDataManager:
    def __init__(self, volatility=1.0):
        self._volatility = volatility

    def calculate_volatility(self):
        return self._volatility


class MockIndicators:
    def __init__(self, signal='NEUTRAL', confidence=0.0):
        self._signal = signal
        self._confidence = confidence

    def get_combined_signal(self, df):
        return self._signal, self._confidence

    def get_macd_signal(self, df):
        return self._signal, self._confidence

    def get_bollinger_signal(self, df):
        return self._signal, self._confidence


class MockAIPredictor:
    def __init__(self, signal='NEUTRAL', confidence=0.0, prediction=0.0):
        self._signal = signal
        self._confidence = confidence
        self._prediction = prediction

    def predict(self, df):
        return self._prediction, self._confidence

    def get_signal(self, df, threshold=0.65):
        return self._signal


def make_strategy(volatility=1.0, ind_signal='NEUTRAL', ind_conf=0.0,
                  ai_signal='NEUTRAL', ai_conf=0.0, ai_pred=0.0):
    dm = MockDataManager(volatility)
    ind = MockIndicators(ind_signal, ind_conf)
    ai = MockAIPredictor(ai_signal, ai_conf, ai_pred)
    config = {
        'VOLATILITY_THRESHOLD': 2.0,
        'SCALPING_CONFIG': {'check_interval': 5},
        'SWING_CONFIG': {'check_interval': 60, 'ai_confidence_threshold': 0.65},
    }
    return HybridStrategy(dm, ind, ai, config)


@pytest.fixture
def dummy_df():
    n = 50
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        'close': close,
        'rsi': np.random.uniform(30, 70, n),
    })


class TestMarketCondition:
    def test_high_volatility(self):
        s = make_strategy(volatility=3.0)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.HIGH_VOLATILITY

    def test_low_volatility(self):
        s = make_strategy(volatility=1.0)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.LOW_VOLATILITY

    def test_threshold_boundary(self):
        s = make_strategy(volatility=2.0)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.LOW_VOLATILITY  # <= threshold = low


class TestGetSignal:
    def test_high_vol_uses_scalping(self, dummy_df):
        s = make_strategy(volatility=3.0, ind_signal='BUY', ind_conf=0.7)
        signal, conf, details = s.get_signal(dummy_df)
        assert details['strategy_used'] == 'SCALPING'
        assert signal == Signal.BUY

    def test_low_vol_uses_swing(self, dummy_df):
        s = make_strategy(volatility=1.0, ai_signal='BUY', ai_conf=0.9, ai_pred=0.5)
        signal, conf, details = s.get_signal(dummy_df)
        assert details['strategy_used'] == 'SWING'

    def test_neutral_on_no_signals(self, dummy_df):
        s = make_strategy(volatility=3.0)
        signal, conf, details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL


class TestSwingStrategy:
    def test_ai_weight_dominates(self, dummy_df):
        """AI con señal BUY fuerte debe dominar sobre indicadores neutrales."""
        s = make_strategy(volatility=1.0, ind_signal='NEUTRAL', ind_conf=0.0,
                          ai_signal='BUY', ai_conf=0.9, ai_pred=0.5)
        signal, conf, details = s.get_signal(dummy_df)
        assert signal == Signal.BUY

    def test_conflicting_signals(self, dummy_df):
        """Indicadores SELL + AI BUY: AI (70%) debe ganar."""
        s = make_strategy(volatility=1.0, ind_signal='SELL', ind_conf=0.7,
                          ai_signal='BUY', ai_conf=0.9, ai_pred=0.5)
        signal, conf, details = s.get_signal(dummy_df)
        # combined = 1*0.7*0.9 + (-1)*0.3*0.7 = 0.63 - 0.21 = 0.42 > 0.3
        assert signal == Signal.BUY


class TestShouldOpenPosition:
    def test_neutral_returns_false(self):
        s = make_strategy()
        assert s.should_open_position(Signal.NEUTRAL, 0.9, 0, 3) is False

    def test_max_positions_returns_false(self):
        s = make_strategy()
        assert s.should_open_position(Signal.BUY, 0.9, 3, 3) is False

    def test_low_confidence_scalping_returns_false(self):
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.4, 0, 3) is False

    def test_sufficient_confidence_scalping(self):
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.6, 0, 3) is True

    def test_low_confidence_swing_returns_false(self):
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.6, 0, 3) is False

    def test_sufficient_confidence_swing(self):
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.7, 0, 3) is True


class TestPositionSize:
    def test_basic_calculation(self):
        s = make_strategy()
        qty = s.calculate_position_size(10000, 0.01, 50000)
        assert pytest.approx(qty, rel=1e-6) == 0.002  # 100/50000

    def test_zero_price_returns_zero(self):
        s = make_strategy()
        qty = s.calculate_position_size(10000, 0.01, 0)
        # Division by zero should be handled
        assert qty == 0.0


class TestStopLossTakeProfit:
    def test_buy_sl_tp(self):
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(100.0, Signal.BUY, 2.0, 4.0)
        assert pytest.approx(sl) == 98.0
        assert pytest.approx(tp) == 104.0

    def test_sell_sl_tp(self):
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(100.0, Signal.SELL, 2.0, 4.0)
        assert pytest.approx(sl) == 102.0
        assert pytest.approx(tp) == 96.0

    def test_neutral_sl_tp(self):
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(100.0, Signal.NEUTRAL, 2.0, 4.0)
        assert sl == 100.0
        assert tp == 100.0


class TestCheckInterval:
    def test_scalping_interval(self):
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        assert s.get_check_interval() == 5

    def test_swing_interval(self):
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        assert s.get_check_interval() == 60

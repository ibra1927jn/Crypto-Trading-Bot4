"""Tests para HybridStrategy"""
import numpy as np
import pandas as pd
import pytest

from strategies.strategy import HybridStrategy, MarketCondition, Signal


class MockDataManager:
    def __init__(self, volatility=1.0):
        self._volatility = volatility

    def calculate_volatility(self):
        return self._volatility


class MockIndicators:
    def __init__(self, signal='NEUTRAL', confidence=0.0):
        self._signal = signal
        self._confidence = confidence

    def get_combined_signal(self, df, bollinger_signal=None):
        return self._signal, self._confidence

    def get_macd_signal(self, df):
        return self._signal, self._confidence

    def get_bollinger_signal(self, df):
        return self._signal, self._confidence


class MockAIPredictor:
    def __init__(self, signal='NEUTRAL', confidence=0.0, prediction=0.0):
        self._signal = signal
        self._confidence = confidence
        self._prediction = prediction  # pct value (float)

    def predict(self, df):
        return self._prediction, self._confidence

    def get_signal(self, df, threshold=0.65):
        return self.signal_from_prediction(
            self._prediction, self._confidence, threshold,
        )

    def signal_from_prediction(self, pct, confidence, threshold=0.65):
        if pct > 0.02 and confidence >= threshold:
            return 'BUY'
        elif pct < -0.02 and confidence >= threshold:
            return 'SELL'
        return 'NEUTRAL'


def make_strategy(volatility=1.0, ind_signal='NEUTRAL', ind_conf=0.0,
                  ai_signal='NEUTRAL', ai_conf=0.0, ai_pred=0.0):
    dm = MockDataManager(volatility)
    ind = MockIndicators(ind_signal, ind_conf)
    ai = MockAIPredictor(ai_signal, ai_conf, ai_pred)
    config = {
        'VOLATILITY_THRESHOLD': 2.0,
        'SCALPING_CONFIG': {'check_interval': 5},
        'SWING_CONFIG': {
            'check_interval': 60,
            'ai_confidence_threshold': 0.65,
        },
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
        signal, _conf, details = s.get_signal(dummy_df)
        assert details['strategy_used'] == 'SCALPING'
        assert signal == Signal.BUY

    def test_low_vol_uses_swing(self, dummy_df):
        s = make_strategy(volatility=1.0, ai_conf=0.9, ai_pred=0.5)
        _signal, _conf, details = s.get_signal(dummy_df)
        assert details['strategy_used'] == 'SWING'

    def test_neutral_on_no_signals(self, dummy_df):
        s = make_strategy(volatility=3.0)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL


class TestSwingStrategy:
    def test_ai_weight_dominates(self, dummy_df):
        """AI con señal BUY fuerte debe dominar sobre indicadores neutrales."""
        s = make_strategy(volatility=1.0, ind_signal='NEUTRAL', ind_conf=0.0,
                          ai_conf=0.9, ai_pred=0.5)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.BUY

    def test_conflicting_signals(self, dummy_df):
        """Indicadores SELL + AI BUY: AI (70%) debe ganar."""
        s = make_strategy(volatility=1.0, ind_signal='SELL', ind_conf=0.7,
                          ai_conf=0.9, ai_pred=0.5)
        signal, _conf, _details = s.get_signal(dummy_df)
        # combined = 1*0.7*0.9 + (-1)*0.3*0.7 = 0.63 - 0.21 = 0.42 > 0.3
        assert signal == Signal.BUY


class TestSwingStrategyLogging:
    def test_swing_does_not_crash_on_log(self, dummy_df):
        """predict() returning string must not crash logger."""
        import logging
        s = make_strategy(volatility=1.0, ind_signal='BUY', ind_conf=0.7,
                          ai_conf=0.9, ai_pred=0.5)
        logging.basicConfig(level=logging.DEBUG)
        signal, _conf, details = s.get_signal(dummy_df)
        # Must not silently fall to NEUTRAL due to exception
        assert signal == Signal.BUY
        assert 'error' not in details


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
        sl, tp = s.calculate_stop_loss_take_profit(
            100.0, Signal.SELL, 2.0, 4.0,
        )
        assert pytest.approx(sl) == 102.0
        assert pytest.approx(tp) == 96.0

    def test_neutral_sl_tp(self):
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(
            100.0, Signal.NEUTRAL, 2.0, 4.0,
        )
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


class TestGetStrategySummary:
    def test_summary_keys(self):
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        summary = s.get_strategy_summary()
        assert 'current_condition' in summary
        assert 'volatility_threshold' in summary
        assert 'current_volatility' in summary
        assert 'last_signal' in summary
        assert 'check_interval' in summary
        assert 'strategy_active' in summary
        assert 'ai_enabled' in summary

    def test_high_vol_summary(self):
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        summary = s.get_strategy_summary()
        assert summary['strategy_active'] == 'SCALPING'
        assert summary['ai_enabled'] is False

    def test_low_vol_summary(self):
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        summary = s.get_strategy_summary()
        assert summary['strategy_active'] == 'SWING'
        assert summary['ai_enabled'] is True


class TestScalpingSignals:
    def test_scalping_sell(self, dummy_df):
        s = make_strategy(volatility=3.0, ind_signal='SELL', ind_conf=0.8)
        signal, _conf, details = s.get_signal(dummy_df)
        assert signal == Signal.SELL
        assert details['strategy_used'] == 'SCALPING'

    def test_scalping_neutral(self, dummy_df):
        s = make_strategy(volatility=3.0, ind_signal='NEUTRAL', ind_conf=0.0)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL


class TestErrorBranches:
    def test_analyze_market_condition_error(self):
        """calculate_volatility() raises → UNKNOWN."""
        dm = MockDataManager(volatility=1.0)

        def _raise():
            raise RuntimeError("fail")
        dm.calculate_volatility = _raise
        ind = MockIndicators()
        ai = MockAIPredictor()
        config = {
            'VOLATILITY_THRESHOLD': 2.0,
            'SCALPING_CONFIG': {'check_interval': 5},
            'SWING_CONFIG': {
                'check_interval': 60,
                'ai_confidence_threshold': 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.UNKNOWN

    def test_get_signal_outer_exception(self, dummy_df):
        """If a sub-strategy bypasses its inner handler and raises,
        get_signal's outer except returns NEUTRAL with error key.
        """
        s = make_strategy(volatility=3.0, ind_signal='BUY', ind_conf=0.7)

        def _raise(df):
            raise RuntimeError("boom")
        s._scalping_strategy = _raise

        signal, _conf, details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL
        assert 'error' in details

    def test_get_signal_calls_calculate_volatility_once(self, dummy_df):
        """Regression: get_signal must not re-invoke calculate_volatility
        for the details dict; reuse the value cached by analyze_market_condition.
        """
        call_count = 0

        class CountingDataManager:
            def calculate_volatility(self):
                nonlocal call_count
                call_count += 1
                return 1.0

        dm = CountingDataManager()
        ind = MockIndicators()
        ai = MockAIPredictor()
        config = {
            'VOLATILITY_THRESHOLD': 2.0,
            'SCALPING_CONFIG': {'check_interval': 5},
            'SWING_CONFIG': {
                'check_interval': 60,
                'ai_confidence_threshold': 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        _signal, _conf, details = s.get_signal(dummy_df)
        assert call_count == 1
        assert details['volatility'] == 1.0

    def test_get_signal_unknown_condition_no_error(self, dummy_df):
        """UNKNOWN condition: analyze fails but volatility works."""
        call_count = 0

        class FailOnceDataManager:
            """First call raises; second succeeds."""
            def calculate_volatility(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("fail")
                return 1.5

        dm = FailOnceDataManager()
        ind = MockIndicators()
        ai = MockAIPredictor()
        config = {
            'VOLATILITY_THRESHOLD': 2.0,
            'SCALPING_CONFIG': {'check_interval': 5},
            'SWING_CONFIG': {
                'check_interval': 60,
                'ai_confidence_threshold': 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        signal, _conf, details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL
        assert details['strategy_used'] == 'NONE'

    def test_scalping_strategy_error(self, dummy_df):
        """Error branch: indicator raises in scalping → NEUTRAL with error."""
        dm = MockDataManager(volatility=3.0)
        ind = MockIndicators()

        def _raise(df):
            raise RuntimeError("bad")

        ind.get_combined_signal = _raise
        ai = MockAIPredictor()
        config = {
            'VOLATILITY_THRESHOLD': 2.0,
            'SCALPING_CONFIG': {'check_interval': 5},
            'SWING_CONFIG': {
                'check_interval': 60,
                'ai_confidence_threshold': 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        signal, _conf, _details = s.get_signal(dummy_df)
        # scalping error returns NEUTRAL, then get_signal wraps it
        assert signal == Signal.NEUTRAL

    def test_swing_strategy_error(self, dummy_df):
        """Error branch: AI predictor raises in swing → NEUTRAL with error."""
        dm = MockDataManager(volatility=1.0)
        ind = MockIndicators()
        ai = MockAIPredictor()

        def _raise(df):
            raise RuntimeError("ai fail")

        ai.predict = _raise
        config = {
            'VOLATILITY_THRESHOLD': 2.0,
            'SCALPING_CONFIG': {'check_interval': 5},
            'SWING_CONFIG': {
                'check_interval': 60,
                'ai_confidence_threshold': 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL

    def test_should_open_position_error(self):
        """Error branch: exception in should_open_position → False."""
        s = make_strategy()
        # Force an error by making confidence non-numeric
        result = s.should_open_position(Signal.BUY, "not_a_number", 0, 3)
        assert result is False

    def test_calculate_position_size_error(self):
        """Error branch: division by zero in position size → 0.0."""
        s = make_strategy()
        # ZeroDivisionError
        qty = s.calculate_position_size(10000, 0.01, 0)
        assert qty == 0.0

    def test_calculate_position_size_exception(self):
        """Error branch: non-numeric balance triggers except → 0.0."""
        s = make_strategy()
        qty = s.calculate_position_size("bad", 0.01, 50000)
        assert qty == 0.0

    def test_calculate_sl_tp_error(self):
        """Error branch: bad entry_price type → returns entry, entry."""
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(
            "not_a_number", Signal.BUY, 2.0, 4.0,
        )
        assert sl == "not_a_number"
        assert tp == "not_a_number"


class TestSwingNeutralSignal:
    def test_swing_neutral_when_combined_near_zero(self, dummy_df):
        """Weak signals combine to NEUTRAL."""
        s = make_strategy(
            volatility=1.0, ind_signal='NEUTRAL',
            ind_conf=0.0, ai_conf=0.5, ai_pred=0.01,
        )
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL


class TestSwingSellSignal:
    def test_ai_sell_dominates(self, dummy_df):
        s = make_strategy(
            volatility=1.0, ind_signal='NEUTRAL',
            ind_conf=0.0, ai_conf=0.9, ai_pred=-0.5,
        )
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.SELL

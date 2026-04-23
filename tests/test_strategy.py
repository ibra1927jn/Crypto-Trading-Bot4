"""Tests para HybridStrategy."""
import logging
from typing import NoReturn

import numpy as np
import pandas as pd
import pytest

from strategies.strategy import HybridStrategy, MarketCondition, Signal


class MockDataManager:
    """Stand-in DataManager returning a fixed calculated volatility."""

    def __init__(self, volatility: float = 1.0) -> None:
        """Store the volatility value that calculate_volatility() will return."""
        self._volatility = volatility

    def calculate_volatility(self) -> float:
        """Return the stored volatility unchanged."""
        return self._volatility


class MockIndicators:
    """Stand-in TechnicalIndicators returning a fixed (signal, confidence) pair."""

    def __init__(self, signal: str = "NEUTRAL", confidence: float = 0.0) -> None:
        """Store the signal/confidence returned by every mocked getter."""
        self._signal = signal
        self._confidence = confidence

    def get_combined_signal(
        self,
        df: pd.DataFrame,
        bollinger_signal: tuple[str, float] | None = None,
    ) -> tuple[str, float]:
        """Return the fixed (signal, confidence) pair."""
        return self._signal, self._confidence

    def get_macd_signal(self, df: pd.DataFrame) -> tuple[str, float]:
        """Return the fixed (signal, confidence) pair."""
        return self._signal, self._confidence

    def get_bollinger_signal(self, df: pd.DataFrame) -> tuple[str, float]:
        """Return the fixed (signal, confidence) pair."""
        return self._signal, self._confidence


class MockAIPredictor:
    """Stand-in AI_Predictor with fixed prediction and confidence outputs."""

    def __init__(
        self,
        signal: str = "NEUTRAL",
        confidence: float = 0.0,
        prediction: float = 0.0,
    ) -> None:
        """Store the fixed signal/confidence/prediction values used by the stubs."""
        self._signal = signal
        self._confidence = confidence
        self._prediction = prediction  # pct value (float)

    def predict(self, df: pd.DataFrame) -> tuple[float, float]:
        """Return the stored (prediction, confidence) tuple."""
        return self._prediction, self._confidence

    def get_signal(
        self, df: pd.DataFrame, threshold: float = 0.65,
    ) -> str:
        """Return a signal derived from the stored prediction and confidence."""
        return self.signal_from_prediction(
            self._prediction, self._confidence, threshold,
        )

    def signal_from_prediction(
        self, pct: float, confidence: float, threshold: float = 0.65,
    ) -> str:
        """Replicate AI_Predictor.signal_from_prediction()'s BUY/SELL/NEUTRAL map."""
        if pct > 0.02 and confidence >= threshold:
            return "BUY"
        if pct < -0.02 and confidence >= threshold:
            return "SELL"
        return "NEUTRAL"


def make_strategy(
    volatility: float = 1.0,
    ind_signal: str = "NEUTRAL",
    ind_conf: float = 0.0,
    ai_signal: str = "NEUTRAL",
    ai_conf: float = 0.0,
    ai_pred: float = 0.0,
) -> HybridStrategy:
    """Build a HybridStrategy wired with the three mock dependencies."""
    dm = MockDataManager(volatility)
    ind = MockIndicators(ind_signal, ind_conf)
    ai = MockAIPredictor(ai_signal, ai_conf, ai_pred)
    config = {
        "VOLATILITY_THRESHOLD": 2.0,
        "SCALPING_CONFIG": {"check_interval": 5},
        "SWING_CONFIG": {
            "check_interval": 60,
            "ai_confidence_threshold": 0.65,
        },
    }
    return HybridStrategy(dm, ind, ai, config)


@pytest.fixture
def dummy_df() -> pd.DataFrame:
    """Minimal 50-row OHLCV-like DataFrame with 'close' and 'rsi' columns."""
    n = 50
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    return pd.DataFrame({
        "close": close,
        "rsi": rng.uniform(30, 70, n),
    })


class TestMarketCondition:
    """Volatility-based classification tests for analyze_market_condition()."""

    def test_high_volatility(self) -> None:
        """Volatility above the threshold maps to HIGH_VOLATILITY."""
        s = make_strategy(volatility=3.0)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.HIGH_VOLATILITY

    def test_low_volatility(self) -> None:
        """Volatility below the threshold maps to LOW_VOLATILITY."""
        s = make_strategy(volatility=1.0)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.LOW_VOLATILITY

    def test_threshold_boundary(self) -> None:
        """Volatility equal to the threshold is treated as LOW_VOLATILITY."""
        s = make_strategy(volatility=2.0)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.LOW_VOLATILITY  # <= threshold = low


class TestGetSignal:
    """Tests that get_signal() dispatches between scalping and swing strategies."""

    def test_high_vol_uses_scalping(self, dummy_df: pd.DataFrame) -> None:
        """High volatility selects the SCALPING branch."""
        s = make_strategy(volatility=3.0, ind_signal="BUY", ind_conf=0.7)
        signal, _conf, details = s.get_signal(dummy_df)
        assert details["strategy_used"] == "SCALPING"
        assert signal == Signal.BUY

    def test_low_vol_uses_swing(self, dummy_df: pd.DataFrame) -> None:
        """Low volatility selects the SWING branch."""
        s = make_strategy(volatility=1.0, ai_conf=0.9, ai_pred=0.5)
        _signal, _conf, details = s.get_signal(dummy_df)
        assert details["strategy_used"] == "SWING"

    def test_neutral_on_no_signals(self, dummy_df: pd.DataFrame) -> None:
        """No inputs → NEUTRAL (scalping branch)."""
        s = make_strategy(volatility=3.0)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL


class TestSwingStrategy:
    """Swing-branch tests: how AI and indicator signals combine."""

    def test_ai_weight_dominates(self, dummy_df: pd.DataFrame) -> None:
        """AI con señal BUY fuerte debe dominar sobre indicadores neutrales."""
        s = make_strategy(volatility=1.0, ind_signal="NEUTRAL", ind_conf=0.0,
                          ai_conf=0.9, ai_pred=0.5)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.BUY

    def test_conflicting_signals(self, dummy_df: pd.DataFrame) -> None:
        """Indicadores SELL + AI BUY: AI (70%) debe ganar."""
        s = make_strategy(volatility=1.0, ind_signal="SELL", ind_conf=0.7,
                          ai_conf=0.9, ai_pred=0.5)
        signal, _conf, _details = s.get_signal(dummy_df)
        # combined = 1*0.7*0.9 + (-1)*0.3*0.7 = 0.63 - 0.21 = 0.42 > 0.3
        assert signal == Signal.BUY


class TestSwingStrategyLogging:
    """Regression tests around logging in the swing branch."""

    def test_swing_does_not_crash_on_log(self, dummy_df: pd.DataFrame) -> None:
        """predict() returning string must not crash logger."""
        s = make_strategy(volatility=1.0, ind_signal="BUY", ind_conf=0.7,
                          ai_conf=0.9, ai_pred=0.5)
        logging.basicConfig(level=logging.DEBUG)
        signal, _conf, details = s.get_signal(dummy_df)
        # Must not silently fall to NEUTRAL due to exception
        assert signal == Signal.BUY
        assert "error" not in details


class TestShouldOpenPosition:
    """Tests for should_open_position() gating rules."""

    def test_neutral_returns_false(self) -> None:
        """NEUTRAL signal never opens a position."""
        s = make_strategy()
        assert s.should_open_position(Signal.NEUTRAL, 0.9, 0, 3) is False

    def test_max_positions_returns_false(self) -> None:
        """Hitting the max-positions cap blocks new positions."""
        s = make_strategy()
        assert s.should_open_position(Signal.BUY, 0.9, 3, 3) is False

    def test_low_confidence_scalping_returns_false(self) -> None:
        """Low confidence in SCALPING mode blocks position entry."""
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.4, 0, 3) is False

    def test_sufficient_confidence_scalping(self) -> None:
        """Sufficient confidence in SCALPING mode allows entry."""
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.6, 0, 3) is True

    def test_low_confidence_swing_returns_false(self) -> None:
        """Low confidence in SWING mode blocks position entry."""
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.6, 0, 3) is False

    def test_sufficient_confidence_swing(self) -> None:
        """Sufficient confidence in SWING mode allows entry."""
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        assert s.should_open_position(Signal.BUY, 0.7, 0, 3) is True


class TestPositionSize:
    """Tests for calculate_position_size()."""

    def test_basic_calculation(self) -> None:
        """Return balance * risk / price for valid inputs."""
        s = make_strategy()
        qty = s.calculate_position_size(10000, 0.01, 50000)
        assert pytest.approx(qty, rel=1e-6) == 0.002  # 100/50000

    def test_zero_price_returns_zero(self) -> None:
        """A zero current price short-circuits to 0.0 (no div-by-zero)."""
        s = make_strategy()
        qty = s.calculate_position_size(10000, 0.01, 0)
        # Division by zero should be handled
        assert qty == 0.0


class TestStopLossTakeProfit:
    """Tests for calculate_stop_loss_take_profit() across signal types."""

    def test_buy_sl_tp(self) -> None:
        """BUY signal places SL below entry and TP above."""
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(100.0, Signal.BUY, 2.0, 4.0)
        assert pytest.approx(sl) == 98.0
        assert pytest.approx(tp) == 104.0

    def test_sell_sl_tp(self) -> None:
        """SELL signal places SL above entry and TP below."""
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(
            100.0, Signal.SELL, 2.0, 4.0,
        )
        assert pytest.approx(sl) == 102.0
        assert pytest.approx(tp) == 96.0

    def test_neutral_sl_tp(self) -> None:
        """NEUTRAL signal returns (entry, entry) — no trade targets."""
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(
            100.0, Signal.NEUTRAL, 2.0, 4.0,
        )
        assert sl == 100.0
        assert tp == 100.0


class TestCheckInterval:
    """Tests that get_check_interval() returns the mode-specific cadence."""

    def test_scalping_interval(self) -> None:
        """SCALPING mode uses the scalping check interval."""
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        assert s.get_check_interval() == 5

    def test_swing_interval(self) -> None:
        """SWING mode uses the swing check interval."""
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        assert s.get_check_interval() == 60


class TestGetStrategySummary:
    """Tests for the get_strategy_summary() report dict."""

    def test_summary_keys(self) -> None:
        """Summary dict exposes the expected bookkeeping keys."""
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        summary = s.get_strategy_summary()
        assert "current_condition" in summary
        assert "volatility_threshold" in summary
        assert "current_volatility" in summary
        assert "last_signal" in summary
        assert "check_interval" in summary
        assert "strategy_active" in summary
        assert "ai_enabled" in summary

    def test_high_vol_summary(self) -> None:
        """HIGH volatility summary reports SCALPING and AI disabled."""
        s = make_strategy(volatility=3.0)
        s.analyze_market_condition()
        summary = s.get_strategy_summary()
        assert summary["strategy_active"] == "SCALPING"
        assert summary["ai_enabled"] is False

    def test_low_vol_summary(self) -> None:
        """LOW volatility summary reports SWING and AI enabled."""
        s = make_strategy(volatility=1.0)
        s.analyze_market_condition()
        summary = s.get_strategy_summary()
        assert summary["strategy_active"] == "SWING"
        assert summary["ai_enabled"] is True


class TestScalpingSignals:
    """Tests of the SCALPING branch under SELL and NEUTRAL indicator signals."""

    def test_scalping_sell(self, dummy_df: pd.DataFrame) -> None:
        """Indicator SELL with high confidence → Signal.SELL via SCALPING."""
        s = make_strategy(volatility=3.0, ind_signal="SELL", ind_conf=0.8)
        signal, _conf, details = s.get_signal(dummy_df)
        assert signal == Signal.SELL
        assert details["strategy_used"] == "SCALPING"

    def test_scalping_neutral(self, dummy_df: pd.DataFrame) -> None:
        """Indicator NEUTRAL → Signal.NEUTRAL."""
        s = make_strategy(volatility=3.0, ind_signal="NEUTRAL", ind_conf=0.0)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL


class TestErrorBranches:
    """Error-path tests: exceptions in sub-strategies must not crash get_signal()."""

    def test_analyze_market_condition_error(self) -> None:
        """calculate_volatility() raises → UNKNOWN."""
        dm = MockDataManager(volatility=1.0)

        def _raise() -> NoReturn:
            raise RuntimeError("fail")
        dm.calculate_volatility = _raise
        ind = MockIndicators()
        ai = MockAIPredictor()
        config = {
            "VOLATILITY_THRESHOLD": 2.0,
            "SCALPING_CONFIG": {"check_interval": 5},
            "SWING_CONFIG": {
                "check_interval": 60,
                "ai_confidence_threshold": 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        cond = s.analyze_market_condition()
        assert cond == MarketCondition.UNKNOWN

    def test_get_signal_outer_exception(self, dummy_df: pd.DataFrame) -> None:
        """If a sub-strategy bypasses its inner handler and raises, return NEUTRAL.

        get_signal's outer except returns NEUTRAL with error key.
        """
        s = make_strategy(volatility=3.0, ind_signal="BUY", ind_conf=0.7)

        def _raise(df: pd.DataFrame) -> NoReturn:
            raise RuntimeError("boom")
        s._scalping_strategy = _raise

        signal, _conf, details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL
        assert "error" in details

    def test_get_signal_calls_calculate_volatility_once(
        self, dummy_df: pd.DataFrame,
    ) -> None:
        """Regression: get_signal must not re-invoke calculate_volatility.

        For the details dict, reuse the value cached by analyze_market_condition.
        """
        call_count = 0

        class CountingDataManager:
            def calculate_volatility(self) -> float:
                nonlocal call_count
                call_count += 1
                return 1.0

        dm = CountingDataManager()
        ind = MockIndicators()
        ai = MockAIPredictor()
        config = {
            "VOLATILITY_THRESHOLD": 2.0,
            "SCALPING_CONFIG": {"check_interval": 5},
            "SWING_CONFIG": {
                "check_interval": 60,
                "ai_confidence_threshold": 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        _signal, _conf, details = s.get_signal(dummy_df)
        assert call_count == 1
        assert details["volatility"] == 1.0

    def test_get_signal_unknown_condition_no_error(
        self, dummy_df: pd.DataFrame,
    ) -> None:
        """UNKNOWN condition: analyze fails but volatility works."""
        call_count = 0

        class FailOnceDataManager:
            """First call raises; second succeeds."""

            def calculate_volatility(self) -> float:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("fail")
                return 1.5

        dm = FailOnceDataManager()
        ind = MockIndicators()
        ai = MockAIPredictor()
        config = {
            "VOLATILITY_THRESHOLD": 2.0,
            "SCALPING_CONFIG": {"check_interval": 5},
            "SWING_CONFIG": {
                "check_interval": 60,
                "ai_confidence_threshold": 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        signal, _conf, details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL
        assert details["strategy_used"] == "NONE"

    def test_scalping_strategy_error(self, dummy_df: pd.DataFrame) -> None:
        """Error branch: indicator raises in scalping → NEUTRAL with error."""
        dm = MockDataManager(volatility=3.0)
        ind = MockIndicators()

        def _raise(df: pd.DataFrame) -> NoReturn:
            raise RuntimeError("bad")

        ind.get_combined_signal = _raise
        ai = MockAIPredictor()
        config = {
            "VOLATILITY_THRESHOLD": 2.0,
            "SCALPING_CONFIG": {"check_interval": 5},
            "SWING_CONFIG": {
                "check_interval": 60,
                "ai_confidence_threshold": 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        signal, _conf, _details = s.get_signal(dummy_df)
        # scalping error returns NEUTRAL, then get_signal wraps it
        assert signal == Signal.NEUTRAL

    def test_swing_strategy_error(self, dummy_df: pd.DataFrame) -> None:
        """Error branch: AI predictor raises in swing → NEUTRAL with error."""
        dm = MockDataManager(volatility=1.0)
        ind = MockIndicators()
        ai = MockAIPredictor()

        def _raise(df: pd.DataFrame) -> NoReturn:
            raise RuntimeError("ai fail")

        ai.predict = _raise
        config = {
            "VOLATILITY_THRESHOLD": 2.0,
            "SCALPING_CONFIG": {"check_interval": 5},
            "SWING_CONFIG": {
                "check_interval": 60,
                "ai_confidence_threshold": 0.65,
            },
        }
        s = HybridStrategy(dm, ind, ai, config)
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL

    def test_should_open_position_error(self) -> None:
        """Error branch: exception in should_open_position → False."""
        s = make_strategy()
        # Force an error by making confidence non-numeric
        result = s.should_open_position(Signal.BUY, "not_a_number", 0, 3)
        assert result is False

    def test_calculate_position_size_error(self) -> None:
        """Error branch: division by zero in position size → 0.0."""
        s = make_strategy()
        # ZeroDivisionError
        qty = s.calculate_position_size(10000, 0.01, 0)
        assert qty == 0.0

    def test_calculate_position_size_exception(self) -> None:
        """Error branch: non-numeric balance triggers except → 0.0."""
        s = make_strategy()
        qty = s.calculate_position_size("bad", 0.01, 50000)
        assert qty == 0.0

    def test_calculate_sl_tp_error(self) -> None:
        """Error branch: bad entry_price type → returns entry, entry."""
        s = make_strategy()
        sl, tp = s.calculate_stop_loss_take_profit(
            "not_a_number", Signal.BUY, 2.0, 4.0,
        )
        assert sl == "not_a_number"
        assert tp == "not_a_number"


class TestSwingNeutralSignal:
    """Tests asserting the SWING branch settles on NEUTRAL for weak inputs."""

    def test_swing_neutral_when_combined_near_zero(
        self, dummy_df: pd.DataFrame,
    ) -> None:
        """Weak signals combine to NEUTRAL."""
        s = make_strategy(
            volatility=1.0, ind_signal="NEUTRAL",
            ind_conf=0.0, ai_conf=0.5, ai_pred=0.01,
        )
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.NEUTRAL


class TestSwingSellSignal:
    """Tests asserting the SWING branch emits SELL when AI predicts a strong drop."""

    def test_ai_sell_dominates(self, dummy_df: pd.DataFrame) -> None:
        """Strong negative AI prediction with neutral indicators → Signal.SELL."""
        s = make_strategy(
            volatility=1.0, ind_signal="NEUTRAL",
            ind_conf=0.0, ai_conf=0.9, ai_pred=-0.5,
        )
        signal, _conf, _details = s.get_signal(dummy_df)
        assert signal == Signal.SELL

"""Tests para AI_Predictor - tensor shapes y lógica de predicción."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import torch

from modules.ai_predictor import (
    AI_Predictor,
    CryptoTransformer,
    PositionalEncoding,
)


class TestCryptoTransformer:
    def test_forward_shape(self) -> None:
        """El modelo debe aceptar (batch, seq, 8) y devolver (batch, 1)."""
        model = CryptoTransformer()
        x = torch.randn(2, 180, 8)
        out = model(x)
        assert out.shape == (2, 1)

    def test_single_sample(self) -> None:
        model = CryptoTransformer()
        x = torch.randn(1, 180, 8)
        out = model(x)
        assert out.shape == (1, 1)

    def test_different_seq_lengths(self) -> None:
        model = CryptoTransformer()
        for seq_len in [50, 100, 180, 300]:
            x = torch.randn(1, seq_len, 8)
            out = model(x)
            assert out.shape == (1, 1)


class TestPositionalEncoding:
    def test_output_shape(self) -> None:
        pe = PositionalEncoding(128)
        x = torch.randn(1, 180, 128)
        out = pe(x)
        assert out.shape == x.shape

    def test_adds_positional_info(self) -> None:
        pe = PositionalEncoding(128)
        x = torch.zeros(1, 10, 128)
        out = pe(x)
        assert not torch.all(out == 0)


class TestAIPredictorPredict:
    def _make_df(self, n: int = 300) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        close = 100 + np.cumsum(rng.standard_normal(n) * 0.1)
        close = np.maximum(close, 1.0)
        return pd.DataFrame({
            "open": close + rng.standard_normal(n) * 0.01,
            "high": close + abs(rng.standard_normal(n) * 0.05),
            "low": close - abs(rng.standard_normal(n) * 0.05),
            "close": close,
            "volume": rng.integers(100, 10000, n).astype(float),
            "funding_rate": rng.uniform(-0.001, 0.001, n),
        })

    def test_predict_returns_tuple(self) -> None:
        predictor = AI_Predictor({})
        df = self._make_df(300)
        result = predictor.predict(df)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_predict_insufficient_data(self) -> None:
        predictor = AI_Predictor({})
        df = self._make_df(50)
        pct, conf = predictor.predict(df)
        assert pct == 0.0
        assert conf == 0.0

    def test_predict_with_model_loaded(self) -> None:
        """Test predict path when model is available."""
        predictor = AI_Predictor({})
        predictor.model = CryptoTransformer().to(predictor.device)
        predictor.model.eval()
        df = self._make_df(300)
        pct, conf = predictor.predict(df)
        assert isinstance(pct, float)
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 0.95

    def test_predict_error_returns_zero(self) -> None:
        """Test that predict returns (0.0, 0.0) on internal error."""
        predictor = AI_Predictor({})
        predictor.model = MagicMock()
        predictor.model.side_effect = RuntimeError("test error")
        df = self._make_df(300)
        pct, conf = predictor.predict(df)
        assert pct == 0.0
        assert conf == 0.0


class TestAIPredictorSignalFromPrediction:
    def test_buy_above_threshold(self) -> None:
        predictor = AI_Predictor({})
        assert predictor.signal_from_prediction(0.05, 0.8) == "BUY"

    def test_sell_below_threshold(self) -> None:
        predictor = AI_Predictor({})
        assert predictor.signal_from_prediction(-0.05, 0.8) == "SELL"

    def test_neutral_low_confidence(self) -> None:
        predictor = AI_Predictor({})
        assert predictor.signal_from_prediction(0.05, 0.3) == "NEUTRAL"

    def test_neutral_small_pct(self) -> None:
        predictor = AI_Predictor({})
        assert predictor.signal_from_prediction(0.01, 0.9) == "NEUTRAL"

    def test_custom_threshold(self) -> None:
        predictor = AI_Predictor({})
        assert predictor.signal_from_prediction(
            0.05, 0.5, threshold=0.4,
        ) == "BUY"

    def test_get_signal_calls_predict_only_once(self) -> None:
        """Regression: get_signal must not invoke predict() twice."""
        predictor = AI_Predictor({})
        with patch.object(
            predictor, "predict", return_value=(0.05, 0.8),
        ) as mock_predict:
            predictor.get_signal(pd.DataFrame())
            assert mock_predict.call_count == 1


class TestAIPredictorGetSignal:
    def test_get_signal_neutral_no_model(self) -> None:
        predictor = AI_Predictor({})
        df = pd.DataFrame({"close": [100.0] * 300})
        signal = predictor.get_signal(df)
        assert signal == "NEUTRAL"

    def test_get_signal_buy(self) -> None:
        predictor = AI_Predictor({})
        with patch.object(predictor, "predict", return_value=(0.05, 0.8)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == "BUY"

    def test_get_signal_sell(self) -> None:
        predictor = AI_Predictor({})
        with patch.object(predictor, "predict", return_value=(-0.05, 0.8)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == "SELL"

    def test_get_signal_neutral_low_confidence(self) -> None:
        predictor = AI_Predictor({})
        with patch.object(predictor, "predict", return_value=(0.05, 0.3)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == "NEUTRAL"

    def test_get_signal_neutral_small_pct(self) -> None:
        predictor = AI_Predictor({})
        with patch.object(predictor, "predict", return_value=(0.01, 0.9)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == "NEUTRAL"

    def test_get_signal_custom_threshold(self) -> None:
        predictor = AI_Predictor({})
        with patch.object(predictor, "predict", return_value=(0.05, 0.5)):
            signal = predictor.get_signal(pd.DataFrame(), threshold=0.4)
            assert signal == "BUY"


class TestAIPredictorLoadModel:
    def test_load_model_no_file(self) -> None:
        """Model stays None when file doesn't exist."""
        predictor = AI_Predictor({})
        assert predictor.model is None

    def test_load_model_bad_file(self, tmp_path: Path) -> None:
        """Model is instantiated even if state_dict load fails (logs error)."""
        bad_model = tmp_path / "bad_model.pth"
        bad_model.write_text("not a model")
        predictor = AI_Predictor({})
        predictor.model_path = str(bad_model)
        predictor._load_model()
        # Model object is created before load_state_dict, so it persists
        assert predictor.model is not None

    def test_load_model_success(self, tmp_path: Path) -> None:
        """Successful load sets model to eval mode."""
        model = CryptoTransformer()
        model_path = tmp_path / "good_model.pth"
        torch.save(model.state_dict(), str(model_path))
        predictor = AI_Predictor({})
        predictor.model_path = str(model_path)
        predictor._load_model()
        assert predictor.model is not None
        assert not predictor.model.training  # eval() sets training=False


class TestAIPredictorPostDropna:
    def _make_df(self, n: int = 300) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        close = 100 + np.cumsum(rng.standard_normal(n) * 0.1)
        close = np.maximum(close, 1.0)
        return pd.DataFrame({
            "open": close + rng.standard_normal(n) * 0.01,
            "high": close + abs(rng.standard_normal(n) * 0.05),
            "low": close - abs(rng.standard_normal(n) * 0.05),
            "close": close,
            "volume": rng.integers(100, 10000, n).astype(float),
            "funding_rate": rng.uniform(-0.001, 0.001, n),
        })

    def test_insufficient_data_after_dropna(self) -> None:
        """Data passes initial check but is too short after dropna."""
        predictor = AI_Predictor({})
        predictor.model = CryptoTransformer().to(predictor.device)
        predictor.model.eval()
        # 210 rows pass the initial check (>= lookback+20=200) but inject NaNs
        # so that after dropna, fewer than lookback (180) rows remain
        df = self._make_df(210)
        # Set most volume to 0 so log(volume+1).pct_change() produces NaN/inf
        df.loc[:100, "volume"] = 0.0
        df.loc[:100, "close"] = np.nan
        pct, conf = predictor.predict(df)
        assert pct == 0.0
        assert conf == 0.0

"""Tests para AI_Predictor - tensor shapes y lógica de predicción."""
import torch
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from modules.ai_predictor import CryptoTransformer, PositionalEncoding, AI_Predictor


class TestCryptoTransformer:
    def test_forward_shape(self):
        """El modelo debe aceptar (batch, seq, 8) y devolver (batch, 1)."""
        model = CryptoTransformer()
        x = torch.randn(2, 180, 8)
        out = model(x)
        assert out.shape == (2, 1)

    def test_single_sample(self):
        model = CryptoTransformer()
        x = torch.randn(1, 180, 8)
        out = model(x)
        assert out.shape == (1, 1)

    def test_different_seq_lengths(self):
        model = CryptoTransformer()
        for seq_len in [50, 100, 180, 300]:
            x = torch.randn(1, seq_len, 8)
            out = model(x)
            assert out.shape == (1, 1)


class TestPositionalEncoding:
    def test_output_shape(self):
        pe = PositionalEncoding(128)
        x = torch.randn(1, 180, 128)
        out = pe(x)
        assert out.shape == x.shape

    def test_adds_positional_info(self):
        pe = PositionalEncoding(128)
        x = torch.zeros(1, 10, 128)
        out = pe(x)
        assert not torch.all(out == 0)


class TestAIPredictorPredict:
    def _make_df(self, n=300):
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 0.1)
        close = np.maximum(close, 1.0)
        return pd.DataFrame({
            'open': close + np.random.randn(n) * 0.01,
            'high': close + abs(np.random.randn(n) * 0.05),
            'low': close - abs(np.random.randn(n) * 0.05),
            'close': close,
            'volume': np.random.randint(100, 10000, n).astype(float),
            'funding_rate': np.random.uniform(-0.001, 0.001, n),
        })

    def test_predict_returns_tuple(self):
        predictor = AI_Predictor({})
        df = self._make_df(300)
        result = predictor.predict(df)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_predict_insufficient_data(self):
        predictor = AI_Predictor({})
        df = self._make_df(50)
        pct, conf = predictor.predict(df)
        assert pct == 0.0
        assert conf == 0.0

    def test_predict_with_model_loaded(self):
        """Test predict path when model is available."""
        predictor = AI_Predictor({})
        predictor.model = CryptoTransformer().to(predictor.device)
        predictor.model.eval()
        df = self._make_df(300)
        pct, conf = predictor.predict(df)
        assert isinstance(pct, float)
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 0.95

    def test_predict_error_returns_zero(self):
        """Test that predict returns (0.0, 0.0) on internal error."""
        predictor = AI_Predictor({})
        predictor.model = MagicMock()
        predictor.model.side_effect = RuntimeError("test error")
        df = self._make_df(300)
        pct, conf = predictor.predict(df)
        assert pct == 0.0
        assert conf == 0.0


class TestAIPredictorGetSignal:
    def test_get_signal_neutral_no_model(self):
        predictor = AI_Predictor({})
        df = pd.DataFrame({'close': [100.0] * 300})
        signal = predictor.get_signal(df)
        assert signal == 'NEUTRAL'

    def test_get_signal_buy(self):
        predictor = AI_Predictor({})
        with patch.object(predictor, 'predict', return_value=(0.05, 0.8)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == 'BUY'

    def test_get_signal_sell(self):
        predictor = AI_Predictor({})
        with patch.object(predictor, 'predict', return_value=(-0.05, 0.8)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == 'SELL'

    def test_get_signal_neutral_low_confidence(self):
        predictor = AI_Predictor({})
        with patch.object(predictor, 'predict', return_value=(0.05, 0.3)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == 'NEUTRAL'

    def test_get_signal_neutral_small_pct(self):
        predictor = AI_Predictor({})
        with patch.object(predictor, 'predict', return_value=(0.01, 0.9)):
            signal = predictor.get_signal(pd.DataFrame())
            assert signal == 'NEUTRAL'

    def test_get_signal_custom_threshold(self):
        predictor = AI_Predictor({})
        with patch.object(predictor, 'predict', return_value=(0.05, 0.5)):
            signal = predictor.get_signal(pd.DataFrame(), threshold=0.4)
            assert signal == 'BUY'


class TestAIPredictorLoadModel:
    def test_load_model_no_file(self):
        """Model stays None when file doesn't exist."""
        predictor = AI_Predictor({})
        assert predictor.model is None

    def test_load_model_bad_file(self, tmp_path):
        """Model is instantiated even if state_dict load fails (logs error)."""
        bad_model = tmp_path / "bad_model.pth"
        bad_model.write_text("not a model")
        predictor = AI_Predictor({})
        predictor.model_path = str(bad_model)
        predictor._load_model()
        # Model object is created before load_state_dict, so it persists
        assert predictor.model is not None

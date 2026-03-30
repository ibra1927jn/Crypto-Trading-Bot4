"""Tests para AI_Predictor - tensor shapes y lógica de predicción."""
import torch
import numpy as np
import pandas as pd

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

class TestAIPredictorGetSignal:
    pass

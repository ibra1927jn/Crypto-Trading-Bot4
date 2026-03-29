"""Tests para AI_Predictor - tensor shapes y lógica de predicción."""
import pytest
import torch
import numpy as np
import pandas as pd
import sys, os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
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
        signal, conf = predictor.predict(df)
        assert signal == 'NEUTRAL'
        assert conf == 0.0

    def test_predict_no_model(self):
        predictor = AI_Predictor({})
        predictor.model = None
        df = self._make_df(300)
        signal, conf = predictor.predict(df)
        assert signal == 'NEUTRAL'

    def test_tensor_shape_in_predict(self):
        """Verifica que el tensor enviado al modelo tiene forma correcta (batch, seq, features)."""
        predictor = AI_Predictor({})
        # Crear modelo dummy que registre la forma del input
        shapes_seen = []
        original_forward = CryptoTransformer.forward

        def tracking_forward(self, x):
            shapes_seen.append(x.shape)
            return original_forward(self, x)

        CryptoTransformer.forward = tracking_forward
        try:
            # Crear modelo dummy (sin pesos guardados)
            predictor.model = CryptoTransformer()
            predictor.model.eval()
            df = self._make_df(300)
            predictor.predict(df)
            assert len(shapes_seen) > 0, "El modelo no fue llamado"
            shape = shapes_seen[0]
            assert len(shape) == 3, f"Tensor debe ser 3D (batch, seq, feat), got {len(shape)}D: {shape}"
            assert shape[0] == 1, f"Batch size debe ser 1, got {shape[0]}"
            assert shape[2] == 8, f"Features debe ser 8, got {shape[2]}"
        finally:
            CryptoTransformer.forward = original_forward


class TestAIPredictorGetSignal:
    def test_get_signal_returns_string(self):
        predictor = AI_Predictor({})
        df = pd.DataFrame({'close': [100]*300, 'high': [101]*300,
                          'low': [99]*300, 'open': [100]*300,
                          'volume': [1000]*300, 'funding_rate': [0.0]*300})
        result = predictor.get_signal(df)
        assert result in ('BUY', 'SELL', 'NEUTRAL')

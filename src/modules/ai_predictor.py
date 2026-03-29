import torch
import torch.nn as nn
import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.preprocessing import RobustScaler
import logging
import os
import math

logger = logging.getLogger(__name__)

# ARQUITECTURA
D_MODEL = 128
NHEAD = 4
NUM_LAYERS = 4
DROPOUT = 0.0

class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=5000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))
    def forward(self, x): return x + self.pe[:, :x.size(1)]

class CryptoTransformer(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Linear(8, D_MODEL)
        self.pos_encoder = PositionalEncoding(D_MODEL)
        encoder_layer = nn.TransformerEncoderLayer(d_model=D_MODEL, nhead=NHEAD, dropout=DROPOUT, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=NUM_LAYERS)
        self.decoder = nn.Linear(D_MODEL, 1)
    def forward(self, x):
        x = self.embedding(x)
        x = self.pos_encoder(x)
        x = self.transformer(x)
        x = x.mean(dim=1)
        return self.decoder(x)

class AI_Predictor:
    def __init__(self, config):
        self.model_path = 'models/trading_model.pth'
        self.lookback = 180
        self.scaler = RobustScaler()
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._load_model()

    def _load_model(self):
        if not os.path.exists(self.model_path): return
        try:
            self.model = CryptoTransformer().to(self.device)
            self.model.load_state_dict(torch.load(self.model_path, map_location=self.device))
            self.model.eval()
            logger.info("✅ CEREBRO TRANSFORMER CONECTADO")
        except Exception as e: logger.error(f"❌ Error: {e}")

    def predict(self, df):
        """Returns (pct_prediction, confidence) as floats."""
        if self.model is None or len(df) < self.lookback + 20: return 0.0, 0.0
        try:
            data = df.copy()
            # Ingeniería
            data['return'] = np.log(data['close'] / data['close'].shift(1))
            data['log_vol'] = np.log(data['volume'] + 1).pct_change()
            data['rsi'] = ta.rsi(data['close'], length=14) / 100.0
            data['atr_rel'] = ta.atr(data['high'], data['low'], data['close'], length=14) / data['close'].clip(lower=1e-8)
            macd = ta.macd(data['close'])
            data['macd'] = macd['MACD_12_26_9']
            data['macd_sig'] = macd['MACDs_12_26_9']
            ema = ta.ema(data['close'], length=50)
            data['dist_ema'] = (data['close'] - ema) / ema.clip(lower=1e-8)
            data['funding'] = data.get('funding_rate', 0.0)

            data.replace([np.inf, -np.inf], np.nan, inplace=True)
            data.dropna(inplace=True)
            if len(data) < self.lookback: return 0.0, 0.0

            feats = data[['return', 'log_vol', 'rsi', 'macd', 'macd_sig', 'atr_rel', 'dist_ema', 'funding']].values
            self.scaler.fit(feats)
            scaled = self.scaler.transform(feats[-self.lookback:])

            tensor = torch.tensor(scaled, dtype=torch.float32).unsqueeze(0).to(self.device)
            with torch.no_grad(): pred = self.model(tensor).item()

            pct = (np.exp(pred) - 1) * 100
            icon = "↗️" if pct > 0 else "↘️"
            logger.info(f"🔮 IA: {icon} {pct:.4f}%")

            confidence = min(abs(pct) / 1.0, 0.95)
            return pct, confidence
        except Exception as e:
            logger.error(f"❌ Error en predict: {e}")
            return 0.0, 0.0

    def get_signal(self, df, threshold=0.65):
        pct, confidence = self.predict(df)
        if pct > 0.02 and confidence >= threshold: return 'BUY'
        elif pct < -0.02 and confidence >= threshold: return 'SELL'
        return 'NEUTRAL'
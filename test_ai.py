import math
import random
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pandas_ta as ta
import torch
from sklearn.preprocessing import RobustScaler
from torch import nn

# Configuración idéntica
DATA_FOLDER = "data"
MODEL_PATH = "models/trading_model.pth"
TEST_BARS = 400
LOOKBACK = 180
D_MODEL = 128
NHEAD = 4
NUM_LAYERS = 4
DROPOUT = 0.0
# Umbral de predicción (± return) para abrir una posición simulada
SIGNAL_THRESHOLD = 0.00005
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# Arquitectura
class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 5000) -> None:
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float()
            * (-math.log(10000.0) / d_model),
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, :x.size(1)]


class CryptoTransformer(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.embedding = nn.Linear(8, D_MODEL)
        self.pos_encoder = PositionalEncoding(D_MODEL)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=D_MODEL, nhead=NHEAD,
            dropout=DROPOUT, batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer, num_layers=NUM_LAYERS,
        )
        self.decoder = nn.Linear(D_MODEL, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.embedding(x)
        x = self.pos_encoder(x)
        x = self.transformer(x)
        x = x.mean(dim=1)
        return self.decoder(x)


if __name__ == "__main__":
    # Carga
    csv_file = Path(DATA_FOLDER) / "BTC_USDT_1m_HD.csv"
    if not csv_file.exists():
        sys.exit("❌ Faltan datos BTC")
    df = pd.read_csv(csv_file)

    # Ingeniería
    df["return"] = np.log(df["close"] / df["close"].shift(1))
    df["vol_change"] = np.log(df["volume"] + 1).pct_change()
    df["rsi"] = ta.rsi(df["close"], length=14) / 100.0
    df["atr_rel"] = (
        ta.atr(df["high"], df["low"], df["close"], length=14)
        / df["close"]
    )
    macd = ta.macd(df["close"])
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_sig"] = macd["MACDs_12_26_9"]
    ema = ta.ema(df["close"], length=50)
    df["dist_ema"] = (df["close"] - ema) / ema
    df["funding"] = df.get("funding_rate", 0.0)
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna()

    feat_cols = [
        "return", "vol_change", "rsi", "macd",
        "macd_sig", "atr_rel", "dist_ema", "funding",
    ]
    features = df[feat_cols].to_numpy()
    scaler = RobustScaler()
    scaled = scaler.fit_transform(features)

    model = CryptoTransformer().to(device)
    try:
        model.load_state_dict(torch.load(
            MODEL_PATH, map_location=device, weights_only=True,
        ))
        model.eval()
    except Exception as e:
        sys.exit(f"❌ Error: Modelo no compatible: {e}")

    # Test
    start_idx = random.randint(0, len(scaled) - TEST_BARS - LOOKBACK)
    test_data = scaled[start_idx:start_idx + TEST_BARS + LOOKBACK]
    end_idx = start_idx + TEST_BARS + LOOKBACK
    real_ret = df["return"].to_numpy()[start_idx + LOOKBACK:end_idx]

    hits = 0
    total = 0
    simulated = [100]

    for i in range(TEST_BARS):
        seq = test_data[i:i + LOOKBACK]
        x = torch.tensor(seq, dtype=torch.float32).unsqueeze(0).to(device)
        with torch.no_grad():
            pred = model(x).item()
        actual = real_ret[i]
        if pred > SIGNAL_THRESHOLD:  # Long
            total += 1
            if actual > 0:
                hits += 1
            simulated.append(simulated[-1] * (1 + actual))
        elif pred < -SIGNAL_THRESHOLD:  # Short
            total += 1
            if actual < 0:
                hits += 1
            simulated.append(simulated[-1] * (1 - actual))
        else:
            simulated.append(simulated[-1])

    acc = (hits / total * 100) if total > 0 else 0
    print(f"📊 ACIERTO: {acc:.2f}%")
    plt.plot(simulated)
    plt.savefig("resultado_examen.png")
    print("📸 Gráfico guardado.")

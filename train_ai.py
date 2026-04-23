import logging
import math
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta
import torch
import wandb
from sklearn.preprocessing import RobustScaler
from torch import nn
from torch.utils.data import DataLoader, Dataset

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

logger = logging.getLogger(__name__)

# ==========================================
# ⚡ CONFIGURACIÓN BASE (SWEEP PUEDE OVERRIDE)
# ==========================================
DATA_FOLDER = 'data'
MODEL_PATH = 'models/trading_model_sweep.pth'

# Valores por defecto (el sweep los reemplazará)
DEFAULT_CONFIG = {
    'epochs': 80,              # Reducido para sweeps rápidos
    'batch_size': 1024,
    'learning_rate': 5e-4,
    'lookback': 180,
    'd_model': 128,
    'nhead': 4,
    'num_layers': 4,
    'dropout': 0.3,
    'gradient_clip': 1.0,
    'weight_decay': 1e-4,
    'optimizer': 'AdamW',
    'scheduler': 'OneCycleLR',
    'architecture': 'Transformer',
    'data_split': 0.8,
    'early_stop_patience': 12  # Más agresivo para sweeps
}

NUM_WORKERS = 0
PIN_MEMORY = True


class LazyCryptoDataset(Dataset):
    def __init__(self, features, targets, lookback):
        self.features = features
        self.targets = targets
        self.lookback = lookback

    def __len__(self):
        return len(self.features) - self.lookback

    def __getitem__(self, idx):
        x = self.features[idx:idx + self.lookback]
        y = self.targets[idx + self.lookback]
        x_t = torch.tensor(x, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.float32)
        return x_t, y_t


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=5000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float()
            * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))

    def forward(self, x):
        return x + self.pe[:, :x.size(1)]


class CryptoTransformer(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.embedding = nn.Linear(8, config['d_model'])
        self.pos_encoder = PositionalEncoding(config['d_model'])
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config['d_model'],
            nhead=config['nhead'],
            dropout=config['dropout'],
            batch_first=True,
            norm_first=True
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer, num_layers=config['num_layers']
        )
        self.decoder = nn.Linear(config['d_model'], 1)
        self._init_weights()

    def _init_weights(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.LayerNorm):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)

    def forward(self, x):
        x = self.embedding(x)
        x = self.pos_encoder(x)
        x = self.transformer(x)
        x = x.mean(dim=1)
        out = self.decoder(x)
        return out.squeeze(1)


class EarlyStopping:
    def __init__(self, patience=12, min_delta=1e-6):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_loss = None
        self.should_stop = False

    def __call__(self, val_loss):
        if self.best_loss is None:
            self.best_loss = val_loss
        elif val_loss > self.best_loss - self.min_delta:
            self.counter += 1
            if self.counter >= self.patience:
                self.should_stop = True
        else:
            self.best_loss = val_loss
            self.counter = 0
        return self.should_stop


def load_and_prepare_data(data_folder, config):
    """Carga datos (versión silenciosa para sweeps)"""
    csv_files = [str(p) for p in Path(data_folder).glob("*_HD.csv")]

    all_features, all_targets = [], []

    for file in csv_files:
        try:
            df = pd.read_csv(file)
            df['return'] = np.log(df['close'] / df['close'].shift(1))
            df['vol_change'] = np.log(df['volume'] + 1).pct_change()
            df['rsi'] = ta.rsi(df['close'], length=14) / 100.0
            macd = ta.macd(df['close'])
            df['macd'] = macd['MACD_12_26_9']
            df['macd_sig'] = macd['MACDs_12_26_9']
            atr = ta.atr(df['high'], df['low'], df['close'], length=14)
            df['atr_rel'] = atr / df['close']
            ema = ta.ema(df['close'], length=50)
            df['dist_ema'] = (df['close'] - ema) / ema
            df['funding'] = df.get('funding_rate', 0.0)

            df = df.replace([np.inf, -np.inf], np.nan)
            df = df.dropna()

            feat_cols = [
                'return', 'vol_change', 'rsi', 'macd',
                'macd_sig', 'atr_rel', 'dist_ema', 'funding',
            ]
            feats = df[feat_cols].to_numpy(dtype=np.float32)
            targs = df['return'].to_numpy(dtype=np.float32)
            all_features.append(feats)
            all_targets.append(targs)
        except Exception as e:
            logger.warning("Skipping %s: %s", file, e)

    X_raw = np.concatenate(all_features)
    y_raw = np.concatenate(all_targets)

    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X_raw)

    split = int(len(X_scaled) * config['data_split'])

    lookback = config['lookback']
    train_dataset = LazyCryptoDataset(
        X_scaled[:split], y_raw[:split], lookback
    )
    val_dataset = LazyCryptoDataset(
        X_scaled[split:], y_raw[split:], lookback
    )

    return train_dataset, val_dataset, scaler


def train_epoch(
    model, train_loader, criterion, optimizer,
    scaler_amp, scheduler, device, config,
):
    """Entrena una época"""
    model.train()
    total_loss = 0

    for bx, by in train_loader:
        bx = bx.to(device, non_blocking=True)
        by = by.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)

        with torch.amp.autocast('cuda'):
            out = model(bx)
            loss = criterion(out, by)

        scaler_amp.scale(loss).backward()
        scaler_amp.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(
            model.parameters(), config['gradient_clip'],
        )

        scaler_amp.step(optimizer)
        scaler_amp.update()
        scheduler.step()

        total_loss += loss.item()

    return total_loss / len(train_loader)


def validate(model, val_loader, criterion, device):
    """Validación"""
    model.eval()
    total_loss = 0
    predictions = []
    targets = []

    with torch.no_grad():
        for bx, by in val_loader:
            bx = bx.to(device, non_blocking=True)
            by = by.to(device, non_blocking=True)
            with torch.amp.autocast('cuda'):
                val_out = model(bx)
                loss = criterion(val_out, by)
            total_loss += loss.item()
            predictions.extend(val_out.cpu().numpy())
            targets.extend(by.cpu().numpy())

    predictions = np.array(predictions)
    targets = np.array(targets)
    mae = np.mean(np.abs(predictions - targets))
    correlation = (
        np.corrcoef(predictions, targets)[0, 1]
        if len(predictions) > 1 else 0
    )

    return total_loss / len(val_loader), mae, correlation


def train():
    """Función principal de entrenamiento (compatible con sweeps)"""

    # Configuración hardware
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 🎯 WANDB INIT (sweep inyecta config automáticamente)
    wandb.init(config=DEFAULT_CONFIG)
    config = wandb.config

    # Cargar datos
    train_dataset, val_dataset, _scaler = load_and_prepare_data(
        DATA_FOLDER, config,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=NUM_WORKERS,
        pin_memory=PIN_MEMORY,
        persistent_workers=False
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=config.batch_size * 2,
        shuffle=False,
        num_workers=NUM_WORKERS,
        pin_memory=PIN_MEMORY,
        persistent_workers=False
    )

    # Modelo
    model = CryptoTransformer(config).to(device)
    criterion = nn.MSELoss()
    scaler_amp = torch.amp.GradScaler('cuda')

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
        betas=(0.9, 0.999)
    )

    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=config.learning_rate,
        epochs=config.epochs,
        steps_per_epoch=len(train_loader),
        pct_start=0.3,
        anneal_strategy='cos',
        div_factor=25.0,
        final_div_factor=1e4
    )

    early_stop = EarlyStopping(patience=config.early_stop_patience)
    best_val_loss = float('inf')

    # Training loop
    for epoch in range(config.epochs):
        avg_train_loss = train_epoch(
            model, train_loader, criterion, optimizer,
            scaler_amp, scheduler, device, config
        )

        avg_val_loss, val_mae, val_corr = validate(
            model, val_loader, criterion, device,
        )

        # Log a WandB (lo que el sweep optimiza)
        wandb.log({
            "epoch": epoch + 1,
            "train/loss": avg_train_loss,
            "val/loss": avg_val_loss,
            "val/mae": val_mae,
            "val/correlation": val_corr,
            "train/learning_rate": optimizer.param_groups[0]['lr']
        })

        # Guardar mejor modelo (no guardamos en sweep: demasiados modelos)
        best_val_loss = min(best_val_loss, avg_val_loss)

        # Early stopping
        if early_stop(avg_val_loss):
            wandb.log({"early_stopped": True, "stopped_epoch": epoch + 1})
            break

    # Métricas finales
    wandb.log({
        "final/best_val_loss": best_val_loss,
        "final/total_epochs": epoch + 1
    })


if __name__ == '__main__':
    train()

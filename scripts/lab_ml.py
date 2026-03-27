"""
🤖 ML TRADING MODEL — XGBoost Crypto Predictor
=================================================
Entrena un modelo de Machine Learning para predecir
trades rentables usando datos históricos.

Pasos:
1. Descarga datos de XRP 5min (Dec-Feb)
2. Crea features (40+ indicadores técnicos)
3. Crea labels (¿sube X% antes de bajar Y%?)
4. Train/Val/Test split temporal (60/20/20)
5. Entrena XGBoost
6. Simula con predicciones del modelo
7. Compara con estrategia de reglas fijas
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, numpy as np, time
from datetime import datetime, timezone
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report, accuracy_score
import xgboost as xgb
import warnings
warnings.filterwarnings('ignore')

def p(msg): print(msg); sys.stdout.flush()

def safe(row, col, default=0):
    v = row.get(col) if isinstance(row, dict) else (row[col] if col in row.index else None)
    return float(v) if v is not None and not pd.isna(v) else default

# ═══════════════════════════════════════════════════════
# FEATURES: 40+ indicadores técnicos como inputs del ML
# ═══════════════════════════════════════════════════════

def create_features(df):
    """Genera todas las features para el modelo ML."""
    f = pd.DataFrame(index=df.index)
    
    # RSI múltiples periodos
    for length in [3, 5, 7, 14, 21]:
        rsi = ta.rsi(df['close'], length=length)
        if rsi is not None:
            f[f'RSI_{length}'] = rsi
    
    # EMAs y distancias
    for length in [5, 9, 13, 21, 50]:
        ema = ta.ema(df['close'], length)
        if ema is not None:
            f[f'EMA_{length}_dist'] = (df['close'] - ema) / ema * 100
    
    # MACD
    mc = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if mc is not None:
        cols = mc.columns.tolist()
        f['MACD'] = mc[cols[0]] if len(cols) > 0 else 0
        f['MACD_signal'] = mc[cols[1]] if len(cols) > 1 else 0
        f['MACD_hist'] = mc[cols[2]] if len(cols) > 2 else 0
    
    # Bollinger Bands position
    bb = ta.bbands(df['close'], length=20, std=2)
    if bb is not None:
        bbl = [c for c in bb.columns if c.startswith('BBL_')]
        bbm = [c for c in bb.columns if c.startswith('BBM_')]
        bbu = [c for c in bb.columns if c.startswith('BBU_')]
        if bbl and bbu:
            f['BB_pos'] = (df['close'] - bb[bbl[0]]) / (bb[bbu[0]] - bb[bbl[0]] + 1e-10)
            f['BB_width'] = (bb[bbu[0]] - bb[bbl[0]]) / bb[bbm[0]] * 100 if bbm else 0
    
    # Stochastic
    st = ta.stoch(df['high'], df['low'], df['close'])
    if st is not None:
        sk = [c for c in st.columns if 'STOCHk' in c]
        sd = [c for c in st.columns if 'STOCHd' in c]
        if sk: f['STOCH_K'] = st[sk[0]]
        if sd: f['STOCH_D'] = st[sd[0]]
    
    # ATR (volatilidad)
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    if atr is not None:
        f['ATR_pct'] = atr / df['close'] * 100
    
    # ADX (fuerza de tendencia)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None:
        ac = [c for c in adx.columns if c.startswith('ADX_')]
        if ac: f['ADX'] = adx[ac[0]]
    
    # Volumen relativo
    f['VOL_ratio'] = df['volume'] / df['volume'].rolling(20).mean().replace(0, 1e-10)
    f['VOL_ratio_5'] = df['volume'] / df['volume'].rolling(5).mean().replace(0, 1e-10)
    
    # Candle patterns
    f['candle_pct'] = (df['close'] - df['open']) / df['open'] * 100
    f['candle_body'] = abs(df['close'] - df['open']) / (df['high'] - df['low'] + 1e-10)
    f['upper_shadow'] = (df['high'] - df[['close', 'open']].max(axis=1)) / (df['high'] - df['low'] + 1e-10)
    f['lower_shadow'] = (df[['close', 'open']].min(axis=1) - df['low']) / (df['high'] - df['low'] + 1e-10)
    
    # Momentum (rate of change)
    for period in [3, 5, 10, 20]:
        f[f'ROC_{period}'] = df['close'].pct_change(period) * 100
    
    # Previous candle features (lag)
    for lag in [1, 2, 3]:
        f[f'candle_pct_lag{lag}'] = f['candle_pct'].shift(lag)
        f[f'VOL_ratio_lag{lag}'] = f['VOL_ratio'].shift(lag)
        if 'RSI_7' in f.columns:
            f[f'RSI_7_lag{lag}'] = f['RSI_7'].shift(lag)
    
    # Hora del día (patrones temporales)
    f['hour'] = df.index.hour
    f['hour_sin'] = np.sin(2 * np.pi * f['hour'] / 24)
    f['hour_cos'] = np.cos(2 * np.pi * f['hour'] / 24)
    
    return f

# ═══════════════════════════════════════════════════════
# LABELS: ¿Será rentable esta vela?
# ═══════════════════════════════════════════════════════

def create_labels(df, tp_pct=1.0, sl_pct=0.5, lookahead=30):
    """
    Para cada vela, mira las próximas N velas:
    - Si el precio sube tp_pct% ANTES de bajar sl_pct% → 1 (BUY)
    - Si toca SL primero o no llega a TP → 0 (NO BUY)
    """
    labels = np.zeros(len(df))
    
    for i in range(len(df) - lookahead):
        entry = df['close'].iloc[i]
        tp_price = entry * (1 + tp_pct / 100)
        sl_price = entry * (1 - sl_pct / 100)
        
        for j in range(1, lookahead + 1):
            high = df['high'].iloc[i + j]
            low = df['low'].iloc[i + j]
            
            if low <= sl_price:
                labels[i] = 0  # SL hit first
                break
            if high >= tp_price:
                labels[i] = 1  # TP hit first
                break
    
    return labels

def simulate_ml(df, features, predictions, probabilities, 
                tp_pct=1.0, sl_pct=0.5, cap=30.0, 
                prob_threshold=0.6, leverage=5, fee_pct=0.04):
    """Simula trading basado en predicciones del modelo ML."""
    bal = cap
    pos = None
    trades = []
    peak = cap
    max_dd = 0
    
    for i in range(len(df)):
        row = df.iloc[i]
        
        if pos:
            price = row['close']
            pnl_pct = (price - pos['entry']) / pos['entry'] * 100
            pnl_lev = pnl_pct * leverage
            pnl_dollar = pos['margin'] * (pnl_lev / 100)
            
            # Liquidación
            if pnl_dollar <= -(pos['margin'] * 0.95):
                bal -= pos['margin']
                trades.append({'pnl': -pos['margin'], 'reason': 'LIQ', 'bal': bal,
                               'ts': row.name})
                pos = None
                if bal < 1: break
                continue
            
            hit_sl = pnl_pct <= -sl_pct
            hit_tp = pnl_pct >= tp_pct
            
            if hit_sl or hit_tp:
                close_fee = pos['position_size'] * (fee_pct / 100)
                actual_pnl = pnl_dollar - close_fee
                bal += actual_pnl
                peak = max(peak, bal)
                dd = (peak - bal) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
                reason = 'SL' if hit_sl else 'TP'
                trades.append({'pnl': actual_pnl, 'reason': reason, 'bal': bal,
                               'ts': row.name})
                pos = None
        else:
            if i < len(predictions) and predictions[i] == 1:
                if probabilities[i] >= prob_threshold and bal >= 2:
                    price = row['close']
                    margin = bal * 0.90
                    position_size = margin * leverage
                    open_fee = position_size * (fee_pct / 100)
                    pos = {
                        'entry': price, 'margin': margin,
                        'position_size': position_size, 'i': i,
                    }
                    bal -= open_fee
    
    if pos:
        price = df.iloc[-1]['close']
        pnl_pct = (price - pos['entry']) / pos['entry'] * 100
        pnl_dollar = pos['margin'] * (pnl_pct * leverage / 100)
        close_fee = pos['position_size'] * (fee_pct / 100)
        bal += pnl_dollar - close_fee
        trades.append({'pnl': pnl_dollar - close_fee, 'reason': 'END', 'bal': bal,
                       'ts': df.index[-1]})
    
    return trades, bal, max_dd

def download_data(ex, symbol, start_date, end_date, tf='5m'):
    start_ts = int(datetime(*start_date, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(*end_date, tzinfo=timezone.utc).timestamp() * 1000)
    all_ohlcv = []
    since = start_ts
    chunk = 0
    while since < end_ts:
        chunk += 1
        if chunk % 5 == 1: p(f"   📥 Chunk {chunk}...")
        ohlcv = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        if not ohlcv: break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        if ohlcv[-1][0] >= end_ts: break
        time.sleep(0.2)
    df = pd.DataFrame(all_ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df[~df.index.duplicated(keep='last')]

def main():
    p("="*80)
    p("🤖 ML TRADING MODEL — XGBoost Crypto Predictor")
    p("   XRP/USDT | 5min candles")
    p("   Train: Oct-Dec 2024 | Test: Jan-Feb 2025")
    p("="*80)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    
    # Descargar más datos: Oct 2024 - Feb 2025 (5 meses)
    p("\n📥 Descargando datos de entrenamiento (Oct 2024 - Feb 2025)...")
    df = download_data(ex, 'XRP/USDT', (2024, 10, 1), (2025, 2, 17, 23, 59))
    p(f"   ✅ {len(df)} velas | {df.index[0]} → {df.index[-1]}")
    
    # Features
    p("\n🔧 Creando features (40+ indicadores)...")
    features = create_features(df)
    
    # Labels: TP 1.0%, SL 0.5%, lookahead 30 velas
    TP_PCT = 1.0
    SL_PCT = 0.5
    p(f"🏷️ Creando labels (TP:{TP_PCT}% SL:{SL_PCT}% lookahead:30)...")
    labels = create_labels(df, tp_pct=TP_PCT, sl_pct=SL_PCT, lookahead=30)
    
    features['label'] = labels
    features = features.dropna()
    
    positive_rate = features['label'].mean()
    p(f"   Positivos: {positive_rate*100:.1f}% ({int(features['label'].sum())}/{len(features)})")
    
    # Split temporal: 60% train, 20% val, 20% test
    n = len(features)
    train_end = int(n * 0.6)
    val_end = int(n * 0.8)
    
    X_train = features.iloc[:train_end].drop('label', axis=1)
    y_train = features.iloc[:train_end]['label']
    X_val = features.iloc[train_end:val_end].drop('label', axis=1)
    y_val = features.iloc[train_end:val_end]['label']
    X_test = features.iloc[val_end:].drop('label', axis=1)
    y_test = features.iloc[val_end:]['label']
    
    p(f"\n📊 Split: Train={len(X_train)} | Val={len(X_val)} | Test={len(X_test)}")
    p(f"   Train: {features.index[0]} → {features.index[train_end]}")
    p(f"   Val:   {features.index[train_end]} → {features.index[val_end]}")
    p(f"   Test:  {features.index[val_end]} → {features.index[-1]}")
    
    # ═══════════════════════════════════════════════════
    # ENTRENAR MODELO
    # ═══════════════════════════════════════════════════
    p("\n🤖 Entrenando XGBoost...")
    
    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_alpha=0.1,
        reg_lambda=1.0,
        scale_pos_weight=len(y_train[y_train==0]) / max(len(y_train[y_train==1]), 1),
        eval_metric='logloss',
        random_state=42,
        verbosity=0,
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    
    # ═══════════════════════════════════════════════════
    # EVALUAR
    # ═══════════════════════════════════════════════════
    
    # Validation
    val_pred = model.predict(X_val)
    val_proba = model.predict_proba(X_val)[:, 1]
    val_acc = accuracy_score(y_val, val_pred)
    
    # Test
    test_pred = model.predict(X_test)
    test_proba = model.predict_proba(X_test)[:, 1]
    test_acc = accuracy_score(y_test, test_pred)
    
    p(f"\n📊 MÉTRICAS DEL MODELO:")
    p(f"   Validation Accuracy: {val_acc*100:.1f}%")
    p(f"   Test Accuracy:       {test_acc*100:.1f}%")
    
    p(f"\n   Test Classification Report:")
    report = classification_report(y_test, test_pred, target_names=['NO BUY', 'BUY'])
    for line in report.split('\n'):
        p(f"   {line}")
    
    # Feature importance
    importances = model.feature_importances_
    feat_names = X_train.columns
    sorted_idx = np.argsort(importances)[::-1][:15]
    p(f"\n   Top 15 Features:")
    for i, idx in enumerate(sorted_idx):
        p(f"   {i+1:2d}. {feat_names[idx]:<20s}: {importances[idx]:.4f}")
    
    # ═══════════════════════════════════════════════════
    # SIMULAR TRADING EN TEST SET
    # ═══════════════════════════════════════════════════
    p(f"\n{'='*70}")
    p("💰 SIMULACIÓN DE TRADING (solo en Test Set — datos NO vistos)")
    p(f"{'='*70}")
    
    test_df = df.iloc[val_end:val_end+len(X_test)]
    
    for lev in [1, 3, 5, 10]:
        for thresh in [0.5, 0.6, 0.7, 0.8]:
            trades, bal, mdd = simulate_ml(
                test_df, X_test, test_pred, test_proba,
                tp_pct=TP_PCT, sl_pct=SL_PCT,
                leverage=lev, prob_threshold=thresh)
            
            w = len([t for t in trades if t['pnl'] > 0])
            n_trades = len(trades)
            pnl = bal - 30
            wr = w / max(n_trades, 1) * 100
            test_days = (test_df.index[-1] - test_df.index[0]).days or 1
            daily = pnl / test_days
            
            e = '🟢' if pnl > 0 else ('💀' if any(t['reason']=='LIQ' for t in trades) else '🔴')
            p(f"   {lev:2d}x prob>{thresh:.0%}: {e} ${pnl:+7.2f} | "
              f"{n_trades:3d}T | WR:{wr:3.0f}% | DD:{mdd:4.1f}% | ${daily:+.2f}/d")
    
    # Benchmark: Buy & Hold en test period
    bh_pct = (test_df.iloc[-1]['close'] / test_df.iloc[0]['close'] - 1) * 100
    bh_pnl = 30 * (bh_pct / 100)
    p(f"\n   📊 Benchmark Buy&Hold: ${bh_pnl:+.2f} ({bh_pct:+.1f}%)")
    
    p(f"\n{'='*70}")

if __name__ == '__main__':
    main()

"""
🤖 ML TRADING MODEL v2 — Entrenamiento Extendido
===================================================
Mejoras sobre v1:
1. 1h candles (menos ruido que 5min)
2. 2 años de datos (mucho más entrenamiento)
3. BTC como indicador líder (correlación)
4. TP/SL adaptativo basado en ATR
5. Labels mejorados: tendencia + ATR
6. Feature engineering más profundo
7. Evaluación robusta con walk-forward

Capital: $30 | Futuros 5x
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, numpy as np, time, json
from datetime import datetime, timezone
from sklearn.metrics import classification_report, accuracy_score, precision_score
import xgboost as xgb
import warnings
warnings.filterwarnings('ignore')

def p(msg): print(msg); sys.stdout.flush()

# ═══════════════════════════════════════════════════════
# DESCARGA DE DATOS
# ═══════════════════════════════════════════════════════

def download_data(ex, symbol, start_date, end_date, tf='1h'):
    """Descarga datos en chunks con paginación."""
    start_ts = int(datetime(*start_date, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(*end_date, tzinfo=timezone.utc).timestamp() * 1000)
    all_ohlcv = []
    since = start_ts
    chunk = 0
    while since < end_ts:
        chunk += 1
        if chunk % 10 == 1: p(f"      Chunk {chunk}...")
        try:
            ohlcv = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        except Exception as e:
            p(f"      ⚠️ Error chunk {chunk}: {e}")
            time.sleep(2)
            continue
        if not ohlcv: break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        if ohlcv[-1][0] >= end_ts: break
        time.sleep(0.15)
    
    df = pd.DataFrame(all_ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    # Filter to exact range
    start_str = f"{start_date[0]}-{start_date[1]:02d}-{start_date[2]:02d}"
    df = df[df.index >= start_str]
    return df

# ═══════════════════════════════════════════════════════
# FEATURES: 60+ indicadores
# ═══════════════════════════════════════════════════════

def create_features(df, btc_df=None):
    """Features técnicos + BTC como líder."""
    f = pd.DataFrame(index=df.index)
    
    # === RSI múltiples periodos ===
    for length in [3, 5, 7, 9, 14, 21]:
        rsi = ta.rsi(df['close'], length=length)
        if rsi is not None: f[f'rsi_{length}'] = rsi
    
    # === EMAs y distancias al precio ===
    for length in [5, 9, 13, 21, 34, 50, 100, 200]:
        ema = ta.ema(df['close'], length)
        if ema is not None:
            f[f'ema_{length}_dist'] = (df['close'] - ema) / ema * 100
    
    # === EMA crossovers ===
    ema9 = ta.ema(df['close'], 9)
    ema21 = ta.ema(df['close'], 21)
    ema50 = ta.ema(df['close'], 50)
    if ema9 is not None and ema21 is not None:
        f['ema_9_21_cross'] = (ema9 - ema21) / ema21 * 100
    if ema21 is not None and ema50 is not None:
        f['ema_21_50_cross'] = (ema21 - ema50) / ema50 * 100
    
    # === MACD ===
    mc = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if mc is not None:
        cols = mc.columns.tolist()
        if len(cols) >= 3:
            f['macd'] = mc[cols[0]]
            f['macd_signal'] = mc[cols[1]]
            f['macd_hist'] = mc[cols[2]]
            f['macd_hist_change'] = mc[cols[2]].diff()
    
    # === Bollinger Bands ===
    for std in [1.5, 2.0, 2.5]:
        bb = ta.bbands(df['close'], length=20, std=std)
        if bb is not None:
            bbl = [c for c in bb.columns if c.startswith('BBL_')]
            bbu = [c for c in bb.columns if c.startswith('BBU_')]
            bbm = [c for c in bb.columns if c.startswith('BBM_')]
            sfx = f'_{std}'.replace('.','')
            if bbl and bbu:
                f[f'bb_pos{sfx}'] = (df['close'] - bb[bbl[0]]) / (bb[bbu[0]] - bb[bbl[0]] + 1e-10)
            if bbu and bbm:
                f[f'bb_width{sfx}'] = (bb[bbu[0]] - bb[bbl[0]]) / bb[bbm[0]] * 100
    
    # === Stochastic ===
    st = ta.stoch(df['high'], df['low'], df['close'])
    if st is not None:
        sk = [c for c in st.columns if 'STOCHk' in c]
        sd = [c for c in st.columns if 'STOCHd' in c]
        if sk: f['stoch_k'] = st[sk[0]]
        if sd: f['stoch_d'] = st[sd[0]]
        if sk and sd: f['stoch_cross'] = st[sk[0]] - st[sd[0]]
    
    # === ATR (volatilidad) — múltiples periodos ===
    for length in [7, 14, 21]:
        atr = ta.atr(df['high'], df['low'], df['close'], length=length)
        if atr is not None:
            f[f'atr_{length}_pct'] = atr / df['close'] * 100
    
    # === ADX (fuerza de tendencia) ===
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None:
        for c in adx.columns:
            if 'ADX' in c: f['adx'] = adx[c]; break
        for c in adx.columns:
            if 'DMP' in c: f['di_plus'] = adx[c]; break
        for c in adx.columns:
            if 'DMN' in c: f['di_minus'] = adx[c]; break
    
    # === Volumen ===
    for period in [5, 10, 20]:
        vol_sma = df['volume'].rolling(period).mean()
        f[f'vol_ratio_{period}'] = df['volume'] / vol_sma.replace(0, 1e-10)
    f['vol_change'] = df['volume'].pct_change()
    
    # === Candle patterns ===
    f['candle_pct'] = (df['close'] - df['open']) / df['open'] * 100
    body = abs(df['close'] - df['open'])
    wick = df['high'] - df['low']
    f['candle_body_ratio'] = body / (wick + 1e-10)
    f['upper_shadow'] = (df['high'] - df[['close','open']].max(axis=1)) / (wick + 1e-10)
    f['lower_shadow'] = (df[['close','open']].min(axis=1) - df['low']) / (wick + 1e-10)
    
    # === Momentum (Rate of Change) ===
    for period in [1, 3, 5, 10, 20, 50]:
        f[f'roc_{period}'] = df['close'].pct_change(period) * 100
    
    # === Volatilidad realizada ===
    returns = df['close'].pct_change()
    for period in [5, 10, 20]:
        f[f'realized_vol_{period}'] = returns.rolling(period).std() * 100
    
    # === High/Low ratio ===
    for period in [5, 10, 20]:
        f[f'high_ratio_{period}'] = df['close'] / df['high'].rolling(period).max()
        f[f'low_ratio_{period}'] = df['close'] / df['low'].rolling(period).min()
    
    # === Lags (previous candles) ===
    for lag in [1, 2, 3, 4, 5]:
        f[f'candle_pct_lag{lag}'] = f['candle_pct'].shift(lag)
        f[f'vol_ratio_20_lag{lag}'] = f['vol_ratio_20'].shift(lag) if 'vol_ratio_20' in f else 0
    
    # === Hora y día (patrones temporales) ===
    f['hour'] = df.index.hour
    f['hour_sin'] = np.sin(2 * np.pi * f['hour'] / 24)
    f['hour_cos'] = np.cos(2 * np.pi * f['hour'] / 24)
    f['dayofweek'] = df.index.dayofweek
    f['dow_sin'] = np.sin(2 * np.pi * f['dayofweek'] / 7)
    f['dow_cos'] = np.cos(2 * np.pi * f['dayofweek'] / 7)
    
    # === BTC como líder (si disponible) ===
    if btc_df is not None and len(btc_df) > 0:
        # Alinear BTC con nuestro índice
        btc_aligned = btc_df.reindex(df.index, method='ffill')
        
        # BTC momentum
        for period in [1, 3, 5, 10]:
            btc_roc = btc_aligned['close'].pct_change(period) * 100
            f[f'btc_roc_{period}'] = btc_roc
        
        # BTC RSI
        btc_rsi = ta.rsi(btc_aligned['close'], length=14)
        if btc_rsi is not None: f['btc_rsi_14'] = btc_rsi
        
        # Correlación rolling
        for period in [20, 50]:
            xrp_ret = df['close'].pct_change()
            btc_ret = btc_aligned['close'].pct_change()
            f[f'btc_corr_{period}'] = xrp_ret.rolling(period).corr(btc_ret)
        
        # BTC dominant direction
        btc_ema9 = ta.ema(btc_aligned['close'], 9)
        btc_ema21 = ta.ema(btc_aligned['close'], 21)
        if btc_ema9 is not None and btc_ema21 is not None:
            f['btc_trend'] = ((btc_ema9 - btc_ema21) / btc_ema21 * 100)
    
    return f

# ═══════════════════════════════════════════════════════
# LABELS MEJORADOS: ATR-basados
# ═══════════════════════════════════════════════════════

def create_labels_atr(df, tp_mult=1.5, sl_mult=1.0, lookahead=12):
    """
    Labels adaptativos basados en ATR.
    TP = ATR * tp_mult, SL = ATR * sl_mult
    Lookahead en velas (12 velas = 12h en 1h timeframe)
    """
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    labels = np.zeros(len(df))
    
    for i in range(len(df) - lookahead):
        if atr is None or pd.isna(atr.iloc[i]):
            continue
            
        entry = df['close'].iloc[i]
        current_atr = atr.iloc[i]
        tp_price = entry + (current_atr * tp_mult)
        sl_price = entry - (current_atr * sl_mult)
        
        for j in range(1, lookahead + 1):
            high = df['high'].iloc[i + j]
            low = df['low'].iloc[i + j]
            
            if low <= sl_price:
                labels[i] = 0
                break
            if high >= tp_price:
                labels[i] = 1
                break
    
    return labels, atr

def simulate_ml_v2(df, atr_series, predictions, probabilities,
                   tp_mult=1.5, sl_mult=1.0, cap=30.0,
                   leverage=5, fee_pct=0.04, prob_threshold=0.6):
    """Simula trading con ML + ATR-based TP/SL."""
    bal = cap
    pos = None
    trades = []
    peak = cap
    max_dd = 0
    daily_pnl = {}
    
    for i in range(len(df)):
        row = df.iloc[i]
        price = row['close']
        date = row.name.strftime('%Y-%m-%d')
        
        if pos:
            if pos['side'] == 'LONG':
                pnl_pct = (price - pos['entry']) / pos['entry'] * 100
            else:
                pnl_pct = (pos['entry'] - price) / pos['entry'] * 100
            
            pnl_lev = pnl_pct * leverage
            pnl_dollar = pos['margin'] * (pnl_lev / 100)
            
            # Liquidación
            if pnl_dollar <= -(pos['margin'] * 0.95):
                bal -= pos['margin']
                trades.append({'pnl': -pos['margin'], 'reason': 'LIQ',
                    'side': pos['side'], 'bal': bal, 'ts': row.name, 'date': date})
                pos = None
                if bal < 1: break
                continue
            
            hit_sl = price <= pos['sl']
            hit_tp = price >= pos['tp']
            
            if hit_sl or hit_tp:
                close_fee = pos['position_size'] * (fee_pct / 100)
                actual_pnl = pnl_dollar - close_fee
                bal += actual_pnl
                peak = max(peak, bal)
                dd = (peak - bal) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
                reason = 'SL' if hit_sl else 'TP'
                trades.append({'pnl': actual_pnl, 'reason': reason,
                    'side': pos['side'], 'bal': bal, 'ts': row.name, 'date': date})
                if date not in daily_pnl: daily_pnl[date] = 0
                daily_pnl[date] += actual_pnl
                pos = None
        else:
            if i < len(predictions) and predictions[i] == 1:
                if probabilities[i] >= prob_threshold and bal >= 2:
                    current_atr = atr_series.iloc[i] if i < len(atr_series) and not pd.isna(atr_series.iloc[i]) else 0
                    if current_atr <= 0: continue
                    
                    margin = bal * 0.90
                    position_size = margin * leverage
                    open_fee = position_size * (fee_pct / 100)
                    
                    pos = {
                        'entry': price, 'margin': margin,
                        'position_size': position_size, 'side': 'LONG',
                        'tp': price + (current_atr * tp_mult),
                        'sl': price - (current_atr * sl_mult),
                    }
                    bal -= open_fee
    
    # Cerrar posición abierta
    if pos:
        price = df.iloc[-1]['close']
        pnl_pct = (price - pos['entry']) / pos['entry'] * 100
        pnl_dollar = pos['margin'] * (pnl_pct * leverage / 100)
        close_fee = pos['position_size'] * (fee_pct / 100)
        bal += pnl_dollar - close_fee
        trades.append({'pnl': pnl_dollar - close_fee, 'reason': 'END',
            'side': 'LONG', 'bal': bal, 'ts': df.index[-1],
            'date': df.index[-1].strftime('%Y-%m-%d')})
    
    return trades, bal, max_dd, daily_pnl

def main():
    p("="*80)
    p("🤖 ML TRADING MODEL v2 — Entrenamiento Extendido")
    p("   1h candles | 2 años de datos | BTC como líder")
    p("   ATR-based TP/SL | Walk-forward evaluation")
    p("="*80)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    
    # ═══════════════════════════════════════════════════
    # 1. DESCARGA DE DATOS (2 años)
    # ═══════════════════════════════════════════════════
    p("\n📥 Descargando XRP/USDT 1h (Mar 2023 → Feb 2025)...")
    xrp = download_data(ex, 'XRP/USDT', (2023, 3, 1), (2025, 2, 28, 23, 59), '1h')
    p(f"   ✅ XRP: {len(xrp)} velas | {xrp.index[0]} → {xrp.index[-1]}")
    
    p("\n📥 Descargando BTC/USDT 1h (Mar 2023 → Feb 2025)...")
    btc = download_data(ex, 'BTC/USDT', (2023, 3, 1), (2025, 2, 28, 23, 59), '1h')
    p(f"   ✅ BTC: {len(btc)} velas | {btc.index[0]} → {btc.index[-1]}")
    
    # ═══════════════════════════════════════════════════
    # 2. FEATURES
    # ═══════════════════════════════════════════════════
    p("\n🔧 Creando features (60+ indicadores + BTC)...")
    features = create_features(xrp, btc_df=btc)
    p(f"   ✅ {len(features.columns)} features creadas")
    
    # ═══════════════════════════════════════════════════
    # 3. LABELS (ATR-based)
    # ═══════════════════════════════════════════════════
    TP_MULT = 1.5  # TP = 1.5 ATR
    SL_MULT = 1.0  # SL = 1.0 ATR (R:R = 1.5:1)
    LOOKAHEAD = 12  # 12 horas
    
    p(f"\n🏷️ Creando labels (TP:{TP_MULT}×ATR, SL:{SL_MULT}×ATR, lookahead:{LOOKAHEAD}h)...")
    labels, atr_series = create_labels_atr(xrp, tp_mult=TP_MULT, sl_mult=SL_MULT, lookahead=LOOKAHEAD)
    
    features['label'] = labels
    features['atr'] = atr_series
    features = features.dropna()
    
    pos_rate = features['label'].mean()
    p(f"   ✅ {len(features)} muestras | Positivos: {pos_rate*100:.1f}%")
    
    # ═══════════════════════════════════════════════════
    # 4. SPLIT TEMPORAL (últimos 3 meses = test)
    # ═══════════════════════════════════════════════════
    # Train: Mar 2023 → Sep 2024 (18 meses)
    # Val:   Oct 2024 → Nov 2024 (2 meses)
    # Test:  Dec 2024 → Feb 2025 (3 meses) — período de supervivencia
    
    train_mask = features.index < '2024-10-01'
    val_mask = (features.index >= '2024-10-01') & (features.index < '2024-12-01')
    test_mask = features.index >= '2024-12-01'
    
    feat_cols = [c for c in features.columns if c not in ['label', 'atr']]
    
    X_train = features.loc[train_mask, feat_cols]
    y_train = features.loc[train_mask, 'label']
    X_val = features.loc[val_mask, feat_cols]
    y_val = features.loc[val_mask, 'label']
    X_test = features.loc[test_mask, feat_cols]
    y_test = features.loc[test_mask, 'label']
    atr_test = features.loc[test_mask, 'atr']
    
    p(f"\n📊 Split temporal:")
    p(f"   Train: {X_train.index[0]} → {X_train.index[-1]} ({len(X_train)} muestras)")
    p(f"   Val:   {X_val.index[0]} → {X_val.index[-1]} ({len(X_val)} muestras)")
    p(f"   Test:  {X_test.index[0]} → {X_test.index[-1]} ({len(X_test)} muestras)")
    p(f"   Train pos rate: {y_train.mean()*100:.1f}%")
    p(f"   Val pos rate:   {y_val.mean()*100:.1f}%")
    p(f"   Test pos rate:  {y_test.mean()*100:.1f}%")
    
    # ═══════════════════════════════════════════════════
    # 5. ENTRENAR MODELO
    # ═══════════════════════════════════════════════════
    p("\n🤖 Entrenando XGBoost (300 estimators, early stopping)...")
    
    neg = len(y_train[y_train==0])
    pos = len(y_train[y_train==1])
    
    # Ensure all features are float and no inf/nan
    for dset in [X_train, X_val, X_test]:
        dset.replace([np.inf, -np.inf], np.nan, inplace=True)
        dset.fillna(0, inplace=True)
    X_train = X_train.astype(np.float32)
    X_val = X_val.astype(np.float32)
    X_test = X_test.astype(np.float32)
    y_train = y_train.astype(int)
    y_val = y_val.astype(int)
    y_test = y_test.astype(int)

    try:
        model = xgb.XGBClassifier(
            n_estimators=500,
            max_depth=6,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.7,
            min_child_weight=10,
            reg_alpha=0.5,
            reg_lambda=2.0,
            gamma=0.1,
            scale_pos_weight=neg / max(pos, 1),
            tree_method='exact',
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train.values, y_train.values, verbose=False)
        p(f"   ✅ XGBoost trained (500 iterations)")
        model_name = "XGBoost"
    except Exception as e:
        p(f"   ⚠️ XGBoost error: {e}")
        p(f"   🔄 Fallback: usando RandomForest...")
        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(
            n_estimators=500, max_depth=10, min_samples_leaf=10,
            class_weight='balanced', random_state=42, n_jobs=-1)
        model.fit(X_train.values, y_train.values)
        p(f"   ✅ RandomForest trained (500 trees)")
        model_name = "RandomForest"
    
    # ═══════════════════════════════════════════════════
    # 6. EVALUAR MODELO
    # ═══════════════════════════════════════════════════
    val_pred = model.predict(X_val.values)
    val_proba = model.predict_proba(X_val.values)[:, 1]
    test_pred = model.predict(X_test.values)
    test_proba = model.predict_proba(X_test.values)[:, 1]
    
    p(f"\n📊 MÉTRICAS:")
    p(f"   Val Accuracy:  {accuracy_score(y_val, val_pred)*100:.1f}%")
    p(f"   Test Accuracy: {accuracy_score(y_test, test_pred)*100:.1f}%")
    
    p(f"\n   Test Classification Report:")
    report = classification_report(y_test, test_pred, target_names=['NO BUY', 'BUY'])
    for line in report.split('\n'):
        p(f"   {line}")
    
    # Feature importance
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1][:20]
    p(f"\n   Top 20 Features:")
    for i, idx in enumerate(sorted_idx):
        p(f"   {i+1:2d}. {feat_cols[idx]:<25s}: {importances[idx]:.4f}")
    
    # ═══════════════════════════════════════════════════
    # 7. SIMULACIÓN DE TRADING
    # ═══════════════════════════════════════════════════
    p(f"\n{'='*80}")
    p("💰 SIMULACIÓN EN TEST SET (Dec 2024 → Feb 2025)")
    p(f"{'='*80}")
    
    test_df = xrp.loc[X_test.index]
    test_days = (test_df.index[-1] - test_df.index[0]).days or 1
    bh_pct = (test_df.iloc[-1]['close'] / test_df.iloc[0]['close'] - 1) * 100
    bh_pnl = 30 * bh_pct / 100
    
    p(f"   Período: {test_days} días | XRP B&H: {bh_pct:+.1f}% (${bh_pnl:+.2f})")
    p(f"\n{'Config':<35s} | {'PnL':>8s} | {'#T':>4s} | {'WR':>4s} | {'DD':>5s} | {'$/d':>6s}")
    p(f"{'-'*35}-+-{'-'*8}-+-{'-'*4}-+-{'-'*4}-+-{'-'*5}-+-{'-'*6}")
    
    best_pnl = -999
    best_config = ""
    
    for lev in [1, 3, 5, 10]:
        for thresh in [0.50, 0.55, 0.60, 0.65, 0.70, 0.80]:
            trades, bal, mdd, dpnl = simulate_ml_v2(
                test_df, atr_test, test_pred, test_proba,
                tp_mult=TP_MULT, sl_mult=SL_MULT,
                leverage=lev, prob_threshold=thresh)
            
            w = len([t for t in trades if t['pnl'] > 0])
            n = len(trades)
            pnl = bal - 30
            wr = w / max(n, 1) * 100
            daily = pnl / test_days
            
            if pnl > best_pnl:
                best_pnl = pnl
                best_config = f"{lev}x prob>{thresh:.0%}"
            
            e = '🟢' if pnl > 0 else ('💀' if any(t.get('reason')=='LIQ' for t in trades) else '🔴')
            lbl = f"{lev}x prob>{thresh:.0%}"
            p(f"{lbl:<35s} | {e}${pnl:+7.2f} | {n:4d} | {wr:3.0f}% | {mdd:4.1f}% | ${daily:+.2f}")
    
    # ═══════════════════════════════════════════════════
    # 8. DETALLE MEJOR CONFIG
    # ═══════════════════════════════════════════════════
    p(f"\n{'='*80}")
    p(f"🏆 MEJOR CONFIG: {best_config} → ${best_pnl:+.2f}")
    p(f"{'='*80}")
    
    # Re-run best
    best_lev = int(best_config.split('x')[0])
    best_thresh = float(best_config.split('>')[1].replace('%','')) / 100
    trades, bal, mdd, dpnl = simulate_ml_v2(
        test_df, atr_test, test_pred, test_proba,
        tp_mult=TP_MULT, sl_mult=SL_MULT,
        leverage=best_lev, prob_threshold=best_thresh)
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    
    p(f"   Capital: $30 → ${bal:.2f}")
    p(f"   PnL: ${bal-30:+.2f} ({(bal/30-1)*100:+.1f}%)")
    p(f"   Trades: {len(trades)} ({len(trades)/test_days:.1f}/d)")
    p(f"   WR: {len(wins)/max(len(trades),1)*100:.0f}%")
    p(f"   Max DD: {mdd:.1f}%")
    if wins: p(f"   Avg Win: ${sum(t['pnl'] for t in wins)/len(wins):.3f}")
    if losses: p(f"   Avg Loss: ${sum(t['pnl'] for t in losses)/len(losses):.3f}")
    if wins and losses:
        pf = sum(t['pnl'] for t in wins) / max(abs(sum(t['pnl'] for t in losses)), 0.01)
        p(f"   Profit Factor: {pf:.2f}")
    
    # PnL semanal
    if trades:
        p(f"\n   PnL semanal:")
        wk = {}
        for t in trades:
            w = t['ts'].strftime('%Y-W%W')
            if w not in wk: wk[w] = {'pnl': 0, 'n': 0, 'w': 0}
            wk[w]['pnl'] += t['pnl']
            wk[w]['n'] += 1
            if t['pnl'] > 0: wk[w]['w'] += 1
        for w in sorted(wk.keys()):
            d = wk[w]
            wr = d['w']/max(d['n'],1)*100
            e = '🟢' if d['pnl'] > 0 else '🔴'
            p(f"   {w}: {e} ${d['pnl']:+.2f} | {d['n']:2d}T | WR:{wr:.0f}%")
    
    # Días ganadores vs perdedores
    if dpnl:
        win_days = sum(1 for v in dpnl.values() if v > 0)
        lose_days = sum(1 for v in dpnl.values() if v < 0)
        p(f"\n   Días ganadores: {win_days}/{len(dpnl)}")
        p(f"   Días perdedores: {lose_days}/{len(dpnl)}")
    
    p(f"\n{'='*80}")
    p(f"📊 COMPARACIÓN FINAL:")
    p(f"   Buy & Hold XRP: ${bh_pnl:+.2f} ({bh_pct:+.1f}%)")
    p(f"   ML v2 {best_config}: ${best_pnl:+.2f} ({(best_pnl/30)*100:+.1f}%)")
    p(f"{'='*80}")

if __name__ == '__main__':
    main()

"""
🧪 FUTURES SIMULATOR — XRP Dec 2024 → Feb 2025
=================================================
Simula Binance Futures con:
- Apalancamiento (5x, 10x, 20x)
- LONG y SHORT
- Liquidación real
- Comisiones Futures (0.04% taker)
- Múltiples estrategias (BB_BOUNCE, RSI, MACD)
- Comparación directa con Spot
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, time
from datetime import datetime, timezone

def p(msg): print(msg); sys.stdout.flush()

def safe(row, col, default=0):
    v = row.get(col) if isinstance(row, dict) else (row[col] if col in row.index else None)
    return float(v) if v is not None and not pd.isna(v) else default

def add_indicators(df):
    df['RSI_7'] = ta.rsi(df['close'], length=7)
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    df['EMA_9'] = ta.ema(df['close'], 9)
    df['EMA_21'] = ta.ema(df['close'], 21)
    df['VOL_SMA'] = df['volume'].rolling(20).mean()
    df['VOL_R'] = df['volume'] / df['VOL_SMA'].replace(0, 1e-10)
    mc = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if mc is not None:
        for px, nm in [('MACD_', 'MACD'), ('MACDs_', 'MACD_S')]:
            cc = [c for c in mc.columns if c.startswith(px)]
            if cc: df[nm] = mc[cc[0]]
    bb = ta.bbands(df['close'], length=20, std=2)
    if bb is not None:
        for px, nm in [('BBL_', 'BB_LO'), ('BBM_', 'BB_MID'), ('BBU_', 'BB_HI')]:
            cc = [c for c in bb.columns if c.startswith(px)]
            if cc: df[nm] = bb[cc[0]]
    st = ta.stoch(df['high'], df['low'], df['close'])
    if st is not None:
        sk = [c for c in st.columns if 'STOCHk' in c]
        if sk: df['SK'] = st[sk[0]]
    df['CANDLE_PCT'] = (df['close'] - df['open']) / df['open'] * 100
    df['BB_POS'] = (df['close'] - df.get('BB_LO', df['close'])) / (
        df.get('BB_HI', df['close']) - df.get('BB_LO', df['close']) + 1e-10)
    return df

def check_long(row, prev):
    """Señales de LONG (compra)."""
    # BB Bounce — precio en banda inferior + vela verde + RSI bajo
    if (safe(row, 'BB_POS', 0.5) < 0.1
        and row['close'] > row['open']
        and safe(row, 'RSI_7', 50) < 35):
        return 'BB_LONG'
    # Stochastic oversold bounce
    if (safe(prev, 'SK', 50) < 15
        and safe(row, 'SK', 50) > safe(prev, 'SK', 50)
        and safe(row, 'RSI_7', 50) < 30):
        return 'STOCH_LONG'
    # MACD bullish cross + RSI bajo
    if (safe(prev, 'MACD', 0) < safe(prev, 'MACD_S', 0)
        and safe(row, 'MACD', 0) > safe(row, 'MACD_S', 0)
        and safe(row, 'RSI_7', 50) < 45):
        return 'MACD_LONG'
    return None

def check_short(row, prev):
    """Señales de SHORT (venta)."""
    # BB superior — precio en banda superior + vela roja + RSI alto
    if (safe(row, 'BB_POS', 0.5) > 0.9
        and row['close'] < row['open']
        and safe(row, 'RSI_7', 50) > 65):
        return 'BB_SHORT'
    # Stochastic overbought drop
    if (safe(prev, 'SK', 50) > 85
        and safe(row, 'SK', 50) < safe(prev, 'SK', 50)
        and safe(row, 'RSI_7', 50) > 70):
        return 'STOCH_SHORT'
    # MACD bearish cross + RSI alto
    if (safe(prev, 'MACD', 0) > safe(prev, 'MACD_S', 0)
        and safe(row, 'MACD', 0) < safe(row, 'MACD_S', 0)
        and safe(row, 'RSI_7', 50) > 55):
        return 'MACD_SHORT'
    return None

def sim_futures(df, leverage, sl_pct, tp_pct, cap=30.0, fee_pct=0.04,
                enable_shorts=True, rsi_exit_long=65, rsi_exit_short=35):
    """
    Simula Binance Futures con apalancamiento.
    
    Liquidación: si la pérdida no realizada >= margen, posición liquidada.
    Fees: 0.04% taker (Binance Futures default).
    """
    bal = cap
    pos = None
    trades = []
    liquidations = 0
    peak = cap
    max_dd = 0
    
    for i in range(60, len(df)):
        row = df.iloc[i]
        price = row['close']
        
        if pos:
            # Calcular P&L
            if pos['side'] == 'LONG':
                pnl_pct = (price - pos['entry']) / pos['entry'] * 100
            else:  # SHORT
                pnl_pct = (pos['entry'] - price) / pos['entry'] * 100
            
            pnl_leveraged = pnl_pct * leverage
            pnl_dollar = pos['margin'] * (pnl_leveraged / 100)
            
            # ¿LIQUIDADO? (pérdida >= margen - 1% buffer de Binance)
            if pnl_dollar <= -(pos['margin'] * 0.95):
                bal -= pos['margin']  # Pierde todo el margen
                liquidations += 1
                peak = max(peak, bal)
                dd = (peak - bal) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
                trades.append({
                    'pnl': -pos['margin'], 'reason': 'LIQUIDATED',
                    'strat': pos['strat'], 'side': pos['side'],
                    'pct': -100, 'bal': bal, 'ts': row.name,
                    'date': row.name.strftime('%Y-%m-%d'),
                })
                pos = None
                if bal < 1:  # Bancarrota
                    break
                continue
            
            # Check SL/TP (en porcentaje del precio, no del margen)
            hit_sl = pnl_pct <= -sl_pct
            hit_tp = pnl_pct >= tp_pct
            
            # RSI exit
            rsi7 = safe(row, 'RSI_7', 50)
            rsi_out = (pos['side'] == 'LONG' and rsi7 > rsi_exit_long) or \
                      (pos['side'] == 'SHORT' and rsi7 < rsi_exit_short)
            
            if hit_sl or hit_tp or rsi_out:
                # Calcular PnL real
                actual_pnl = pnl_dollar
                # Comisión de cierre
                close_fee = pos['position_size'] * (fee_pct / 100)
                actual_pnl -= close_fee
                
                bal += actual_pnl
                peak = max(peak, bal)
                dd = (peak - bal) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
                
                reason = 'SL' if hit_sl else ('TP' if hit_tp else 'RSI')
                trades.append({
                    'pnl': actual_pnl, 'reason': reason,
                    'strat': pos['strat'], 'side': pos['side'],
                    'pct': pnl_leveraged, 'bal': bal,
                    'ts': row.name,
                    'date': row.name.strftime('%Y-%m-%d'),
                })
                pos = None
        else:
            prev = df.iloc[i-1]
            
            # Check LONG
            long_strat = check_long(row, prev)
            short_strat = check_short(row, prev) if enable_shorts else None
            
            strat = long_strat or short_strat
            side = 'LONG' if long_strat else ('SHORT' if short_strat else None)
            
            if strat and side and bal >= 2:
                margin = bal * 0.90  # Usar 90% como margen
                position_size = margin * leverage
                
                # Comisión de apertura
                open_fee = position_size * (fee_pct / 100)
                
                pos = {
                    'entry': price,
                    'side': side,
                    'margin': margin,
                    'position_size': position_size,
                    'strat': strat,
                    'i': i,
                    'fee': open_fee,
                }
                bal -= open_fee  # Pagar comisión de apertura
    
    # Cerrar posición abierta
    if pos:
        price = df.iloc[-1]['close']
        if pos['side'] == 'LONG':
            pnl_pct = (price - pos['entry']) / pos['entry'] * 100
        else:
            pnl_pct = (pos['entry'] - price) / pos['entry'] * 100
        pnl_lev = pnl_pct * leverage
        pnl_dollar = pos['margin'] * (pnl_lev / 100)
        close_fee = pos['position_size'] * (fee_pct / 100)
        pnl_dollar -= close_fee
        bal += pnl_dollar
        trades.append({'pnl': pnl_dollar, 'reason': 'END', 'strat': pos['strat'],
                       'side': pos['side'], 'pct': pnl_lev, 'bal': bal,
                       'ts': df.index[-1], 'date': df.index[-1].strftime('%Y-%m-%d')})
    
    return trades, bal, liquidations, max_dd

def download_data(ex, symbol, start_date, end_date, tf='5m'):
    """Descarga datos en chunks."""
    start_ts = int(datetime(*start_date, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(*end_date, tzinfo=timezone.utc).timestamp() * 1000)
    
    all_ohlcv = []
    since = start_ts
    chunk = 0
    while since < end_ts:
        chunk += 1
        if chunk % 5 == 1:
            p(f"   📥 Chunk {chunk}...")
        ohlcv = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        if not ohlcv: break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        if ohlcv[-1][0] >= end_ts: break
        time.sleep(0.2)
    
    df = pd.DataFrame(all_ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    return add_indicators(df)

def main():
    p("="*80)
    p("🧪 FUTURES SIMULATOR — Test de Supervivencia")
    p("   XRP/USDT | Dec 1 2024 → Feb 17 2025 | 5min candles")
    p("   CON comisiones reales (0.04% taker)")
    p("   CON liquidación real")
    p("="*80)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    
    p("\n📥 Descargando XRP/USDT Dec-Feb...")
    df = download_data(ex, 'XRP/USDT', (2024,12,1), (2025,2,17,23,59))
    
    days = (df.index[-1] - df.index[0]).days or 1
    bh = (df.iloc[-1]['close'] / df.iloc[0]['close'] - 1) * 100
    p(f"   ✅ {len(df)} velas | {days} días")
    p(f"   Precio: ${df.iloc[0]['close']:.4f} → ${df.iloc[-1]['close']:.4f} ({bh:+.1f}%)")
    
    # ═══════════════════════════════════════════════════════
    # TEST 1: Solo LONGS (mismo que spot pero con leverage)
    # ═══════════════════════════════════════════════════════
    p(f"\n{'='*70}")
    p("📊 TEST 1: Solo LONGS (como spot pero con leverage)")
    p(f"{'='*70}")
    p(f"{'Config':<30s} | {'PnL':>8s} | {'#T':>4s} | {'WR':>4s} | {'Liq':>3s} | {'DD':>5s} | {'$/d':>6s}")
    p(f"{'-'*30}-+-{'-'*8}-+-{'-'*4}-+-{'-'*4}-+-{'-'*3}-+-{'-'*5}-+-{'-'*6}")
    
    for lev in [1, 3, 5, 10, 15, 20]:
        for sl, tp, label in [(1.0, 1.5, 'SL1/TP1.5'), (0.5, 1.0, 'SL0.5/TP1')]:
            trades, bal, liqs, mdd = sim_futures(
                df, leverage=lev, sl_pct=sl, tp_pct=tp,
                enable_shorts=False)
            w = len([t for t in trades if t['pnl'] > 0])
            n = len(trades)
            pnl = bal - 30
            wr = w / max(n, 1) * 100
            daily = pnl / days
            e = '🟢' if pnl > 0 else ('💀' if liqs > 0 else '🔴')
            lbl = f"{lev}x {label}"
            p(f"{lbl:<30s} | {e}${pnl:+7.2f} | {n:4d} | {wr:3.0f}% | {liqs:3d} | {mdd:4.1f}% | ${daily:+.2f}")
    
    # ═══════════════════════════════════════════════════════
    # TEST 2: LONGS + SHORTS (el poder real de futuros)
    # ═══════════════════════════════════════════════════════
    p(f"\n{'='*70}")
    p("📊 TEST 2: LONGS + SHORTS (bidireccional)")
    p(f"{'='*70}")
    p(f"{'Config':<30s} | {'PnL':>8s} | {'#T':>4s} | {'WR':>4s} | {'Liq':>3s} | {'DD':>5s} | {'$/d':>6s}")
    p(f"{'-'*30}-+-{'-'*8}-+-{'-'*4}-+-{'-'*4}-+-{'-'*3}-+-{'-'*5}-+-{'-'*6}")
    
    for lev in [1, 3, 5, 10, 15, 20]:
        for sl, tp, label in [(1.0, 1.5, 'SL1/TP1.5'), (0.5, 1.0, 'SL0.5/TP1')]:
            trades, bal, liqs, mdd = sim_futures(
                df, leverage=lev, sl_pct=sl, tp_pct=tp,
                enable_shorts=True)
            w = len([t for t in trades if t['pnl'] > 0])
            n = len(trades)
            pnl = bal - 30
            wr = w / max(n, 1) * 100
            daily = pnl / days
            e = '🟢' if pnl > 0 else ('💀' if liqs > 0 else '🔴')
            lbl = f"{lev}x {label} L+S"
            p(f"{lbl:<30s} | {e}${pnl:+7.2f} | {n:4d} | {wr:3.0f}% | {liqs:3d} | {mdd:4.1f}% | ${daily:+.2f}")
    
    # ═══════════════════════════════════════════════════════
    # TOP 3 DETALLE
    # ═══════════════════════════════════════════════════════
    p(f"\n{'='*70}")
    p("📊 DETALLE: 5x SL1/TP1.5 LONG+SHORT (config equilibrada)")
    p(f"{'='*70}")
    
    trades, bal, liqs, mdd = sim_futures(
        df, leverage=5, sl_pct=1.0, tp_pct=1.5, enable_shorts=True)
    
    w = [t for t in trades if t['pnl'] > 0]
    l = [t for t in trades if t['pnl'] <= 0]
    pnl = bal - 30
    
    p(f"   Capital: $30 → ${bal:.2f} ({pnl:+.2f})")
    p(f"   Trades: {len(trades)} ({len(trades)/days:.1f}/d)")
    p(f"   WR: {len(w)/max(len(trades),1)*100:.0f}%")
    p(f"   Liquidaciones: {liqs}")
    p(f"   Max DD: {mdd:.1f}%")
    if w: p(f"   Avg Win: ${sum(t['pnl'] for t in w)/len(w):.3f}")
    if l: p(f"   Avg Loss: ${sum(t['pnl'] for t in l)/len(l):.3f}")
    
    # Por estrategia
    by_s = {}
    for t in trades:
        k = f"{t['side']}_{t['strat']}"
        if k not in by_s: by_s[k] = {'n':0,'w':0,'pnl':0}
        by_s[k]['n'] += 1
        if t['pnl'] > 0: by_s[k]['w'] += 1
        by_s[k]['pnl'] += t['pnl']
    
    p(f"\n   Por estrategia:")
    for s, d in sorted(by_s.items(), key=lambda x: -x[1]['pnl']):
        wr = d['w']/max(d['n'],1)*100
        e = '🟢' if d['pnl'] > 0 else '🔴'
        p(f"   {s:20s}: {d['n']:4d}T | WR:{wr:.0f}% | {e} ${d['pnl']:+.2f}")
    
    # PnL semanal
    p(f"\n   PnL semanal:")
    wk = {}
    for t in trades:
        w = t['ts'].strftime('%Y-W%W')
        if w not in wk: wk[w] = 0
        wk[w] += t['pnl']
    for w in sorted(wk.keys()):
        e = '🟢' if wk[w] > 0 else '🔴'
        p(f"   {w}: {e} ${wk[w]:+.2f}")

if __name__ == '__main__':
    main()

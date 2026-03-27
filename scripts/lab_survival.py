"""
🧪 TEST DE SUPERVIVENCIA: XRP Dec 1 2024 → Feb 17 2025
========================================================
79 días de datos reales en 5min. Prueba ciega total.
Multi-estrategia: BB_BOUNCE, STOCH_OB, MACD_CROSS, DIP_BUY
SL: 1.0% | TP: 1.5% | RSI Exit: 65
Capital: $30
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

def check_entry(row, prev):
    """Múltiples estrategias — devuelve nombre o None."""
    # 1. BB_BOUNCE — Rebote en Bollinger inferior (la estrella: 83-86% WR)
    if (safe(row, 'BB_POS', 0.5) < 0.1
        and row['close'] > row['open']
        and safe(row, 'RSI_7', 50) < 40):
        return 'BB_BOUNCE'
    
    # 2. STOCH_OB — Stochastic oversold + rebote (60-67% WR)
    if (safe(prev, 'SK', 50) < 15
        and safe(row, 'SK', 50) > safe(prev, 'SK', 50)
        and safe(row, 'RSI_7', 50) < 35):
        return 'STOCH_OB'
    
    # 3. MACD_CROSS — MACD cruza señal positivamente
    if (safe(prev, 'MACD', 0) < safe(prev, 'MACD_S', 0)
        and safe(row, 'MACD', 0) > safe(row, 'MACD_S', 0)
        and safe(row, 'RSI_7', 50) < 45):
        return 'MACD_CROSS'
    
    # 4. DIP_BUY — Vela roja fuerte → rebote con volumen
    if (safe(prev, 'CANDLE_PCT', 0) < -0.5
        and row['close'] > row['open']
        and safe(row, 'VOL_R', 1) > 1.5
        and safe(row, 'RSI_7', 50) < 40):
        return 'DIP_BUY'
    
    # 5. EMA_CROSS — EMA9 cruza sobre EMA21 (solo si RSI bajo)
    if (safe(prev, 'EMA_9', 0) < safe(prev, 'EMA_21', 0)
        and safe(row, 'EMA_9', 0) > safe(row, 'EMA_21', 0)
        and safe(row, 'RSI_7', 50) < 50):
        return 'EMA_CROSS'
    
    return None

def main():
    p("="*80)
    p("🧪 TEST DE SUPERVIVENCIA — XRP/USDT")
    p("   Dec 1, 2024 → Feb 17, 2025 (79 días)")
    p("   5min candles | $30 capital | Multi-estrategia")
    p("   SL: 1.0% | TP: 1.5% | RSI Exit: 65")
    p("="*80)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    
    # Descargar en chunks (Binance max 1000 velas por request)
    start_ts = int(datetime(2024, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(2025, 2, 17, 23, 59, tzinfo=timezone.utc).timestamp() * 1000)
    
    all_ohlcv = []
    since = start_ts
    chunk = 0
    
    while since < end_ts:
        chunk += 1
        p(f"   📥 Descargando chunk {chunk}...")
        ohlcv = ex.fetch_ohlcv('XRP/USDT', '5m', since=since, limit=1000)
        if not ohlcv:
            break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        if ohlcv[-1][0] >= end_ts:
            break
        time.sleep(0.3)
    
    df = pd.DataFrame(all_ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    
    # Filtrar al rango exacto
    df = df[df.index >= '2024-12-01']
    df = df[df.index <= '2025-02-17 23:59:59']
    
    df = add_indicators(df)
    
    days = (df.index[-1] - df.index[0]).days
    p(f"\n   ✅ {len(df)} velas descargadas ({days} días)")
    p(f"   Rango: {df.index[0]} → {df.index[-1]}")
    p(f"   Precio: ${df.iloc[0]['close']:.4f} → ${df.iloc[-1]['close']:.4f}")
    bh_pct = (df.iloc[-1]['close'] / df.iloc[0]['close'] - 1) * 100
    p(f"   Buy&Hold: {bh_pct:+.1f}%")
    
    # === SIMULACIÓN ===
    SL_PCT = 1.0
    TP_PCT = 1.5
    RSI_EXIT = 65
    
    bal = 30.0
    pos = None
    trades = []
    peak = 30.0
    max_dd = 0
    daily_pnl = {}  # {date: pnl}
    
    for i in range(60, len(df)):
        row = df.iloc[i]
        date = row.name.strftime('%Y-%m-%d')
        
        if pos:
            price = row['close']
            # Trailing
            gain = (price - pos['entry']) / pos['entry'] * 100
            if gain > 1.0:
                new_sl = price * (1 - 1.0/100)
                if new_sl > pos['sl']:
                    pos['sl'] = new_sl
            
            hit_sl = price <= pos['sl']
            hit_tp = price >= pos['tp']
            rsi_out = safe(row, 'RSI_7', 50) > RSI_EXIT
            
            if hit_sl or hit_tp or rsi_out:
                pnl = (price - pos['entry']) * pos['amount']
                bal += pnl
                peak = max(peak, bal)
                dd = (peak - bal) / peak * 100
                max_dd = max(max_dd, dd)
                
                reason = 'SL' if hit_sl else ('TP' if hit_tp else 'RSI')
                trades.append({
                    'pnl': pnl, 'reason': reason, 'strat': pos['strat'],
                    'pct': (price/pos['entry']-1)*100, 'bal': bal,
                    'ts': row.name, 'date': date,
                })
                
                if date not in daily_pnl: daily_pnl[date] = 0
                daily_pnl[date] += pnl
                
                pos = None
        else:
            prev = df.iloc[i-1]
            strat = check_entry(row, prev)
            if strat:
                price = row['close']
                amount = (bal * 0.90) / price
                pos = {
                    'entry': price, 'amount': amount,
                    'sl': price * (1 - SL_PCT/100),
                    'tp': price * (1 + TP_PCT/100),
                    'strat': strat, 'i': i,
                }
    
    # Cerrar posición abierta
    if pos:
        price = df.iloc[-1]['close']
        pnl = (price - pos['entry']) * pos['amount']
        bal += pnl
        trades.append({'pnl': pnl, 'reason': 'END', 'strat': pos['strat'],
                       'pct': 0, 'bal': bal, 'ts': df.index[-1],
                       'date': df.index[-1].strftime('%Y-%m-%d')})
    
    # === RESULTADOS ===
    p(f"\n{'='*80}")
    p("🏆 RESULTADOS — TEST DE SUPERVIVENCIA XRP")
    p(f"{'='*80}")
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    
    p(f"\n   Capital:      $30.00 → ${bal:.2f}")
    p(f"   PnL total:    ${bal-30:+.2f} ({(bal/30-1)*100:+.1f}%)")
    p(f"   Período:      {days} días")
    p(f"   PnL/día:      ${(bal-30)/max(days,1):.2f}")
    p(f"   PnL/mes:      ${(bal-30)/max(days,1)*30:.2f}")
    p(f"   Max DD:       {max_dd:.1f}%")
    p(f"   Buy&Hold XRP: {bh_pct:+.1f}%")
    
    p(f"\n   Trades:       {len(trades)}")
    p(f"   Trades/día:   {len(trades)/max(days,1):.1f}")
    p(f"   Ganados:      {len(wins)} ({len(wins)/max(len(trades),1)*100:.0f}%)")
    p(f"   Perdidos:     {len(losses)}")
    
    if wins:
        p(f"   Avg Win:      ${sum(t['pnl'] for t in wins)/len(wins):.3f}")
    if losses:
        p(f"   Avg Loss:     ${sum(t['pnl'] for t in losses)/len(losses):.3f}")
    if wins and losses:
        pf = sum(t['pnl'] for t in wins) / max(abs(sum(t['pnl'] for t in losses)), 0.01)
        p(f"   Profit Factor: {pf:.2f}")
    
    # Por estrategia
    p(f"\n   📊 Por estrategia:")
    by_strat = {}
    for t in trades:
        s = t['strat']
        if s not in by_strat: by_strat[s] = {'n': 0, 'w': 0, 'pnl': 0}
        by_strat[s]['n'] += 1
        if t['pnl'] > 0: by_strat[s]['w'] += 1
        by_strat[s]['pnl'] += t['pnl']
    
    for s, d in sorted(by_strat.items(), key=lambda x: -x[1]['pnl']):
        wr = d['w'] / max(d['n'], 1) * 100
        e = '🟢' if d['pnl'] > 0 else '🔴'
        p(f"   {s:12s}: {d['n']:4d}T | WR:{wr:.0f}% | {e} ${d['pnl']:+.2f}")
    
    # Por razón de cierre
    p(f"\n   📊 Razones de cierre:")
    by_reason = {}
    for t in trades:
        r = t['reason']
        if r not in by_reason: by_reason[r] = {'n': 0, 'pnl': 0}
        by_reason[r]['n'] += 1
        by_reason[r]['pnl'] += t['pnl']
    
    for r, d in by_reason.items():
        e = '🟢' if d['pnl'] > 0 else '🔴'
        p(f"   {r:4s}: {d['n']:4d}T | {e} ${d['pnl']:+.2f}")
    
    # PnL por semana
    p(f"\n   📊 PnL por semana:")
    week_pnl = {}
    for t in trades:
        week = t['ts'].strftime('%Y-W%W')
        if week not in week_pnl: week_pnl[week] = {'pnl': 0, 'n': 0, 'w': 0}
        week_pnl[week]['pnl'] += t['pnl']
        week_pnl[week]['n'] += 1
        if t['pnl'] > 0: week_pnl[week]['w'] += 1
    
    for week in sorted(week_pnl.keys()):
        d = week_pnl[week]
        wr = d['w'] / max(d['n'], 1) * 100
        e = '🟢' if d['pnl'] > 0 else '🔴'
        p(f"   {week}: {e} ${d['pnl']:+.2f} | {d['n']:2d}T | WR:{wr:.0f}%")
    
    # Mejores y peores días
    if daily_pnl:
        sorted_days = sorted(daily_pnl.items(), key=lambda x: x[1])
        p(f"\n   📊 Top 5 mejores días:")
        for date, pnl in sorted_days[-5:][::-1]:
            p(f"   {date}: 🟢 ${pnl:+.2f}")
        p(f"\n   📊 Top 5 peores días:")
        for date, pnl in sorted_days[:5]:
            p(f"   {date}: 🔴 ${pnl:+.2f}")
    
    # Días ganadores vs perdedores
    winning_days = sum(1 for v in daily_pnl.values() if v > 0)
    losing_days = sum(1 for v in daily_pnl.values() if v < 0)
    p(f"\n   Días ganadores: {winning_days}/{len(daily_pnl)}")
    p(f"   Días perdedores: {losing_days}/{len(daily_pnl)}")
    
    p(f"\n{'='*80}")

if __name__ == '__main__':
    main()

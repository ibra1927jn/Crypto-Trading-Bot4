"""
🧪 BACKTEST MONITOR STRATEGY — 2 años de datos
=================================================
Simula la estrategia del Monitor Engine:
- Comprar cuando score > umbral (señales combinadas)
- Vender a TP 3% o SL 2%
- Capital: $30
- Test en varias monedas baratas y volátiles
- 1h candles, 2 años (Mar 2023 - Mar 2025)
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, numpy as np, time
from datetime import datetime, timezone

def p(msg): print(msg); sys.stdout.flush()

# ═══════════════════════════════════════════════════════
# DESCARGA
# ═══════════════════════════════════════════════════════

def download(ex, symbol, start, end, tf='1h'):
    start_ts = int(datetime(*start, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(*end, tzinfo=timezone.utc).timestamp() * 1000)
    all_data = []
    since = start_ts
    ch = 0
    while since < end_ts:
        ch += 1
        if ch % 10 == 1: p(f"      Chunk {ch}...")
        try:
            ohlcv = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        except Exception as e:
            p(f"      ⚠️ {e}")
            time.sleep(2)
            continue
        if not ohlcv: break
        all_data.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        if ohlcv[-1][0] >= end_ts: break
        time.sleep(0.15)
    df = pd.DataFrame(all_data, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df[~df.index.duplicated(keep='last')]

# ═══════════════════════════════════════════════════════
# SCORING (misma lógica que monitor_engine.py)
# ═══════════════════════════════════════════════════════

def compute_scores(df):
    """Calcula el score de oportunidad para cada vela."""
    n = len(df)
    scores = np.zeros(n)
    
    # Indicadores
    rsi14 = ta.rsi(df['close'], 14)
    rsi7 = ta.rsi(df['close'], 7)
    bb = ta.bbands(df['close'], length=20, std=2)
    vol_sma = df['volume'].rolling(20).mean()
    
    bb_lo = bb[[c for c in bb.columns if c.startswith('BBL_')][0]] if bb is not None else df['close']
    bb_hi = bb[[c for c in bb.columns if c.startswith('BBU_')][0]] if bb is not None else df['close']
    
    for i in range(50, n):
        score = 0
        price = df['close'].iloc[i]
        
        # 1. Posición en rango 24h (20 pts max)
        h24 = df['high'].iloc[max(0,i-24):i+1].max()
        l24 = df['low'].iloc[max(0,i-24):i+1].min()
        rng = h24 - l24
        if rng > 0:
            rpos = (price - l24) / rng
            if rpos < 0.15: score += 20
            elif rpos < 0.30: score += 15
            elif rpos < 0.45: score += 8
        
        # 2. RSI (20 pts max)
        r14 = rsi14.iloc[i] if rsi14 is not None and not pd.isna(rsi14.iloc[i]) else 50
        if r14 < 25: score += 20
        elif r14 < 35: score += 15
        elif r14 < 45: score += 8
        
        # 3. Volumen (15 pts max)
        vs = vol_sma.iloc[i]
        vr = df['volume'].iloc[i] / vs if vs > 0 else 1
        if vr > 3.0: score += 15
        elif vr > 2.0: score += 10
        elif vr > 1.5: score += 5
        
        # 4. Tendencia corta (15 pts max)
        greens = sum(1 for j in range(max(0,i-2), i+1) 
                     if df['close'].iloc[j] > df['open'].iloc[j])
        if greens >= 3: score += 15
        elif greens >= 2: score += 10
        
        # 5. Bollinger (15 pts max)
        bl = bb_lo.iloc[i] if not pd.isna(bb_lo.iloc[i]) else price
        bh = bb_hi.iloc[i] if not pd.isna(bb_hi.iloc[i]) else price
        bb_rng = bh - bl
        if bb_rng > 0:
            bb_pos = (price - bl) / bb_rng
            if bb_pos < 0.10: score += 15
            elif bb_pos < 0.25: score += 10
        
        # 6. Momentum (15 pts max)
        if i >= 4:
            roc1 = (df['close'].iloc[i] / df['close'].iloc[i-1] - 1) * 100
            roc3 = (df['close'].iloc[i] / df['close'].iloc[i-3] - 1) * 100
            if roc1 > 0 and roc3 < -2: score += 15
            elif roc1 > 0.5: score += 8
        
        scores[i] = score
    
    return scores

# ═══════════════════════════════════════════════════════
# SIMULACIÓN
# ═══════════════════════════════════════════════════════

def simulate(df, scores, tp_pct=3.0, sl_pct=2.0, min_score=65, 
             cap=30.0, fee_pct=0.1, cooldown=6):
    """
    Simula trading basado en scores del monitor.
    cooldown = horas mínimas entre trades.
    """
    bal = cap
    pos = None
    trades = []
    peak = cap
    max_dd = 0
    last_trade_i = -cooldown
    daily_pnl = {}
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        price = row['close']
        date = row.name.strftime('%Y-%m-%d')
        
        if pos:
            pnl_pct = (price - pos['entry']) / pos['entry'] * 100
            
            hit_sl = pnl_pct <= -sl_pct
            hit_tp = pnl_pct >= tp_pct
            
            if hit_sl or hit_tp:
                amount = pos['amount']
                pnl = amount * price - pos['cost']
                # Comisión
                fee = amount * price * (fee_pct / 100)
                pnl -= fee
                
                bal += pnl
                peak = max(peak, bal)
                dd = (peak - bal) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
                
                reason = 'SL' if hit_sl else 'TP'
                trades.append({
                    'pnl': pnl, 'reason': reason, 'pct': pnl_pct,
                    'bal': bal, 'ts': row.name, 'date': date,
                    'score': pos['score'],
                })
                if date not in daily_pnl: daily_pnl[date] = 0
                daily_pnl[date] += pnl
                
                last_trade_i = i
                pos = None
                
                if bal < 2: break  # Bancarrota
        else:
            if scores[i] >= min_score and (i - last_trade_i) >= cooldown:
                amount = (bal * 0.90) / price
                fee = amount * price * (fee_pct / 100)
                pos = {
                    'entry': price,
                    'amount': amount,
                    'cost': amount * price + fee,
                    'score': scores[i],
                    'i': i,
                }
                bal -= fee  # Comisión de apertura
    
    # Cerrar posición abierta
    if pos:
        price = df.iloc[-1]['close']
        pnl = pos['amount'] * price - pos['cost']
        fee = pos['amount'] * price * (fee_pct / 100)
        pnl -= fee
        bal += pnl
        trades.append({'pnl': pnl, 'reason': 'END', 'pct': 0, 
                       'bal': bal, 'ts': df.index[-1],
                       'date': df.index[-1].strftime('%Y-%m-%d'),
                       'score': pos['score']})
    
    return trades, bal, max_dd, daily_pnl

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    p("="*80)
    p("🧪 BACKTEST: Monitor Strategy — 2 años")
    p("   1h candles | Score-based entry | TP 3% / SL 2%")
    p("   Capital: $30 | Comisiones: 0.1%")
    p("="*80)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    
    # Monedas a testear (las top del scanner que llevan 2+ años en Binance)
    coins = [
        'DOGE/USDT', 'XRP/USDT', 'ADA/USDT', 'GALA/USDT',
        'CHZ/USDT', 'JASMY/USDT', 'MBOX/USDT', 'ANKR/USDT',
        'FLOKI/USDT', 'COS/USDT',
    ]
    
    all_results = []
    
    for coin in coins:
        p(f"\n{'='*60}")
        p(f"📊 {coin}")
        p(f"{'='*60}")
        
        p(f"   📥 Descargando 2 años de datos...")
        df = download(ex, coin, (2023, 3, 1), (2025, 3, 8, 23, 59))
        
        if len(df) < 100:
            p(f"   ⚠️ Datos insuficientes ({len(df)} velas)")
            continue
        
        days = (df.index[-1] - df.index[0]).days or 1
        bh_pct = (df.iloc[-1]['close'] / df.iloc[0]['close'] - 1) * 100
        bh_pnl = 30 * bh_pct / 100
        
        p(f"   ✅ {len(df)} velas | {days} días")
        p(f"   Precio: ${df.iloc[0]['close']:.6f} → ${df.iloc[-1]['close']:.6f} ({bh_pct:+.1f}%)")
        
        p(f"   🔧 Calculando scores...")
        scores = compute_scores(df)
        high_scores = sum(1 for s in scores if s >= 65)
        p(f"   Señales score≥65: {high_scores} ({high_scores/days:.1f}/día)")
        
        # Test con diferentes configs
        p(f"\n   {'Config':<25s} | {'PnL':>8s} | {'#T':>4s} | {'WR':>4s} | {'DD':>5s} | "
          f"{'$/d':>6s} | {'$/m':>6s}")
        p(f"   {'-'*25}-+-{'-'*8}-+-{'-'*4}-+-{'-'*4}-+-{'-'*5}-+-{'-'*6}-+-{'-'*6}")
        
        best = None
        for min_sc in [50, 55, 60, 65, 70]:
            for tp, sl in [(3.0, 2.0), (5.0, 2.0), (3.0, 1.5)]:
                trades, bal, mdd, dpnl = simulate(
                    df, scores, tp_pct=tp, sl_pct=sl,
                    min_score=min_sc, cooldown=6)
                
                w = len([t for t in trades if t['pnl'] > 0])
                n = len(trades)
                pnl = bal - 30
                wr = w / max(n, 1) * 100
                daily = pnl / days
                monthly = daily * 30
                
                if best is None or pnl > best['pnl']:
                    best = {'pnl': pnl, 'config': f"SC{min_sc} TP{tp}/SL{sl}",
                            'trades': trades, 'wr': wr, 'n': n, 'mdd': mdd,
                            'daily': daily, 'monthly': monthly, 'dpnl': dpnl}
                
                e = '🟢' if pnl > 0 else '🔴'
                lbl = f"SC≥{min_sc} TP{tp}/SL{sl}"
                p(f"   {lbl:<25s} | {e}${pnl:+7.2f} | {n:4d} | {wr:3.0f}% | "
                  f"{mdd:4.1f}% | ${daily:+.2f} | ${monthly:+.1f}")
        
        # Resumen mejor config
        if best and best['n'] > 0:
            p(f"\n   🏆 MEJOR: {best['config']}")
            p(f"      PnL: ${best['pnl']:+.2f} | {best['n']} trades | WR: {best['wr']:.0f}%")
            p(f"      $/día: ${best['daily']:.2f} | $/mes: ${best['monthly']:.1f}")
            p(f"      Max DD: {best['mdd']:.1f}%")
            p(f"   📊 B&H: ${bh_pnl:+.2f} ({bh_pct:+.1f}%)")
            
            # Días ganadores vs perdedores
            if best['dpnl']:
                wd = sum(1 for v in best['dpnl'].values() if v > 0)
                ld = sum(1 for v in best['dpnl'].values() if v < 0)
                p(f"   📅 Días: {wd} ganadores / {ld} perdedores")
        
        all_results.append({
            'coin': coin, 'best': best, 'bh_pnl': bh_pnl, 'bh_pct': bh_pct, 'days': days
        })
        
        time.sleep(0.5)
    
    # ═══════════════════════════════════════════════════
    # RESUMEN GLOBAL
    # ═══════════════════════════════════════════════════
    p(f"\n{'='*80}")
    p(f"📋 RESUMEN GLOBAL — 2 años, {len(all_results)} monedas")
    p(f"{'='*80}")
    
    total_pnl = 0
    total_bh = 0
    
    p(f"{'Moneda':<15s} | {'Mejor Config':<20s} | {'PnL':>8s} | {'#T':>4s} | {'WR':>4s} | "
      f"{'$/día':>6s} | {'B&H':>8s}")
    p(f"{'-'*15}-+-{'-'*20}-+-{'-'*8}-+-{'-'*4}-+-{'-'*4}-+-{'-'*6}-+-{'-'*8}")
    
    for r in sorted(all_results, key=lambda x: -(x['best']['pnl'] if x['best'] else -999)):
        b = r['best']
        if b:
            e = '🟢' if b['pnl'] > 0 else '🔴'
            p(f"{r['coin']:<15s} | {b['config']:<20s} | {e}${b['pnl']:+7.2f} | {b['n']:4d} | "
              f"{b['wr']:3.0f}% | ${b['daily']:+.2f} | ${r['bh_pnl']:+7.2f}")
            total_pnl += b['pnl']
            total_bh += r['bh_pnl']
    
    p(f"\n   💰 Total estrategia (todas): ${total_pnl:+.2f}")
    p(f"   📊 Total Buy & Hold (todas): ${total_bh:+.2f}")
    p(f"   📊 Operando 1 moneda a la vez con $30: promedio ${total_pnl/max(len(all_results),1):+.2f}")
    
    p(f"\n{'='*80}")

if __name__ == '__main__':
    main()

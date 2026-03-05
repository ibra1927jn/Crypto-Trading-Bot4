"""
CT4 LAB — SIMULACIÓN HÍBRIDA: Bollinger Bounce + Grid Bot
============================================================
Simula el combo completo:
  - ADX > 20 → Bollinger Bounce (francotirador)
  - ADX < 15 → Grid Bot (pescador)
  - 15-20    → Zona gris (Grid mantiene, BB evalúa)

Compara:
  A. Solo Bollinger Bounce
  B. Solo Grid Bot
  C. HÍBRIDO (BB + Grid con switching ADX)

Datos: Máximo disponible en Binance Testnet (~23 días).
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

def calc(df):
    c, h, lo = df['close'], df['high'], df['low']
    df['EMA9'] = c.ewm(span=9).mean()
    df['EMA21'] = c.ewm(span=21).mean()
    df['EMA50'] = c.ewm(span=50).mean()
    df['EMA200'] = c.ewm(span=200).mean()
    d = c.diff()
    g = d.where(d > 0, 0).rolling(14).mean()
    l = (-d.where(d < 0, 0)).rolling(14).mean()
    rs = g / l.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    tr = pd.concat([h - lo, abs(h - c.shift(1)), abs(lo - c.shift(1))], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    pdm = h.diff().where(lambda x: (x > 0) & (x > -lo.diff()), 0)
    mdm = (-lo.diff()).where(lambda x: (x > 0) & (x > h.diff()), 0)
    pdi = 100 * (pdm.rolling(14).mean() / df['ATR'])
    mdi = 100 * (mdm.rolling(14).mean() / df['ATR'])
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    df['ADX'] = dx.rolling(14).mean()
    df['VSMA'] = df['volume'].rolling(20).mean()
    bb_mid = c.rolling(20).mean()
    bs = c.rolling(20).std()
    df['BB_MID'] = bb_mid
    df['BB_LO'] = bb_mid - 2 * bs
    df['BB_HI'] = bb_mid + 2 * bs
    df['BB_PCT'] = (c - df['BB_LO']) / (df['BB_HI'] - df['BB_LO'] + 1e-10)
    return df

def v(r, c, d=0):
    x = r.get(c, d)
    return d if pd.isna(x) else x

# ═══════════════════════════════════════════
# BOLLINGER BOUNCE (idéntica a producción)
# ═══════════════════════════════════════════
def backtest_bollinger(df, capital=10000):
    cap = capital; peak = capital; dd = 0; pos = None; trades = []
    for i in range(202, len(df) - 1):
        r, p1 = df.iloc[i], df.iloc[i - 1]
        if pos is None:
            bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50)
            prsi = v(p1, 'RSI', 50); adx = v(r, 'ADX')
            macro = r['close'] > v(r, 'EMA200') * 0.99
            if bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro:
                atr = v(r, 'ATR', 100)
                sz = min(cap * 0.30 / r['close'], cap * 0.30 / r['close'])
                pos = {'e': r['close'], 'sl': r['close'] - 1.5 * atr,
                       'tp': r['close'] + 3.0 * atr, 'sz': sz, 'b': i, 'pk': r['close']}
        else:
            p = r['close']; pos['pk'] = max(pos['pk'], p)
            if p > pos['e'] * 1.005:
                pos['sl'] = max(pos['sl'], p - 1.0 * v(r, 'ATR', 100))
            pnl = None
            if p <= pos['sl']: pnl = (pos['sl'] - pos['e']) * pos['sz']
            elif p >= pos['tp']: pnl = (pos['tp'] - pos['e']) * pos['sz']
            elif v(r, 'BB_PCT') > 0.95: pnl = (p - pos['e']) * pos['sz']
            elif (v(p1, 'EMA9') >= v(p1, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21')):
                pnl = (p - pos['e']) * pos['sz']
            elif p < v(r, 'EMA200') * 0.985:
                pnl = (p - pos['e']) * pos['sz']
            if pnl is not None:
                cap += pnl; peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl, 'bars': i - pos['b']})
                pos = None
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    return {
        'n': len(trades), 'w': len(w), 'l': len(lo),
        'wr': len(w) / len(trades) * 100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
    }

# ═══════════════════════════════════════════
# GRID BOT
# ═══════════════════════════════════════════
def backtest_grid(df, capital=10000, grid_pct=0.3, num_levels=5, 
                  max_alloc=0.30, only_low_adx=False, adx_off=20):
    """
    Simula un Grid Bot.
    
    Parámetros:
      grid_pct:    Distancia entre niveles (% del precio central)
      num_levels:  Número de niveles de compra debajo del precio
      max_alloc:   % máximo del capital para Grid
      only_low_adx: Si True, solo opera cuando ADX < adx_off
    """
    cap = capital; peak = capital; dd = 0
    grid_active = False; grid_center = 0; grid_orders = []
    trades = []; total_roundtrips = 0
    fee = 0.001  # 0.1% por trade (Binance spot)
    
    candles_in_grid = 0; candles_total = 0
    
    for i in range(202, len(df) - 1):
        r = df.iloc[i]
        p = r['close']
        adx = v(r, 'ADX')
        candles_total += 1
        
        # ─── Decidir si Grid debe estar activo ───
        should_grid = True
        if only_low_adx and adx >= adx_off:
            should_grid = False
        
        # ─── Activar/Desactivar Grid ───
        if should_grid and not grid_active:
            # Crear nueva cuadrícula centrada en precio actual
            grid_center = p
            grid_alloc = cap * max_alloc  # Capital asignado al grid
            per_level = grid_alloc / num_levels
            grid_orders = []
            for lv in range(1, num_levels + 1):
                buy_price = grid_center * (1 - grid_pct / 100 * lv)
                sell_price = grid_center * (1 + grid_pct / 100 * lv)
                qty_buy = per_level / buy_price
                grid_orders.append({
                    'buy': buy_price, 'sell': sell_price,
                    'qty': qty_buy, 'filled_buy': False, 'filled_sell': False
                })
            grid_active = True
        
        elif not should_grid and grid_active:
            # Cerrar grid — cancelar pendientes, vender holdings al mercado
            for order in grid_orders:
                if order['filled_buy'] and not order['filled_sell']:
                    # Tenemos BTC comprado, vender al precio actual
                    pnl = (p - order['buy']) * order['qty']
                    pnl -= order['buy'] * order['qty'] * fee  # fee compra
                    pnl -= p * order['qty'] * fee             # fee venta
                    cap += pnl
                    trades.append({'pnl': pnl, 'type': 'grid_close'})
            grid_orders = []
            grid_active = False
        
        if not grid_active:
            continue
            
        candles_in_grid += 1
        
        # ─── Ejecutar Grid ───
        for order in grid_orders:
            # Check buy fills
            if not order['filled_buy'] and p <= order['buy']:
                order['filled_buy'] = True
            
            # Check sell fills (roundtrip complete)
            if order['filled_buy'] and not order['filled_sell'] and p >= order['sell']:
                order['filled_sell'] = True
                pnl = (order['sell'] - order['buy']) * order['qty']
                pnl -= order['buy'] * order['qty'] * fee
                pnl -= order['sell'] * order['qty'] * fee
                cap += pnl
                peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl, 'type': 'roundtrip'})
                total_roundtrips += 1
                
                # Reset this level for new roundtrip
                order['filled_buy'] = False
                order['filled_sell'] = False
        
        # ─── Grid Range Protection ───
        # Si el precio se aleja >3% del centro, recalcular grid
        if abs(p - grid_center) / grid_center > 0.03:
            # Cerrar posiciones abiertas
            for order in grid_orders:
                if order['filled_buy'] and not order['filled_sell']:
                    pnl = (p - order['buy']) * order['qty']
                    pnl -= order['buy'] * order['qty'] * fee
                    pnl -= p * order['qty'] * fee
                    cap += pnl
                    trades.append({'pnl': pnl, 'type': 'rebalance'})
            
            # Recalcular grid en nuevo centro
            grid_center = p
            grid_alloc = cap * max_alloc
            per_level = grid_alloc / num_levels
            grid_orders = []
            for lv in range(1, num_levels + 1):
                buy_price = grid_center * (1 - grid_pct / 100 * lv)
                sell_price = grid_center * (1 + grid_pct / 100 * lv)
                qty_buy = per_level / buy_price
                grid_orders.append({
                    'buy': buy_price, 'sell': sell_price,
                    'qty': qty_buy, 'filled_buy': False, 'filled_sell': False
                })
            peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
    
    # End: close remaining
    if grid_active:
        p = df.iloc[-1]['close']
        for order in grid_orders:
            if order['filled_buy'] and not order['filled_sell']:
                pnl = (p - order['buy']) * order['qty']
                pnl -= order['buy'] * order['qty'] * fee
                pnl -= p * order['qty'] * fee
                cap += pnl
                trades.append({'pnl': pnl, 'type': 'final_close'})
    
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    roundtrips = [t for t in trades if t.get('type') == 'roundtrip']
    
    return {
        'n': len(trades), 'w': len(w), 'l': len(lo),
        'roundtrips': len(roundtrips),
        'wr': len(w) / len(trades) * 100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
        'coverage': candles_in_grid / candles_total * 100 if candles_total else 0,
    }

# ═══════════════════════════════════════════
# HYBRID: BB + Grid con ADX switching
# ═══════════════════════════════════════════
def backtest_hybrid(df, capital=10000, grid_pct=0.3, num_levels=5):
    """
    El bot inteligente:
      ADX < 15  → Solo Grid
      ADX 15-20 → Grid mantiene + BB evalúa
      ADX > 20  → Solo BB (Grid se cierra)
    
    Capital split: 30% para el modo activo.
    """
    cap = capital; peak = capital; dd = 0
    fee = 0.001
    
    # BB state
    bb_pos = None; bb_trades = []
    # Grid state
    grid_active = False; grid_center = 0; grid_orders = []
    grid_trades = []
    
    mode_time = {'grid': 0, 'bb': 0, 'both': 0}
    
    for i in range(202, len(df) - 1):
        r, p1 = df.iloc[i], df.iloc[i - 1]
        p = r['close']
        adx = v(r, 'ADX')
        
        # ─── MODE SELECTION ───
        if adx < 15:
            mode = 'grid'
        elif adx < 20:
            mode = 'both'
        else:
            mode = 'bb'
        mode_time[mode] += 1
        
        # ─── GRID LOGIC ───
        if mode in ('grid', 'both'):
            if not grid_active:
                grid_center = p
                grid_alloc = cap * 0.30
                per_level = grid_alloc / num_levels
                grid_orders = []
                for lv in range(1, num_levels + 1):
                    bp = grid_center * (1 - grid_pct / 100 * lv)
                    sp = grid_center * (1 + grid_pct / 100 * lv)
                    grid_orders.append({
                        'buy': bp, 'sell': sp,
                        'qty': per_level / bp,
                        'filled_buy': False, 'filled_sell': False
                    })
                grid_active = True
            
            for order in grid_orders:
                if not order['filled_buy'] and p <= order['buy']:
                    order['filled_buy'] = True
                if order['filled_buy'] and not order['filled_sell'] and p >= order['sell']:
                    order['filled_sell'] = True
                    pnl = (order['sell'] - order['buy']) * order['qty']
                    pnl -= order['buy'] * order['qty'] * fee
                    pnl -= order['sell'] * order['qty'] * fee
                    cap += pnl; peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                    grid_trades.append({'pnl': pnl})
                    order['filled_buy'] = False
                    order['filled_sell'] = False
            
            # Rebalance if price drifts
            if abs(p - grid_center) / grid_center > 0.03:
                for order in grid_orders:
                    if order['filled_buy'] and not order['filled_sell']:
                        pnl = (p - order['buy']) * order['qty']
                        pnl -= order['buy'] * order['qty'] * fee * 2
                        cap += pnl
                        grid_trades.append({'pnl': pnl})
                grid_center = p
                grid_alloc = cap * 0.30
                per_level = grid_alloc / num_levels
                grid_orders = []
                for lv in range(1, num_levels + 1):
                    bp = grid_center * (1 - grid_pct / 100 * lv)
                    sp = grid_center * (1 + grid_pct / 100 * lv)
                    grid_orders.append({
                        'buy': bp, 'sell': sp, 'qty': per_level / bp,
                        'filled_buy': False, 'filled_sell': False
                    })
                peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
        
        elif mode == 'bb' and grid_active:
            # Close grid
            for order in grid_orders:
                if order['filled_buy'] and not order['filled_sell']:
                    pnl = (p - order['buy']) * order['qty']
                    pnl -= order['buy'] * order['qty'] * fee * 2
                    cap += pnl
                    grid_trades.append({'pnl': pnl})
            grid_orders = []
            grid_active = False
        
        # ─── BOLLINGER BOUNCE LOGIC ───
        if mode in ('bb', 'both'):
            if bb_pos is None:
                bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50)
                prsi = v(p1, 'RSI', 50); macro = p > v(r, 'EMA200') * 0.99
                if bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro:
                    atr = v(r, 'ATR', 100)
                    # Capital disponible (menos lo que usa Grid si está activo)
                    avail = cap * 0.30
                    sz = avail / p
                    bb_pos = {'e': p, 'sl': p - 1.5 * atr,
                              'tp': p + 3.0 * atr, 'sz': sz, 'b': i, 'pk': p}
            else:
                bb_pos['pk'] = max(bb_pos['pk'], p)
                if p > bb_pos['e'] * 1.005:
                    bb_pos['sl'] = max(bb_pos['sl'], p - 1.0 * v(r, 'ATR', 100))
                pnl = None
                if p <= bb_pos['sl']: pnl = (bb_pos['sl'] - bb_pos['e']) * bb_pos['sz']
                elif p >= bb_pos['tp']: pnl = (bb_pos['tp'] - bb_pos['e']) * bb_pos['sz']
                elif v(r, 'BB_PCT') > 0.95: pnl = (p - bb_pos['e']) * bb_pos['sz']
                elif (v(p1, 'EMA9') >= v(p1, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21')):
                    pnl = (p - bb_pos['e']) * bb_pos['sz']
                elif p < v(r, 'EMA200') * 0.985:
                    pnl = (p - bb_pos['e']) * bb_pos['sz']
                if pnl is not None:
                    cap += pnl; peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                    bb_trades.append({'pnl': pnl})
                    bb_pos = None
    
    # Close remaining
    if bb_pos:
        pnl = (df.iloc[-1]['close'] - bb_pos['e']) * bb_pos['sz']
        cap += pnl; bb_trades.append({'pnl': pnl})
    if grid_active:
        p = df.iloc[-1]['close']
        for order in grid_orders:
            if order['filled_buy'] and not order['filled_sell']:
                pnl = (p - order['buy']) * order['qty']
                pnl -= order['buy'] * order['qty'] * fee * 2
                cap += pnl; grid_trades.append({'pnl': pnl})
    
    all_trades = bb_trades + grid_trades
    w = [t for t in all_trades if t['pnl'] > 0]
    lo = [t for t in all_trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    total_candles = sum(mode_time.values())
    
    return {
        'n': len(all_trades), 'w': len(w), 'l': len(lo),
        'bb_trades': len(bb_trades), 'grid_trades': len(grid_trades),
        'wr': len(w) / len(all_trades) * 100 if all_trades else 0,
        'pnl': sum(t['pnl'] for t in all_trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
        'bb_pnl': sum(t['pnl'] for t in bb_trades),
        'grid_pnl': sum(t['pnl'] for t in grid_trades),
        'mode_grid_pct': mode_time['grid'] / total_candles * 100 if total_candles else 0,
        'mode_bb_pct': mode_time['bb'] / total_candles * 100 if total_candles else 0,
        'mode_both_pct': mode_time['both'] / total_candles * 100 if total_candles else 0,
    }


async def main():
    print("=" * 80)
    print("🔬 CT4 LAB — SIMULACIÓN HÍBRIDA: Bollinger + Grid Bot")
    print("=" * 80)

    exchange = ccxt.binance({'sandbox': True})
    
    all_candles = []
    since = int(datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(2026, 3, 5, 6, 0, tzinfo=timezone.utc).timestamp() * 1000)
    
    while since < end_ts:
        try:
            candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', since=since, limit=1000)
            if not candles: break
            all_candles.extend(candles)
            since = candles[-1][0] + 1
            await asyncio.sleep(0.3)
        except: break
    
    await exchange.close()

    seen = set(); unique = []
    for c in all_candles:
        if c[0] not in seen: seen.add(c[0]); unique.append(c)
    unique.sort(key=lambda x: x[0])

    df = pd.DataFrame(unique, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc(df)
    
    total_days = len(df) * 5 / 60 / 24
    
    # Market phases
    low_adx = (df['ADX'] < 15).sum()
    mid_adx = ((df['ADX'] >= 15) & (df['ADX'] < 20)).sum()
    hi_adx = (df['ADX'] >= 20).sum()
    total = len(df)
    
    print(f"\n  📊 Data: {len(df)} velas ({total_days:.0f} días)")
    print(f"  Rango: {df.index[0].strftime('%m/%d')} → {df.index[-1].strftime('%m/%d')}")
    print(f"  Precio: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    
    print(f"\n  ⏱️  Distribución ADX del mercado:")
    print(f"     ADX < 15  (Grid):   {low_adx:>5} velas ({low_adx/total*100:>4.0f}%) {'█' * int(low_adx/total*40)}")
    print(f"     ADX 15-20 (Ambos):  {mid_adx:>5} velas ({mid_adx/total*100:>4.0f}%) {'█' * int(mid_adx/total*40)}")
    print(f"     ADX > 20  (BB):     {hi_adx:>5} velas ({hi_adx/total*100:>4.0f}%) {'█' * int(hi_adx/total*40)}")

    # ═══ RUN TESTS ═══
    print(f"\n{'=' * 80}")
    print(f"🧪 RESULTADOS")
    print(f"{'=' * 80}")
    
    # A. Solo Bollinger Bounce
    bb = backtest_bollinger(df)
    print(f"\n  A. SOLO BOLLINGER BOUNCE")
    print(f"     PnL: ${bb['pnl']:>+8.2f} | Trades: {bb['n']:>3} | WR: {bb['wr']:.0f}% | DD: {bb['dd']:.1f}% | PF: {bb['pf']:.1f}")
    
    # B. Solo Grid Bot (siempre activo)
    gr_always = backtest_grid(df, grid_pct=0.3, num_levels=5, only_low_adx=False)
    print(f"\n  B. SOLO GRID BOT (siempre activo)")
    print(f"     PnL: ${gr_always['pnl']:>+8.2f} | Trades: {gr_always['n']:>3} ({gr_always['roundtrips']} roundtrips) | WR: {gr_always['wr']:.0f}% | DD: {gr_always['dd']:.1f}%")
    print(f"     Cobertura: {gr_always['coverage']:.0f}% del tiempo")
    
    # C. Solo Grid Bot (solo ADX < 20)
    gr_low = backtest_grid(df, grid_pct=0.3, num_levels=5, only_low_adx=True, adx_off=20)
    print(f"\n  C. SOLO GRID BOT (solo ADX < 20)")
    print(f"     PnL: ${gr_low['pnl']:>+8.2f} | Trades: {gr_low['n']:>3} ({gr_low['roundtrips']} roundtrips) | WR: {gr_low['wr']:.0f}% | DD: {gr_low['dd']:.1f}%")
    print(f"     Cobertura: {gr_low['coverage']:.0f}% del tiempo")
    
    # D. HYBRID
    hybrid = backtest_hybrid(df, grid_pct=0.3, num_levels=5)
    print(f"\n  D. 🏆 HÍBRIDO (BB + Grid + ADX Switch)")
    print(f"     PnL TOTAL: ${hybrid['pnl']:>+8.2f} | Trades: {hybrid['n']:>3} | WR: {hybrid['wr']:.0f}% | DD: {hybrid['dd']:.1f}% | PF: {hybrid['pf']:.1f}")
    print(f"     ├─ Bollinger: ${hybrid['bb_pnl']:>+8.2f} ({hybrid['bb_trades']} trades)")
    print(f"     └─ Grid:      ${hybrid['grid_pnl']:>+8.2f} ({hybrid['grid_trades']} trades)")
    print(f"     Modos: Grid={hybrid['mode_grid_pct']:.0f}% | BB={hybrid['mode_bb_pct']:.0f}% | Ambos={hybrid['mode_both_pct']:.0f}%")

    # Grid parameter sweep
    print(f"\n{'=' * 80}")
    print(f"🔧 OPTIMIZACIÓN GRID (solo ADX < 20)")
    print(f"{'=' * 80}")
    print(f"   {'Grid%':>5} {'Levels':>6} {'PnL':>10} {'Trades':>6} {'RT':>4} {'WR':>5} {'DD':>5}")
    print(f"   {'-'*50}")
    for gp in [0.2, 0.3, 0.5, 0.8, 1.0]:
        for nl in [3, 5, 8]:
            r = backtest_grid(df, grid_pct=gp, num_levels=nl, only_low_adx=True, adx_off=20)
            if r['n'] > 0:
                print(f"   {gp:>5.1f}% {nl:>6} ${r['pnl']:>+8.2f} {r['n']:>6} {r['roundtrips']:>4} {r['wr']:>4.0f}% {r['dd']:>4.1f}%")

    # ═══ COMPARISON ═══
    print(f"\n{'=' * 80}")
    print(f"⚖️  VEREDICTO FINAL")
    print(f"{'=' * 80}")
    results = [
        ("A. Solo Bollinger",  bb['pnl'], bb['dd'], bb['n']),
        ("B. Solo Grid",       gr_always['pnl'], gr_always['dd'], gr_always['n']),
        ("C. Grid (ADX<20)",   gr_low['pnl'], gr_low['dd'], gr_low['n']),
        ("D. HÍBRIDO BB+Grid", hybrid['pnl'], hybrid['dd'], hybrid['n']),
    ]
    results.sort(key=lambda x: -x[1])
    medals = ["🥇", "🥈", "🥉", "4."]
    for i, (name, pnl, dd, n) in enumerate(results):
        e = "🟢" if pnl > 0 else "🔴"
        bar = "█" * max(1, int(max(0, pnl) / 10))
        print(f"  {medals[i]} {e} {name:<22} ${pnl:>+8.2f} | DD {dd:.1f}% | {n} trades  {bar}")
    
    print(f"\n  📊 El híbrido cubrió:")
    print(f"     Grid mode: {hybrid['mode_grid_pct']:.0f}% del tiempo")
    print(f"     BB mode:   {hybrid['mode_bb_pct']:.0f}% del tiempo")
    print(f"     Overlap:   {hybrid['mode_both_pct']:.0f}% del tiempo")
    print(f"     TOTAL:     {hybrid['mode_grid_pct'] + hybrid['mode_bb_pct'] + hybrid['mode_both_pct']:.0f}%")

if __name__ == "__main__":
    asyncio.run(main())

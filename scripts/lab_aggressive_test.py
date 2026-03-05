"""
CT4 LAB — ESTRATEGIAS AGRESIVAS PARA DEX ($100)
==================================================
Nuevas reglas del juego:
  - Tokens volátiles (SOL, DOGE como proxy de memecoins)
  - Position size: 80% (no 30%)
  - Fees DEX: 0.05% (Jupiter) vs 0.1% (Binance)
  - SL: -3% máximo | TP: +5-8%
  - Timeframes: 5m y 1m

Estrategias diseñadas para VOLATILIDAD:
  1. Momentum Burst — Explosión de precio + volumen
  2. Breakout Agresivo — Nuevos máximos locales
  3. RSI Extreme — RSI < 20, rebote rápido
  4. Volume Spike — Volumen 3x + precio subiendo
  5. EMA Fast Cross — EMA5 cruza EMA13
  6. BB Agresivo — BB < 0.05, trade grande
  7. MACD Fast — MACD cruce en timeframe rápido
  8. Stoch Extreme — Stochastic < 10, explosión
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

CAPITAL = 100
POS_PCT = 0.80  # 80% del capital por trade
FEE_DEX = 0.0005  # 0.05% Jupiter
FEE_CEX = 0.001   # 0.1% Binance

def calc(df):
    c, h, lo = df['close'], df['high'], df['low']
    df['EMA5'] = c.ewm(span=5).mean()
    df['EMA9'] = c.ewm(span=9).mean()
    df['EMA13'] = c.ewm(span=13).mean()
    df['EMA21'] = c.ewm(span=21).mean()
    df['EMA50'] = c.ewm(span=50).mean()
    df['EMA200'] = c.ewm(span=200).mean()
    d = c.diff()
    g = d.where(d > 0, 0).rolling(14).mean()
    l = (-d.where(d < 0, 0)).rolling(14).mean()
    rs = g / l.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI_FAST'] = 100 - (100 / (1 + d.where(d>0,0).rolling(7).mean() / (-d.where(d<0,0)).rolling(7).mean().replace(0, np.nan)))
    tr = pd.concat([h - lo, abs(h - c.shift(1)), abs(lo - c.shift(1))], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    df['ATR_PCT'] = df['ATR'] / c * 100
    pdm = h.diff().where(lambda x: (x > 0) & (x > -lo.diff()), 0)
    mdm = (-lo.diff()).where(lambda x: (x > 0) & (x > h.diff()), 0)
    pdi = 100 * (pdm.rolling(14).mean() / df['ATR'])
    mdi = 100 * (mdm.rolling(14).mean() / df['ATR'])
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    df['ADX'] = dx.rolling(14).mean()
    df['VSMA'] = df['volume'].rolling(20).mean()
    df['VOL_RATIO'] = df['volume'] / df['VSMA'].replace(0, 1)
    bb_mid = c.rolling(20).mean()
    bs = c.rolling(20).std()
    df['BB_LO'] = bb_mid - 2 * bs
    df['BB_HI'] = bb_mid + 2 * bs
    df['BB_PCT'] = (c - df['BB_LO']) / (df['BB_HI'] - df['BB_LO'] + 1e-10)
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_S'] = df['MACD'].ewm(span=9).mean()
    rsi = df['RSI']
    rr = rsi.rolling(14)
    df['SRSI'] = (rsi - rr.min()) / (rr.max() - rr.min() + 1e-10) * 100
    df['CANDLE_PCT'] = (c - df['open']) / df['open'] * 100
    df['HIGH_5'] = h.rolling(5).max()
    df['HIGH_10'] = h.rolling(10).max()
    return df

def v(r, c, d=0):
    x = r.get(c, d)
    return d if pd.isna(x) else x

def backtest(df, name, buy_fn, exit_fn, sl_pct=-3.0, tp_pct=6.0,
             pos_pct=POS_PCT, fee=FEE_DEX, trailing_pct=None):
    """Backtest agresivo: SL/TP por PORCENTAJE, no por ATR."""
    cap = CAPITAL; peak = CAPITAL; dd = 0; pos = None; trades = []
    for i in range(50, len(df) - 1):
        r, p1 = df.iloc[i], df.iloc[i - 1]
        p2 = df.iloc[i - 2] if i >= 2 else p1
        if pos is None:
            if buy_fn(r, p1, p2):
                alloc = cap * pos_pct
                if alloc < 5: continue
                sz = alloc / r['close']
                entry_fee = alloc * fee
                sl = r['close'] * (1 + sl_pct / 100)
                tp = r['close'] * (1 + tp_pct / 100)
                pos = {'e': r['close'], 'sl': sl, 'tp': tp, 'sz': sz,
                       'b': i, 'fee': entry_fee, 'pk': r['close']}
        else:
            p = r['close']
            pos['pk'] = max(pos['pk'], p)
            # Trailing stop
            if trailing_pct and p > pos['e'] * 1.01:
                trail_sl = pos['pk'] * (1 - trailing_pct / 100)
                pos['sl'] = max(pos['sl'], trail_sl)
            pnl = None
            if p <= pos['sl']:
                pnl = (pos['sl'] - pos['e']) * pos['sz']
            elif p >= pos['tp']:
                pnl = (pos['tp'] - pos['e']) * pos['sz']
            elif exit_fn(r, p1):
                pnl = (p - pos['e']) * pos['sz']
            if pnl is not None:
                exit_fee = abs(p * pos['sz'] * fee)
                pnl -= (pos['fee'] + exit_fee)
                cap += pnl; peak = max(peak, cap); dd = max(dd, (peak-cap)/peak*100)
                trades.append({'pnl': pnl, 'bars': i - pos['b'],
                               'pct': pnl / (pos['e'] * pos['sz']) * 100})
                pos = None
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']
        pnl -= pos['fee'] + abs(df.iloc[-1]['close'] * pos['sz'] * fee)
        cap += pnl; trades.append({'pnl': pnl, 'bars': 0, 'pct': 0})
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    mcl = 0; cur = 0
    for t in trades:
        if t['pnl'] <= 0: cur += 1; mcl = max(mcl, cur)
        else: cur = 0
    avg_bars = np.mean([t['bars'] for t in trades]) if trades else 0
    return {
        'name': name, 'n': len(trades), 'w': len(w), 'l': len(lo),
        'wr': len(w)/len(trades)*100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
        'mcl': mcl, 'avg_bars': avg_bars,
        'avg_pct': np.mean([t['pct'] for t in trades]) if trades else 0,
        'best': max(t['pnl'] for t in trades) if trades else 0,
        'worst': min(t['pnl'] for t in trades) if trades else 0,
    }

# ═══════════════════════════════════════════
# EXITS
# ═══════════════════════════════════════════
def exit_never(r, p): return False
def exit_ema_cross(r, p):
    return v(p, 'EMA5') >= v(p, 'EMA13') and v(r, 'EMA5') < v(r, 'EMA13')
def exit_rsi_high(r, p):
    return v(r, 'RSI') > 70
def exit_bb_high(r, p):
    return v(r, 'BB_PCT') > 0.90

# ═══════════════════════════════════════════
# ESTRATEGIAS AGRESIVAS
# ═══════════════════════════════════════════

# 1. MOMENTUM BURST — Gran vela + volumen
def buy_momentum_burst(r, p1, p2):
    candle = v(r, 'CANDLE_PCT')
    vol = v(r, 'VOL_RATIO', 1)
    trend = r['close'] > v(r, 'EMA21')
    return candle > 0.5 and vol > 2.0 and trend

# 2. BREAKOUT AGRESIVO — Precio rompe máximo de 10 velas
def buy_breakout(r, p1, p2):
    hi10 = v(p1, 'HIGH_10')
    vol = v(r, 'VOL_RATIO', 1)
    adx = v(r, 'ADX')
    return r['close'] > hi10 and vol > 1.5 and adx > 20

# 3. RSI EXTREME — RSI < 20, rebote inmediato
def buy_rsi_extreme(r, p1, p2):
    rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    trend = r['close'] > v(r, 'EMA50') * 0.97
    return prsi < 20 and rsi > prsi and trend

# 4. VOLUME SPIKE — Volumen 3x + precio verde
def buy_vol_spike(r, p1, p2):
    vol = v(r, 'VOL_RATIO', 1)
    green = r['close'] > r['open']
    trend = r['close'] > v(r, 'EMA21')
    rsi = v(r, 'RSI', 50)
    return vol > 3.0 and green and trend and rsi < 65

# 5. EMA FAST CROSS — EMA5 cruza arriba de EMA13
def buy_ema_fast(r, p1, p2):
    cross = v(p1, 'EMA5') < v(p1, 'EMA13') and v(r, 'EMA5') >= v(r, 'EMA13')
    adx = v(r, 'ADX')
    rsi = v(r, 'RSI', 50)
    return cross and adx > 15 and rsi < 60

# 6. BB AGRESIVO — BB < 0.05, buy the extreme dip
def buy_bb_aggressive(r, p1, p2):
    bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    trend = r['close'] > v(r, 'EMA50') * 0.97
    return bb < 0.05 and rsi > prsi and trend

# 7. MACD FAST — MACD cruce bullish
def buy_macd_fast(r, p1, p2):
    cross = v(p1, 'MACD') < v(p1, 'MACD_S') and v(r, 'MACD') >= v(r, 'MACD_S')
    rsi = v(r, 'RSI', 50)
    trend = r['close'] > v(r, 'EMA21')
    return cross and rsi < 55 and trend

# 8. STOCH EXTREME — Stochastic < 10, explosión
def buy_stoch_extreme(r, p1, p2):
    srsi = v(r, 'SRSI', 50); psrsi = v(p1, 'SRSI', 50)
    trend = r['close'] > v(r, 'EMA50') * 0.97
    return psrsi < 10 and srsi > psrsi and trend

# 9. COMBO KILLER — Momentum + BB bajo + Volume
def buy_combo(r, p1, p2):
    bb = v(r, 'BB_PCT', 0.5)
    vol = v(r, 'VOL_RATIO', 1)
    rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    green = r['close'] > r['open']
    trend = r['close'] > v(r, 'EMA50') * 0.98
    return bb < 0.20 and vol > 1.5 and rsi > prsi and green and trend

# 10. SNIPER — Todo alineado (menos trades, más precisión)
def buy_sniper(r, p1, p2):
    bb = v(r, 'BB_PCT', 0.5)
    vol = v(r, 'VOL_RATIO', 1)
    rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX')
    ema_up = v(r, 'EMA5') > v(r, 'EMA13') or (v(p1, 'EMA5') < v(p1, 'EMA13') and v(r, 'EMA5') >= v(r, 'EMA13'))
    trend = r['close'] > v(r, 'EMA50')
    return bb < 0.15 and vol > 1.8 and prsi < 30 and rsi > prsi and adx > 20 and trend


async def run_test(exchange, symbol, tf='5m'):
    all_candles = []
    since = int(datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(2026, 3, 5, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)
    while since < end_ts:
        try:
            candles = await exchange.fetch_ohlcv(symbol, tf, since=since, limit=1000)
            if not candles: break
            all_candles.extend(candles); since = candles[-1][0] + 1
            await asyncio.sleep(0.3)
        except: break
    seen = set(); unique = []
    for c in all_candles:
        if c[0] not in seen: seen.add(c[0]); unique.append(c)
    unique.sort(key=lambda x: x[0])
    df = pd.DataFrame(unique, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return calc(df)

async def main():
    print("=" * 90)
    print(f"🔥 CT4 LAB — ESTRATEGIAS AGRESIVAS PARA DEX (${CAPITAL}, 80% position)")
    print("=" * 90)

    exchange = ccxt.binance({'sandbox': True})
    
    # Test on SOL (proxy for volatile Solana tokens) and DOGE (proxy for memecoins)
    test_coins = ['SOL/USDT', 'DOGE/USDT', 'BTC/USDT']
    
    for symbol in test_coins:
        print(f"\n{'=' * 90}")
        print(f"📊 {symbol} — Timeframe 5m")
        print(f"{'=' * 90}")
        
        df = await run_test(exchange, symbol, '5m')
        if df is None or len(df) < 100:
            print(f"  ❌ No hay datos para {symbol}")
            continue
        
        # Split 70/30
        cut = int(len(df) * 0.70)
        df_out = calc(df.iloc[max(0, cut-50):].copy())
        
        days = len(df) * 5 / 60 / 24
        vol = df['ATR_PCT'].dropna().mean()
        ret = (df.iloc[-1]['close'] - df.iloc[50]['close']) / df.iloc[50]['close'] * 100
        print(f"  {len(df)} velas ({days:.0f} días) | Volatilidad: {vol:.2f}%/vela | B&H: {ret:+.1f}%")
        
        configs = [
            ("01.Momentum Burst",  buy_momentum_burst, exit_ema_cross, -3, 6, 2.0),
            ("02.Breakout",        buy_breakout,        exit_ema_cross, -3, 8, None),
            ("03.RSI Extreme",     buy_rsi_extreme,     exit_rsi_high,  -3, 6, 2.0),
            ("04.Volume Spike",    buy_vol_spike,       exit_ema_cross, -2, 5, 1.5),
            ("05.EMA Fast Cross",  buy_ema_fast,        exit_ema_cross, -3, 6, 2.0),
            ("06.BB Agresivo",     buy_bb_aggressive,   exit_bb_high,   -3, 6, 2.0),
            ("07.MACD Fast",       buy_macd_fast,       exit_ema_cross, -3, 5, 2.0),
            ("08.Stoch Extreme",   buy_stoch_extreme,   exit_rsi_high,  -3, 6, 2.0),
            ("09.Combo Killer",    buy_combo,           exit_bb_high,   -2, 5, 1.5),
            ("10.Sniper",          buy_sniper,          exit_bb_high,   -2, 8, 2.0),
        ]
        
        # OUT-OF-SAMPLE
        print(f"\n  {'Estrategia':<22} {'T':>3} {'W':>2} {'L':>2} {'WR':>4} {'PnL':>9} {'DD':>5} {'PF':>5} "
              f"{'Best':>7} {'Worst':>7} {'Avg%':>6}")
        print("  " + "-" * 85)
        
        results = []
        for name, buy, exit_fn, sl, tp, trail in configs:
            r = backtest(df_out, name, buy, exit_fn, sl_pct=sl, tp_pct=tp,
                        fee=FEE_DEX, trailing_pct=trail)
            results.append(r)
            e = "🟢" if r['pnl'] > 0 else "🔴"
            pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
            print(f"  {e} {r['name']:<20} {r['n']:>3} {r['w']:>2} {r['l']:>2} {r['wr']:>3.0f}% "
                  f"${r['pnl']:>+7.2f} {r['dd']:>4.1f}% {pf:>5} "
                  f"${r['best']:>+5.2f} ${r['worst']:>+5.2f} {r['avg_pct']:>+5.1f}%")
        
        # Ranking for this coin
        ranked = sorted(results, key=lambda x: -x['pnl'])
        print(f"\n  🏆 Top 3 für {symbol}:")
        for i, r in enumerate(ranked[:3]):
            ret = r['pnl'] / CAPITAL * 100
            print(f"     {i+1}. {r['name']} → ${r['pnl']:>+.2f} ({ret:>+.1f}%) | WR {r['wr']:.0f}% | DD {r['dd']:.1f}%")

    # ═══ FEE COMPARISON ═══
    print(f"\n{'=' * 90}")
    print(f"💰 IMPACTO FEES: Jupiter (0.05%) vs Binance (0.1%)")
    print(f"{'=' * 90}")
    
    df_sol = await run_test(exchange, 'SOL/USDT', '5m')
    cut = int(len(df_sol) * 0.70)
    df_out = calc(df_sol.iloc[max(0, cut-50):].copy())
    
    print(f"  {'Estrategia':<22} {'Jupiter':>10} {'Binance':>10} {'Diff':>8}")
    print("  " + "-" * 52)
    for name, buy, exit_fn, sl, tp, trail in configs:
        r_dex = backtest(df_out, name, buy, exit_fn, sl, tp, fee=FEE_DEX, trailing_pct=trail)
        r_cex = backtest(df_out, name, buy, exit_fn, sl, tp, fee=FEE_CEX, trailing_pct=trail)
        diff = r_dex['pnl'] - r_cex['pnl']
        print(f"  {name:<22} ${r_dex['pnl']:>+7.2f} ${r_cex['pnl']:>+7.2f} ${diff:>+6.2f}")

    await exchange.close()
    
    print(f"\n{'=' * 90}")
    print(f"📌 NOTA: Estos datos son de SOL/DOGE en Binance Testnet.")
    print(f"   Los memecoins de Solana (BONK, WIF, JUP) son 5-10× más volátiles.")
    print(f"   Los resultados en Jupiter/Solana mainnet serán probablemente MEJORES")
    print(f"   porque hay más volatilidad y menos fees.")
    print(f"{'=' * 90}")

if __name__ == "__main__":
    asyncio.run(main())

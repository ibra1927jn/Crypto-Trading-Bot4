"""
CT4 LAB — MATRIX: Muchas Monedas × Mejores Estrategias
========================================================
Aprovechamos los $10,000 de testnet para mapear:
  - 15+ monedas disponibles en Binance Testnet
  - Las 5 mejores estrategias agresivas
  - $10,000 capital (datos limpios)
  - También simulamos con $100 para comparar
  - OOS ciego (últimos 7 días)

Objetivo: Encontrar las 3-4 mejores combinaciones moneda+estrategia.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

FEE = 0.0005  # Jupiter 0.05%

COINS = [
    'SOL/USDT', 'DOGE/USDT', 'BTC/USDT', 'ETH/USDT',
    'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'AVAX/USDT',
    'LINK/USDT', 'DOT/USDT', 'LTC/USDT', 'NEAR/USDT',
    'FIL/USDT', 'APT/USDT', 'ARB/USDT', 'OP/USDT',
    'ATOM/USDT', 'UNI/USDT', 'AAVE/USDT', 'INJ/USDT',
]

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
    df['CANDLE_PCT'] = (c - df['open']) / df['open'] * 100
    df['HIGH_10'] = h.rolling(10).max()
    return df

def v(r, c, d=0):
    x = r.get(c, d)
    return d if pd.isna(x) else x

def backtest(df, buy_fn, exit_fn, sl_pct, tp_pct, capital, pos_pct=0.80,
             trailing_pct=None):
    cap = capital; peak = capital; dd = 0; pos = None; trades = []
    for i in range(50, len(df) - 1):
        r, p1 = df.iloc[i], df.iloc[i - 1]
        p2 = df.iloc[i - 2] if i >= 2 else p1
        if pos is None:
            if buy_fn(r, p1, p2):
                alloc = cap * pos_pct
                if alloc < 5: continue
                sz = alloc / r['close']
                ef = alloc * FEE
                pos = {'e': r['close'], 'sl': r['close']*(1+sl_pct/100),
                       'tp': r['close']*(1+tp_pct/100), 'sz': sz,
                       'b': i, 'fee': ef, 'pk': r['close']}
        else:
            p = r['close']; pos['pk'] = max(pos['pk'], p)
            if trailing_pct and p > pos['e'] * 1.01:
                pos['sl'] = max(pos['sl'], pos['pk']*(1-trailing_pct/100))
            pnl = None
            if p <= pos['sl']: pnl = (pos['sl']-pos['e'])*pos['sz']
            elif p >= pos['tp']: pnl = (pos['tp']-pos['e'])*pos['sz']
            elif exit_fn(r, p1): pnl = (p-pos['e'])*pos['sz']
            if pnl is not None:
                pnl -= (pos['fee'] + abs(p*pos['sz']*FEE))
                cap += pnl; peak = max(peak, cap); dd = max(dd,(peak-cap)/peak*100)
                trades.append({'pnl': pnl})
                pos = None
    if pos:
        p = df.iloc[-1]['close']; pnl = (p-pos['e'])*pos['sz']
        pnl -= pos['fee'] + abs(p*pos['sz']*FEE)
        cap += pnl; trades.append({'pnl': pnl})
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    return {
        'n': len(trades), 'w': len(w),
        'wr': len(w)/len(trades)*100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w)/abs(gl) if gl != 0 else 999,
    }

# EXITS
def exit_ema(r, p):
    return v(p, 'EMA5') >= v(p, 'EMA13') and v(r, 'EMA5') < v(r, 'EMA13')
def exit_bb(r, p):
    return v(r, 'BB_PCT') > 0.90

# 5 BEST STRATEGIES
def buy_combo(r, p1, p2):
    return (v(r,'BB_PCT',0.5) < 0.20 and v(r,'VOL_RATIO',1) > 1.5 and
            v(r,'RSI',50) > v(p1,'RSI',50) and r['close'] > r['open'] and
            r['close'] > v(r,'EMA50')*0.98)

def buy_momentum(r, p1, p2):
    return (v(r,'CANDLE_PCT') > 0.5 and v(r,'VOL_RATIO',1) > 2.0 and
            r['close'] > v(r,'EMA21'))

def buy_breakout(r, p1, p2):
    return (r['close'] > v(p1,'HIGH_10') and v(r,'VOL_RATIO',1) > 1.5 and
            v(r,'ADX') > 20)

def buy_macd(r, p1, p2):
    return (v(p1,'MACD') < v(p1,'MACD_S') and v(r,'MACD') >= v(r,'MACD_S') and
            v(r,'RSI',50) < 55 and r['close'] > v(r,'EMA21'))

def buy_bb_aggressive(r, p1, p2):
    return (v(r,'BB_PCT',0.5) < 0.05 and v(r,'RSI',50) > v(p1,'RSI',50) and
            r['close'] > v(r,'EMA50')*0.97)

STRATEGIES = [
    ("Combo",     buy_combo,      exit_bb,  -2, 5, 1.5),
    ("Momentum",  buy_momentum,   exit_ema, -3, 6, 2.0),
    ("Breakout",  buy_breakout,   exit_ema, -3, 8, None),
    ("MACD",      buy_macd,       exit_ema, -3, 5, 2.0),
    ("BB Agres",  buy_bb_aggressive, exit_bb, -3, 6, 2.0),
]


async def main():
    print("=" * 100)
    print("🗺️  CT4 LAB — MATRIX: Monedas × Estrategias (OOS 7 días)")
    print("=" * 100)

    exchange = ccxt.binance({'sandbox': True})
    
    # Download all coins
    coin_data = {}
    for symbol in COINS:
        print(f"  📡 {symbol}...", end=" ", flush=True)
        all_candles = []
        since = int(datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        end_ts = int(datetime(2026, 3, 5, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)
        try:
            while since < end_ts:
                candles = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=1000)
                if not candles: break
                all_candles.extend(candles); since = candles[-1][0] + 1
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"❌ {e}"); continue
        if len(all_candles) < 300:
            print(f"⚠️ {len(all_candles)} velas"); continue
        seen = set(); unique = []
        for c in all_candles:
            if c[0] not in seen: seen.add(c[0]); unique.append(c)
        unique.sort(key=lambda x: x[0])
        df = pd.DataFrame(unique, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = calc(df)
        coin_data[symbol] = df
        vol = df['ATR_PCT'].dropna().mean()
        print(f"✅ {len(df)} velas | Vol: {vol:.2f}%")
    
    await exchange.close()

    # ═══ MARKET OVERVIEW ═══
    print(f"\n{'=' * 100}")
    print(f"📊 PERFIL DE CADA MONEDA (23 días)")
    print(f"{'=' * 100}")
    print(f"  {'Moneda':<12} {'Precio':>10} {'B&H':>7} {'Vol%':>5} {'Rango/día':>9} {'BB<20%':>6}")
    print("  " + "-" * 55)
    
    profiles = []
    for sym, df in coin_data.items():
        ret = (df.iloc[-1]['close'] - df.iloc[50]['close'])/df.iloc[50]['close']*100
        vol = df['ATR_PCT'].dropna().mean()
        daily_r = ((df['high']-df['low'])/df['close']).mean()*100
        bb_low = (df['BB_PCT'].dropna() < 0.20).sum()/len(df)*100
        profiles.append({'sym': sym, 'p': df.iloc[-1]['close'], 'ret': ret,
                         'vol': vol, 'dr': daily_r, 'bb': bb_low})
    
    profiles.sort(key=lambda x: -x['vol'])
    for p in profiles:
        fire = "🔥" if p['vol'] > 0.3 else "  "
        print(f"  {p['sym']:<12} ${p['p']:>8.2f} {p['ret']:>+5.1f}% {p['vol']:>4.2f}% "
              f"{p['dr']:>7.2f}% {p['bb']:>5.1f}% {fire}")

    # ═══ STRATEGY MATRIX — $10,000 ═══
    print(f"\n{'=' * 100}")
    print(f"🗺️  MATRIX $10,000 — OOS (últimos 7 días)")
    print(f"{'=' * 100}")
    
    strat_names = [s[0] for s in STRATEGIES]
    print(f"  {'Moneda':<12}", end="")
    for sn in strat_names:
        print(f" {sn:>10}", end="")
    print(f" {'MEJOR':>12}")
    print("  " + "-" * (12 + 11*len(strat_names) + 13))
    
    matrix_10k = {}
    for sym, df in coin_data.items():
        cut = int(len(df) * 0.70)
        df_oos = calc(df.iloc[max(0,cut-50):].copy())
        
        row = {}
        print(f"  {sym:<12}", end="")
        best_pnl = -999; best_name = ""
        for name, buy, exit_fn, sl, tp, trail in STRATEGIES:
            r = backtest(df_oos, buy, exit_fn, sl, tp, capital=10000, trailing_pct=trail)
            row[name] = r
            e = "+" if r['pnl'] > 0 else " "
            print(f" {e}${r['pnl']:>+7.0f}", end="")
            if r['pnl'] > best_pnl: best_pnl = r['pnl']; best_name = name
        matrix_10k[sym] = row
        print(f"  → {best_name}")
    
    # ═══ STRATEGY MATRIX — $100 ═══
    print(f"\n{'=' * 100}")
    print(f"🗺️  MATRIX $100 — OOS (últimos 7 días)")
    print(f"{'=' * 100}")
    
    print(f"  {'Moneda':<12}", end="")
    for sn in strat_names:
        print(f" {sn:>10}", end="")
    print(f" {'MEJOR':>12}")
    print("  " + "-" * (12 + 11*len(strat_names) + 13))
    
    matrix_100 = {}
    all_combos = []
    for sym, df in coin_data.items():
        cut = int(len(df) * 0.70)
        df_oos = calc(df.iloc[max(0,cut-50):].copy())
        
        row = {}
        print(f"  {sym:<12}", end="")
        best_pnl = -999; best_name = ""
        for name, buy, exit_fn, sl, tp, trail in STRATEGIES:
            r = backtest(df_oos, buy, exit_fn, sl, tp, capital=100, trailing_pct=trail)
            r['symbol'] = sym; r['strategy'] = name
            row[name] = r
            all_combos.append(r)
            e = "+" if r['pnl'] > 0 else " "
            print(f" ${r['pnl']:>+7.2f}", end="")
            if r['pnl'] > best_pnl: best_pnl = r['pnl']; best_name = name
        matrix_100[sym] = row
        print(f"  → {best_name}")

    # ═══ BEST COMBINATIONS ═══
    print(f"\n{'=' * 100}")
    print(f"🏆 TOP 15 COMBINACIONES (Moneda + Estrategia) con $100")
    print(f"{'=' * 100}")
    all_combos.sort(key=lambda x: -x['pnl'])
    print(f"  {'#':>3} {'Moneda':<12} {'Estrategia':<12} {'PnL':>9} {'Ret%':>7} {'Trades':>6} {'WR':>5} "
          f"{'DD%':>5} {'PF':>5}")
    print("  " + "-" * 72)
    for i, r in enumerate(all_combos[:15]):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        ret = r['pnl']/100*100
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"  {i+1:>3} {e} {r['symbol']:<10} {r['strategy']:<12} ${r['pnl']:>+7.2f} {ret:>+5.1f}% "
              f"{r['n']:>6} {r['wr']:>4.0f}% {r['dd']:>4.1f}% {pf:>5}")

    # ═══ BEST STRATEGY PER COIN ═══
    print(f"\n{'=' * 100}")
    print(f"🎯 MEJOR ESTRATEGIA PARA CADA MONEDA ($100)")
    print(f"{'=' * 100}")
    for sym in coin_data:
        if sym not in matrix_100: continue
        best = max(matrix_100[sym].values(), key=lambda x: x['pnl'])
        e = "🟢" if best['pnl'] > 0 else "🔴"
        ret = best['pnl']/100*100
        print(f"  {e} {sym:<12} → {best['strategy']:<12} ${best['pnl']:>+6.2f} ({ret:>+.1f}%) | "
              f"{best['n']} trades | WR {best['wr']:.0f}%")

    # ═══ PORTFOLIO SUGGESTION ═══
    print(f"\n{'=' * 100}")
    print(f"💼 PORTFOLIO SUGERIDO — $100 dividido en las 4 mejores combinaciones")
    print(f"{'=' * 100}")
    # Get top 4 unique coins
    selected = []; seen_coins = set()
    for r in all_combos:
        if r['symbol'] not in seen_coins and r['pnl'] > 0:
            selected.append(r); seen_coins.add(r['symbol'])
        if len(selected) == 4: break
    
    if not selected:
        selected = all_combos[:4]  # Take top 4 even if negative
    
    total = sum(r['pnl'] for r in selected)
    per_coin = 100 / len(selected) if selected else 25
    scaled_total = total * (per_coin / 100)  # Scale from $100 per coin
    
    for r in selected:
        e = "🟢" if r['pnl'] > 0 else "🔴"
        scaled = r['pnl'] * (per_coin / 100)
        print(f"  {e} ${per_coin:.0f} → {r['symbol']:<10} ({r['strategy']:<10}) → ${scaled:>+.2f} | "
              f"{r['n']} trades | WR {r['wr']:.0f}%")
    
    print(f"\n  TOTAL: $100 → ${100+scaled_total:.2f} ({scaled_total:>+.2f}, {scaled_total:.1f}%) en 7 días")
    print(f"  Anualizado: ~{scaled_total/7*365:.0f}% si se mantiene")

if __name__ == "__main__":
    asyncio.run(main())

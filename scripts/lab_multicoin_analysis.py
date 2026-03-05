"""
CT4 LAB — ANÁLISIS MULTI-MONEDA
=================================
Escanea las top monedas de Binance Testnet.
Para cada una analiza:
  - Volatilidad (ATR%, rango diario)
  - Frecuencia de señales BB
  - PnL con $25 (multi-coin, $100/4 monedas)
  - Drawdown y WR
  - Correlación con BTC

Objetivo: Encontrar las 3-4 monedas ideales para operar en paralelo.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

CAPITAL_PER_COIN = 25  # $100 / 4 monedas
FEE = 0.001

# Candidatas
COINS = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT',
    'XRP/USDT', 'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT',
    'LINK/USDT', 'DOT/USDT', 'MATIC/USDT', 'LTC/USDT',
]

def calc(df):
    c, h, lo = df['close'], df['high'], df['low']
    df['EMA9'] = c.ewm(span=9).mean()
    df['EMA21'] = c.ewm(span=21).mean()
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
    df['BB_LO'] = bb_mid - 2 * bs
    df['BB_HI'] = bb_mid + 2 * bs
    df['BB_PCT'] = (c - df['BB_LO']) / (df['BB_HI'] - df['BB_LO'] + 1e-10)
    df['EMA50_1H'] = c.ewm(span=50*12).mean()
    return df

def v(r, c, d=0):
    x = r.get(c, d)
    return d if pd.isna(x) else x

def buy_bb_mtf(r, p1):
    bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX'); macro = r['close'] > v(r, 'EMA200') * 0.99
    mtf = r['close'] > v(r, 'EMA50_1H') * 0.995
    return bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro and mtf

def exit_bb(r, p1):
    if v(r, 'BB_PCT') > 0.95: return True
    if v(p1, 'EMA9') >= v(p1, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21'): return True
    if r['close'] < v(r, 'EMA200') * 0.985: return True
    return False

def backtest_coin(df, capital=CAPITAL_PER_COIN):
    cap = capital; peak = capital; dd = 0; pos = None; trades = []
    signals = 0; min_notional = 5  # Más bajo para altcoins
    for i in range(250, len(df) - 1):
        r, p1 = df.iloc[i], df.iloc[i - 1]
        if pos is None:
            if buy_bb_mtf(r, p1):
                signals += 1
                atr = v(r, 'ATR', r['close'] * 0.01)
                alloc = cap * 0.90  # Con $25, usar 90% (sino min_notional falla)
                if alloc < min_notional: continue
                sz = alloc / r['close']
                entry_fee = alloc * FEE
                pos = {'e': r['close'], 'sl': r['close'] - 1.5 * atr,
                       'tp': r['close'] + 3.0 * atr, 'sz': sz, 'b': i,
                       'fee': entry_fee}
        else:
            p = r['close']
            if p > pos['e'] * 1.005:
                pos['sl'] = max(pos['sl'], p - 1.0 * v(r, 'ATR', r['close'] * 0.01))
            pnl = None
            if p <= pos['sl']: pnl = (pos['sl'] - pos['e']) * pos['sz']
            elif p >= pos['tp']: pnl = (pos['tp'] - pos['e']) * pos['sz']
            elif exit_bb(r, p1): pnl = (p - pos['e']) * pos['sz']
            if pnl is not None:
                exit_fee = p * pos['sz'] * FEE
                pnl -= (pos['fee'] + exit_fee)
                cap += pnl; peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl})
                pos = None
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']
        pnl -= pos['fee'] + df.iloc[-1]['close'] * pos['sz'] * FEE
        cap += pnl; trades.append({'pnl': pnl})
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    return {
        'n': len(trades), 'signals': signals,
        'w': len(w), 'l': len(lo),
        'wr': len(w) / len(trades) * 100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
    }

def analyze_market(df, symbol):
    """Analiza las características del mercado de una moneda."""
    if df is None or len(df) < 250:
        return None
    c = df['close']
    ret = (c.iloc[-1] - c.iloc[250]) / c.iloc[250] * 100
    vol_pct = (df['ATR'].dropna() / c).mean() * 100  # ATR como % del precio
    daily_range = ((df['high'] - df['low']) / c).mean() * 100
    bb_touches = (df['BB_PCT'].dropna() < 0.15).sum()
    bb_pct_time = bb_touches / len(df) * 100
    adx_avg = df['ADX'].dropna().mean()
    adx_high = (df['ADX'].dropna() > 20).sum() / len(df) * 100
    rsi_oversold = (df['RSI'].dropna() < 35).sum()
    price_min = c.min()
    price_max = c.max()
    price_range = (price_max - price_min) / price_min * 100
    
    return {
        'symbol': symbol,
        'candles': len(df),
        'price': c.iloc[-1],
        'ret': ret,
        'vol_pct': vol_pct,
        'daily_range': daily_range,
        'bb_touches': bb_touches,
        'bb_pct': bb_pct_time,
        'adx_avg': adx_avg,
        'adx_high_pct': adx_high,
        'rsi_oversold': rsi_oversold,
        'price_range': price_range,
    }


async def main():
    print("=" * 90)
    print("🔬 CT4 LAB — ANÁLISIS MULTI-MONEDA (¿Cuáles son las mejores para operar?)")
    print("=" * 90)
    print(f"  Capital total: $100 | ${CAPITAL_PER_COIN} por moneda | Fee: {FEE*100}%")
    print(f"  Estrategia: BB + MTF (1h) — La mejor del showdown de $100")

    exchange = ccxt.binance({'sandbox': True})
    
    results = []
    market_data = []
    btc_closes = None
    
    for symbol in COINS:
        print(f"\n  📡 Descargando {symbol}...", end=" ", flush=True)
        all_candles = []
        since = int(datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        end_ts = int(datetime(2026, 3, 5, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)
        
        try:
            while since < end_ts:
                candles = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=1000)
                if not candles: break
                all_candles.extend(candles)
                since = candles[-1][0] + 1
                await asyncio.sleep(0.3)
        except Exception as e:
            print(f"❌ Error: {e}")
            continue
        
        if len(all_candles) < 300:
            print(f"⚠️ Solo {len(all_candles)} velas — insuficientes")
            continue
        
        seen = set(); unique = []
        for c in all_candles:
            if c[0] not in seen: seen.add(c[0]); unique.append(c)
        unique.sort(key=lambda x: x[0])
        
        df = pd.DataFrame(unique, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = calc(df)
        
        if symbol == 'BTC/USDT':
            btc_closes = df['close'].copy()
        
        # Market analysis
        mkt = analyze_market(df, symbol)
        if mkt: market_data.append(mkt)
        
        # Backtest
        bt = backtest_coin(df)
        bt['symbol'] = symbol
        results.append(bt)
        
        e = "🟢" if bt['pnl'] > 0 else "🔴"
        print(f"✅ {len(df)} velas | {e} ${bt['pnl']:+.2f} | {bt['n']} trades | WR {bt['wr']:.0f}%")
    
    await exchange.close()

    # ═══ MARKET ANALYSIS TABLE ═══
    print(f"\n{'=' * 90}")
    print(f"📊 ANÁLISIS DE MERCADO — ¿Qué moneda es más apta para BB Bounce?")
    print(f"{'=' * 90}")
    print(f"   {'Moneda':<12} {'Precio':>10} {'Ret%':>6} {'Vol%':>5} {'Rango%':>7} {'BB<15':>5} {'BB%t':>5} {'ADX':>5} {'RSIos':>5}")
    print("   " + "-" * 70)
    
    market_data.sort(key=lambda x: -x['bb_pct'])
    for m in market_data:
        vol_star = "🔥" if m['vol_pct'] > 0.5 else "  "
        print(f"   {m['symbol']:<12} ${m['price']:>8.2f} {m['ret']:>+5.1f}% {m['vol_pct']:>4.1f}% "
              f"{m['daily_range']:>5.1f}%  {m['bb_touches']:>4} {m['bb_pct']:>4.1f}% "
              f"{m['adx_avg']:>4.0f} {m['rsi_oversold']:>5} {vol_star}")

    # ═══ STRATEGY RESULTS ═══
    print(f"\n{'=' * 90}")
    print(f"💰 BB+MTF BACKTEST — ${CAPITAL_PER_COIN} por moneda")
    print(f"{'=' * 90}")
    results.sort(key=lambda x: -x['pnl'])
    print(f"   {'Moneda':<12} {'PnL':>8} {'Ret%':>7} {'Trades':>6} {'WR':>5} {'DD%':>5} {'PF':>5} {'Sigs':>5}")
    print("   " + "-" * 60)
    for r in results:
        e = "🟢" if r['pnl'] > 0 else "🔴"
        ret = r['pnl'] / CAPITAL_PER_COIN * 100
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['symbol']:<10} ${r['pnl']:>+6.2f} {ret:>+5.1f}% {r['n']:>6} {r['wr']:>4.0f}% "
              f"{r['dd']:>4.1f}% {pf:>5} {r['signals']:>5}")

    # ═══ PORTFOLIO SIMULATION ═══
    positive = [r for r in results if r['pnl'] > 0]
    top4 = results[:4]  # Top 4 by PnL
    
    print(f"\n{'=' * 90}")
    print(f"🎯 SIMULACIÓN PORTFOLIO — Top 4 monedas con ${CAPITAL_PER_COIN} cada una")
    print(f"{'=' * 90}")
    total_pnl = sum(r['pnl'] for r in top4)
    total_trades = sum(r['n'] for r in top4)
    total_cap = sum(r['cap'] for r in top4)
    max_dd = max(r['dd'] for r in top4) if top4 else 0
    
    print(f"  Monedas: {', '.join(r['symbol'] for r in top4)}")
    for r in top4:
        e = "🟢" if r['pnl'] > 0 else "🔴"
        print(f"    {e} {r['symbol']:<10}: ${r['pnl']:>+.2f} ({r['n']} trades)")
    print(f"\n  TOTAL:   ${total_pnl:>+.2f} ({total_pnl/100*100:>+.1f}%)")
    print(f"  Trades:  {total_trades}")
    print(f"  Capital: $100 → ${total_cap:.2f}")
    print(f"  Max DD:  {max_dd:.1f}%")
    
    # vs BTC only
    btc_r = [r for r in results if r['symbol'] == 'BTC/USDT']
    if btc_r:
        btc_pnl = btc_r[0]['pnl']
        btc_pnl_100 = btc_pnl * (100 / CAPITAL_PER_COIN)  # Escalado a $100
        print(f"\n  Comparación:")
        print(f"    Solo BTC ($100):     ${btc_pnl_100:>+.2f}")
        print(f"    Portfolio Top 4:     ${total_pnl:>+.2f}")
        diff = total_pnl - btc_pnl_100
        print(f"    Diferencia:          ${diff:>+.2f} {'✅ Portfolio GANA' if diff > 0 else '❌ BTC solo GANA'}")

    # ═══ RECOMMENDATION ═══
    print(f"\n{'=' * 90}")
    print(f"🏆 RECOMENDACIÓN FINAL")
    print(f"{'=' * 90}")
    profitable = [r for r in results if r['pnl'] > 0]
    if profitable:
        print(f"\n  ✅ Monedas RENTABLES con BB+MTF y ${CAPITAL_PER_COIN}:")
        for r in profitable:
            ret = r['pnl'] / CAPITAL_PER_COIN * 100
            print(f"     {r['symbol']:<12} ${r['pnl']:>+.2f} ({ret:>+.1f}%) | {r['n']} trades | WR {r['wr']:.0f}%")
    
    losers = [r for r in results if r['pnl'] <= 0]
    if losers:
        print(f"\n  ❌ Monedas que PIERDEN:")
        for r in losers:
            ret = r['pnl'] / CAPITAL_PER_COIN * 100
            print(f"     {r['symbol']:<12} ${r['pnl']:>+.2f} ({ret:>+.1f}%)")

if __name__ == "__main__":
    asyncio.run(main())

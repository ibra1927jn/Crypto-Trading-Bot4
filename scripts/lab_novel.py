"""
CT4 Lab — Estrategias NUEVAS (nunca probadas)
===============================================
Todas son enfoques completamente diferentes al RSI Pullback:

1. MACD DIVERGENCE   — Compra divergencia alcista MACD
2. ICHIMOKU CLOUD    — Sistema japonés de nube
3. DONCHIAN TURTLE   — Sistema de tortugas (canales)
4. VWAP BOUNCE       — Rebote en precio medio ponderado por volumen
5. SCALPER           — Trades ultra-rápidos (micro ganancias)
6. SWING EMA CROSS   — Cruce EMA largo plazo
7. DOUBLE BOTTOM     — Patrón chartista doble suelo
8. SQUEEZE MOMENTUM  — Bollinger apretadas + explosión

+ Monte Carlo de cada una (50 sims)
"""
import asyncio, sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

def calc(df):
    df['EMA9'] = df['close'].ewm(span=9).mean()
    df['EMA21'] = df['close'].ewm(span=21).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    df['EMA200'] = df['close'].ewm(span=200).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, abs(h-c.shift(1)), abs(l-c.shift(1))], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    
    pdm = h.diff().where(lambda x: (x > 0) & (x > -l.diff()), 0)
    mdm = (-l.diff()).where(lambda x: (x > 0) & (x > h.diff()), 0)
    pdi = 100*(pdm.rolling(14).mean()/df['ATR'])
    mdi = 100*(mdm.rolling(14).mean()/df['ATR'])
    dx = 100*abs(pdi-mdi)/(pdi+mdi)
    df['ADX'] = dx.rolling(14).mean()
    df['VSMA'] = df['volume'].rolling(20).mean()
    
    # MACD
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_S'] = df['MACD'].ewm(span=9).mean()
    df['MACD_H'] = df['MACD'] - df['MACD_S']
    
    # Bollinger
    df['BB_MID'] = c.rolling(20).mean()
    bs = c.rolling(20).std()
    df['BB_LO'] = df['BB_MID'] - 2*bs
    df['BB_HI'] = df['BB_MID'] + 2*bs
    df['BB_W'] = (df['BB_HI']-df['BB_LO'])/df['BB_MID']  # Bandwidth
    
    # Donchian Channels
    df['DC_HI'] = h.rolling(20).max()
    df['DC_LO'] = l.rolling(20).min()
    df['DC_MID'] = (df['DC_HI']+df['DC_LO'])/2
    
    # VWAP (approx - rolling)
    df['VWAP'] = (c * df['volume']).rolling(50).sum() / df['volume'].rolling(50).sum()
    
    # Ichimoku
    df['ICHI_TENKAN'] = (h.rolling(9).max()+l.rolling(9).min())/2
    df['ICHI_KIJUN'] = (h.rolling(26).max()+l.rolling(26).min())/2
    span_a = ((df['ICHI_TENKAN']+df['ICHI_KIJUN'])/2).shift(26)
    span_b = ((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    df['ICHI_SPAN_A'] = span_a
    df['ICHI_SPAN_B'] = span_b
    df['ICHI_CLOUD_TOP'] = pd.concat([span_a, span_b], axis=1).max(axis=1)
    df['ICHI_CLOUD_BOT'] = pd.concat([span_a, span_b], axis=1).min(axis=1)
    
    # Squeeze (Bollinger Width)
    df['SQUEEZE'] = df['BB_W'] < df['BB_W'].rolling(50).quantile(0.2)
    
    # Stochastic
    l14 = l.rolling(14).min()
    h14 = h.rolling(14).max()
    df['STOCH_K'] = 100 * (c - l14) / (h14 - l14 + 1e-10)
    df['STOCH_D'] = df['STOCH_K'].rolling(3).mean()
    
    return df

def g(r, c, d=0):
    v = r.get(c, d); return d if pd.isna(v) else v

def run(df, name, buy_fn, exit_fn, sl_m=1.5, tp_m=3.0, risk=0.3):
    cap=10000; peak=10000; dd=0; pos=None; trades=[]
    for i in range(202, len(df)-1):
        r, p1, p2 = df.iloc[i], df.iloc[i-1], df.iloc[i-2]
        p3 = df.iloc[i-3] if i>=3 else p2
        if pos is None:
            if buy_fn(r, p1, p2, p3):
                atr=g(r,'ATR',100); sz=(cap*risk)/r['close']
                pos={'e':r['close'],'sl':r['close']-sl_m*atr,'tp':r['close']+tp_m*atr,'sz':sz,'b':i}
        else:
            p=r['close']; pnl=None
            if p<=pos['sl']: pnl=(pos['sl']-pos['e'])*pos['sz']; t='SL'
            elif p>=pos['tp']: pnl=(pos['tp']-pos['e'])*pos['sz']; t='TP'
            elif exit_fn(r,p1): pnl=(p-pos['e'])*pos['sz']; t='EXIT'
            if pnl is not None:
                cap+=pnl; peak=max(peak,cap); dd=max(dd,(peak-cap)/peak*100)
                trades.append({'pnl':pnl,'t':t,'e':pos['e'],'x':p}); pos=None
    if pos:
        pnl=(df.iloc[-1]['close']-pos['e'])*pos['sz']; cap+=pnl
        trades.append({'pnl':pnl,'t':'OPEN','e':pos['e'],'x':df.iloc[-1]['close']})
    w=[t for t in trades if t['pnl']>0]
    l=[t for t in trades if t['pnl']<=0]
    return {'name':name,'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
            'pnl':sum(t['pnl'] for t in trades),'dd':dd,'cap':cap,
            'pf':sum(t['pnl'] for t in w)/abs(sum(t['pnl'] for t in l)) if l and sum(t['pnl'] for t in l)!=0 else 999,
            'details':trades}

# ═══ REFERENCE ═══
def buy_momentum(r,p1,p2,p3):
    rsi,prsi,p2rsi=g(r,'RSI',50),g(p1,'RSI',50),g(p2,'RSI',50)
    adx=g(r,'ADX')
    if prsi<20 and rsi>prsi and adx>35 and r['close']>r['open']: return True
    atr_pct=(g(r,'ATR',100)/r['close'])*100; hv=atr_pct>0.5
    rt=40 if hv else 35; at=15 if hv else 20; mt=0.02 if hv else 0.01
    return (r['close']>g(r,'EMA200')*(1-mt) and adx>at and
            r['volume']>g(r,'VSMA')*0.8 and prsi<rt and rsi>prsi and prsi>p2rsi)

def exit_base(r,p): return (g(p,'EMA9')>=g(p,'EMA21') and g(r,'EMA9')<g(r,'EMA21')) or r['close']<g(r,'EMA200')*0.985

# ═══ NEW STRATEGIES ═══

# 1. MACD DIVERGENCE
def buy_macd(r,p1,p2,p3):
    """Compra cuando MACD cruza señal de abajo + histograma positivo"""
    macd,sig=g(r,'MACD'),g(r,'MACD_S')
    pmacd,psig=g(p1,'MACD'),g(p1,'MACD_S')
    cross_up = pmacd < psig and macd >= sig
    hist_growing = g(r,'MACD_H') > g(p1,'MACD_H')
    above_ema = r['close'] > g(r,'EMA200')
    return cross_up and hist_growing and above_ema
def exit_macd(r,p): return g(r,'MACD') < g(r,'MACD_S') and g(p,'MACD') >= g(p,'MACD_S')

# 2. ICHIMOKU CLOUD
def buy_ichimoku(r,p1,p2,p3):
    """Precio encima de la nube + Tenkan > Kijun"""
    above_cloud = r['close'] > g(r,'ICHI_CLOUD_TOP')
    tk_cross = g(r,'ICHI_TENKAN') > g(r,'ICHI_KIJUN') and g(p1,'ICHI_TENKAN') <= g(p1,'ICHI_KIJUN')
    return above_cloud and tk_cross
def exit_ichimoku(r,p): return r['close'] < g(r,'ICHI_CLOUD_BOT') or (g(r,'ICHI_TENKAN')<g(r,'ICHI_KIJUN'))

# 3. DONCHIAN TURTLE
def buy_donchian(r,p1,p2,p3):
    """Compra breakout del canal superior de Donchian"""
    new_high = r['close'] >= g(r,'DC_HI') * 0.999
    vol_confirm = r['volume'] > g(r,'VSMA')
    trend = g(r,'ADX') > 20
    return new_high and vol_confirm and trend
def exit_donchian(r,p): return r['close'] <= g(r,'DC_MID')

# 4. VWAP BOUNCE
def buy_vwap(r,p1,p2,p3):
    """Rebote en VWAP con RSI oversold"""
    vwap = g(r,'VWAP')
    near_vwap = abs(r['close']-vwap)/vwap < 0.003  # Dentro de 0.3%
    above_ema = r['close'] > g(r,'EMA200')
    rsi_low = g(r,'RSI',50) < 40
    bouncing = r['close'] > r['open']
    return near_vwap and above_ema and rsi_low and bouncing
def exit_vwap(r,p): return r['close'] > g(r,'VWAP')*1.005 and g(r,'RSI',50)>60

# 5. SCALPER (trades rápidos)
def buy_scalper(r,p1,p2,p3):
    """Micro-pullback en tendencia alcista, entry rápido"""
    trend = g(r,'EMA9') > g(r,'EMA21') > g(r,'EMA50')
    pullback = g(p1,'RSI',50) < 45 and g(r,'RSI',50) > g(p1,'RSI',50)
    vol_ok = r['volume'] > g(r,'VSMA') * 0.5
    stoch_cross = g(p1,'STOCH_K') < g(p1,'STOCH_D') and g(r,'STOCH_K') >= g(r,'STOCH_D')
    return trend and pullback and vol_ok
def exit_scalper(r,p): return g(r,'RSI',50) > 60 or g(r,'EMA9') < g(r,'EMA21')

# 6. SWING EMA CROSS
def buy_swing(r,p1,p2,p3):
    """EMA 9 cruza EMA 50 hacia arriba + ADX confirma"""
    cross = g(p1,'EMA9') <= g(p1,'EMA50') and g(r,'EMA9') > g(r,'EMA50')
    trend = g(r,'ADX') > 20
    above_200 = r['close'] > g(r,'EMA200')
    return cross and trend and above_200
def exit_swing(r,p): return g(r,'EMA9') < g(r,'EMA50')

# 7. DOUBLE BOTTOM (doble suelo)
def buy_double_bottom(r,p1,p2,p3):
    """Detecta patrón de doble suelo con RSI"""
    rsi=g(r,'RSI',50); p1r=g(p1,'RSI',50); p2r=g(p2,'RSI',50); p3r=g(p3,'RSI',50)
    # RSI hizo valle → subió → volvió a valle → sube ahora
    first_dip = p3r < 35
    recovery = p2r > p3r
    second_dip = p1r < 38 and p1r > p3r - 5  # Segundo suelo más alto
    bounce = rsi > p1r
    above_ema = r['close'] > g(r,'EMA200') * 0.99
    return first_dip and recovery and second_dip and bounce and above_ema
def exit_double_bottom(r,p): return exit_base(r,p)

# 8. SQUEEZE MOMENTUM (Bollinger squeeze + breakout)
def buy_squeeze(r,p1,p2,p3):
    """Bollinger Bands se aprietan → explosión alcista"""
    was_squeezed = g(p1,'SQUEEZE') or g(p2,'SQUEEZE')
    not_squeezed = not g(r,'SQUEEZE')
    breakout_up = r['close'] > g(r,'BB_MID') and r['close'] > p1['close']
    trend_ok = g(r,'ADX') > 15
    return was_squeezed and not_squeezed and breakout_up and trend_ok
def exit_squeeze(r,p): return r['close'] < g(r,'BB_MID') or g(r,'RSI',50) > 75

async def main():
    print("="*70)
    print("🧪 CT4 LAB — Estrategias COMPLETAMENTE NUEVAS")
    print("="*70)
    
    exchange = ccxt.binance({'sandbox': True})
    candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', limit=1000)
    await exchange.close()
    
    df = pd.DataFrame(candles, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc(df)
    
    print(f"\n✅ {len(df)} velas | {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')}")
    print(f"   Rango: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    
    strats = [
        ("⭐ MOMENTUM (referencia)", buy_momentum, exit_base, 1.5, 3.0),
        ("1. MACD DIVERGENCE",       buy_macd,     exit_macd, 1.5, 3.0),
        ("2. ICHIMOKU CLOUD",        buy_ichimoku, exit_ichimoku, 2.0, 3.0),
        ("3. DONCHIAN TURTLE",       buy_donchian, exit_donchian, 1.5, 3.0),
        ("4. VWAP BOUNCE",           buy_vwap,     exit_vwap, 1.0, 2.0),
        ("5. SCALPER",               buy_scalper,  exit_scalper, 0.8, 1.5),
        ("6. SWING EMA CROSS",       buy_swing,    exit_swing, 2.0, 4.0),
        ("7. DOUBLE BOTTOM",         buy_double_bottom, exit_double_bottom, 1.5, 3.0),
        ("8. SQUEEZE MOMENTUM",      buy_squeeze,  exit_squeeze, 1.5, 3.0),
    ]
    
    results = []
    for name, buy, exit_fn, sl, tp in strats:
        r = run(df, name, buy, exit_fn, sl, tp)
        results.append(r)
    
    print(f"\n{'='*70}")
    print(f"📊 RESULTADOS — Backtest normal")
    print(f"{'='*70}")
    print(f"   {'Estrategia':<30} {'T':>3} {'W':>3} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
    print("   "+"-"*65)
    for r in results:
        e="🟢" if r['pnl']>0 else ("🔴" if r['pnl']<0 else "⚪")
        print(f"   {e} {r['name']:<28} {r['n']:>3} {r['w']:>3} {r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {r['pf']:>5.1f}")
    
    # ═══ MONTE CARLO (50 sims each) ═══
    print(f"\n{'='*70}")
    print("🎲 MONTE CARLO — 50 simulaciones cada una")
    print(f"{'='*70}")
    
    for name, buy, exit_fn, sl, tp in strats:
        profits = []
        for _ in range(50):
            blocks = [df.iloc[i:i+10] for i in range(0, len(df), 10)]
            random.shuffle(blocks)
            sh = pd.concat(blocks).reset_index(drop=True)
            sh = calc(sh)
            r = run(sh, name, buy, exit_fn, sl, tp)
            profits.append(r['pnl'])
        wins = sum(1 for p in profits if p > 0)
        avg = np.mean(profits)
        worst = min(profits)
        best = max(profits)
        e="🟢" if wins>=25 else "🔴"
        print(f"   {e} {name:<28} Gana {wins:>2}/50 ({wins*2:>3}%) | Avg: ${avg:>+7.1f} | Worst: ${worst:>+7.1f} | Best: ${best:>+7.1f}")
    
    # ═══ WALK-FORWARD ═══
    print(f"\n{'='*70}")
    print("🛡️ WALK-FORWARD — ¿Funcionan en datos NO VISTOS?")
    print(f"{'='*70}")
    
    split = int(len(df)*0.7)
    train, test = df.iloc[:split], df.iloc[split:]
    
    print(f"   {'Estrategia':<30} {'TRAIN PnL':>12} {'TEST PnL':>12} {'Consistent':>12}")
    print("   "+"-"*70)
    for name, buy, exit_fn, sl, tp in strats:
        rt = run(train, name, buy, exit_fn, sl, tp)
        rv = run(test, name, buy, exit_fn, sl, tp)
        con = "✅ SÍ" if (rt['pnl']>0)==(rv['pnl']>0) else "❌ NO"
        et="🟢" if rt['pnl']>0 else "🔴"
        ev="🟢" if rv['pnl']>0 else "🔴"
        print(f"   {name:<30} {et} ${rt['pnl']:>+8.2f} {ev} ${rv['pnl']:>+8.2f}    {con}")
    
    # ═══ RANKING FINAL ═══
    ranked = sorted(results, key=lambda x: x['pnl'], reverse=True)
    print(f"\n{'='*70}")
    print("🏆 RANKING FINAL")
    print(f"{'='*70}")
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣"]
    for i, r in enumerate(ranked):
        e="🟢" if r['pnl']>0 else "🔴"
        print(f"  {medals[i]} {e} {r['name']:<30} {r['n']:>2}T {r['wr']:>3.0f}% ${r['pnl']:>+8.2f} DD:{r['dd']:.1f}% PF:{r['pf']:.1f}")
    
    # Winner details
    w = ranked[0]
    print(f"\n⭐ GANADORA: {w['name']}")
    print(f"   Trades: {w['n']} | Win Rate: {w['wr']:.0f}% | PnL: ${w['pnl']:+.2f} | DD: {w['dd']:.2f}%")
    for t in w['details'][:8]:
        e="🟢" if t['pnl']>0 else "🔴"
        print(f"   {e} ${t['e']:.0f}→${t['x']:.0f} | {t['t']:>4} | ${t['pnl']:+.2f}")

if __name__ == "__main__":
    asyncio.run(main())

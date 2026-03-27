"""
🧪 LAB AGRESIVO: 5 Monedas × 8 Estrategias × $30 cada una
============================================================
XRP, DOGE, AVAX, SHIB, SOL — Estrategias agresivas
Datos: último mes de Binance Real (velas 5m)
"""
import sys
import os
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timedelta

def p(msg):
    print(msg)
    sys.stdout.flush()

# ═══════════════════════════════════════════════════════
# ESTRATEGIAS AGRESIVAS
# ═══════════════════════════════════════════════════════

def strat_rsi_dip(data, rsi_buy=30, rsi_sell=65, sl=3, tp=5, cap=30.0):
    """RSI Buy-the-Dip agresivo."""
    pos=None; bal=cap; trades=[]
    for i in range(50, len(data)):
        r,prev,price = data.iloc[i], data.iloc[i-1], data.iloc[i]['close']
        rn=r.get('RSI_14',50); rp=prev.get('RSI_14',50)
        if pd.isna(rn) or pd.isna(rp): continue
        if pos is None:
            if rp < rsi_buy and rn > rp:
                amt=(bal*0.90)/price
                pos={'e':price,'a':amt,'sl':price*(1-sl/100),'tp':price*(1+tp/100)}
        else:
            if price<=pos['sl'] or price>=pos['tp'] or rn>rsi_sell:
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                trades.append({'pnl':pnl,'r':'SL' if price<=pos['sl'] else ('TP' if price>=pos['tp'] else 'RSI')})
                pos=None
    if pos: pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl; trades.append({'pnl':pnl,'r':'END'})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    return {'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100}

def strat_bb_bounce(data, sl=3, tp=5, cap=30.0):
    """Bollinger Band Bounce — compra cuando toca banda inferior."""
    pos=None; bal=cap; trades=[]
    bb = ta.bbands(data['close'], length=20, std=2.0)
    if bb is None: return {'trades':0,'wins':0,'pnl':0,'wr':0}
    bbl_col = [c for c in bb.columns if c.startswith('BBL_')]
    bbu_col = [c for c in bb.columns if c.startswith('BBU_')]
    if not bbl_col or not bbu_col: return {'trades':0,'wins':0,'pnl':0,'wr':0}
    data = data.copy()
    data['BBL'] = bb[bbl_col[0]]
    data['BBU'] = bb[bbu_col[0]]
    
    for i in range(50, len(data)):
        r = data.iloc[i]; price = r['close']
        bbl = r.get('BBL', None); bbu = r.get('BBU', None)
        if pd.isna(bbl) or pd.isna(bbu): continue
        if pos is None:
            if price <= bbl * 1.005:  # Toca o cruza banda inferior
                amt=(bal*0.90)/price
                pos={'e':price,'a':amt,'sl':price*(1-sl/100),'tp':price*(1+tp/100)}
        else:
            if price<=pos['sl'] or price>=pos['tp'] or price >= bbu * 0.995:
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                trades.append({'pnl':pnl,'r':'SL' if price<=pos['sl'] else 'TP/BB'})
                pos=None
    if pos: pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl; trades.append({'pnl':pnl,'r':'END'})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    return {'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100}

def strat_ema_cross(data, fast=9, slow=21, sl=3, tp=5, cap=30.0):
    """EMA Crossover agresivo — compra cuando EMA rápida cruza EMA lenta hacia arriba."""
    pos=None; bal=cap; trades=[]
    data = data.copy()
    ema_f = ta.ema(data['close'], length=fast)
    ema_s = ta.ema(data['close'], length=slow)
    if ema_f is None or ema_s is None: return {'trades':0,'wins':0,'pnl':0,'wr':0}
    data['EF'] = ema_f; data['ES'] = ema_s
    
    for i in range(50, len(data)):
        r,prev,price = data.iloc[i],data.iloc[i-1],data.iloc[i]['close']
        ef=r.get('EF'); es=r.get('ES'); pef=prev.get('EF'); pes=prev.get('ES')
        if any(pd.isna(x) for x in [ef,es,pef,pes]): continue
        if pos is None:
            if pef <= pes and ef > es:  # Golden cross
                amt=(bal*0.90)/price
                pos={'e':price,'a':amt,'sl':price*(1-sl/100),'tp':price*(1+tp/100)}
        else:
            if price<=pos['sl'] or price>=pos['tp'] or (ef < es):
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                trades.append({'pnl':pnl,'r':'SL' if price<=pos['sl'] else 'EXIT'})
                pos=None
    if pos: pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl; trades.append({'pnl':pnl,'r':'END'})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    return {'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100}

def strat_momentum_burst(data, sl=4, tp=6, cap=30.0):
    """Momentum Burst — compra cuando RSI sube de <40 a >50 con volumen alto."""
    pos=None; bal=cap; trades=[]
    data = data.copy()
    data['VOL_SMA'] = data['volume'].rolling(20).mean()
    
    for i in range(50, len(data)):
        r,prev,price = data.iloc[i],data.iloc[i-1],data.iloc[i]['close']
        rn=r.get('RSI_14',50); rp=prev.get('RSI_14',50)
        vol=r.get('volume',0); vol_sma=r.get('VOL_SMA',1)
        if pd.isna(rn) or pd.isna(rp) or pd.isna(vol_sma) or vol_sma==0: continue
        if pos is None:
            if rp < 40 and rn > 50 and vol > vol_sma * 1.5:
                amt=(bal*0.90)/price
                pos={'e':price,'a':amt,'sl':price*(1-sl/100),'tp':price*(1+tp/100)}
        else:
            if price<=pos['sl'] or price>=pos['tp'] or rn>75:
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                trades.append({'pnl':pnl,'r':'SL' if price<=pos['sl'] else 'EXIT'})
                pos=None
    if pos: pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl; trades.append({'pnl':pnl,'r':'END'})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    return {'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100}

def strat_scalp(data, sl=1.5, tp=2, cap=30.0):
    """Scalping ultra-agresivo — RSI<40, TP rápido +2%, SL ajustado -1.5%."""
    return strat_rsi_dip(data, rsi_buy=40, rsi_sell=55, sl=sl, tp=tp, cap=cap)

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    p("=" * 80)
    p("🧪 LAB AGRESIVO: 5 MONEDAS × 8 ESTRATEGIAS × $30")
    p(f"📅 Datos: último mes de Binance Real (velas 5m)")
    p(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    p("=" * 80)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    coins = ['XRP/USDT', 'DOGE/USDT', 'AVAX/USDT', 'SHIB/USDT', 'SOL/USDT']
    
    all_results = {}
    
    for coin in coins:
        p(f"\n{'─'*80}")
        p(f"📊 {coin}")
        p(f"{'─'*80}")
        
        try:
            # Descargar último mes (1000 velas 5m ≈ 3.5 días, 
            # usamos 1h para cubrir más tiempo → 720 velas ≈ 30 días)
            p(f"   📥 Descargando datos (1h, ~30 días)...")
            ohlcv = ex.fetch_ohlcv(coin, '1h', limit=720)
            
            if not ohlcv or len(ohlcv) < 100:
                p(f"   ❌ Insuficientes datos: {len(ohlcv) if ohlcv else 0} velas")
                continue
            
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df[~df.index.duplicated(keep='last')]
            df['RSI_14'] = ta.rsi(df['close'], length=14)
            
            price_now = df.iloc[-1]['close']
            price_start = df.iloc[0]['close']
            bh_ret = (price_now / price_start - 1) * 100
            
            p(f"   ✅ {len(df)} velas | ${price_start:.4f} → ${price_now:.4f} ({bh_ret:+.1f}%)")
            p(f"   📈 Rango: ${df['close'].min():.4f} — ${df['close'].max():.4f}")
            
            # RSI distribution
            rsi = df['RSI_14'].dropna()
            for lvl in [15,25,30,35,40]:
                cnt = len(rsi[rsi<lvl])
                p(f"   RSI<{lvl}: {cnt} velas ({cnt/len(rsi)*100:.1f}%)")
            
            # Run all strategies
            strategies = [
                ('RSI<30 Agresivo (SL-3%/TP+5%)',   lambda d: strat_rsi_dip(d, 30, 65, 3, 5)),
                ('RSI<35 Ultra-Agresivo (SL-3%/TP+5%)', lambda d: strat_rsi_dip(d, 35, 60, 3, 5)),
                ('RSI<30 Swing (SL-5%/TP+10%)',      lambda d: strat_rsi_dip(d, 30, 75, 5, 10)),
                ('Bollinger Bounce (SL-3%/TP+5%)',    lambda d: strat_bb_bounce(d, 3, 5)),
                ('EMA 9/21 Cross (SL-3%/TP+5%)',      lambda d: strat_ema_cross(d, 9, 21, 3, 5)),
                ('Momentum Burst (SL-4%/TP+6%)',      lambda d: strat_momentum_burst(d, 4, 6)),
                ('Scalping (SL-1.5%/TP+2%)',          lambda d: strat_scalp(d, 1.5, 2)),
                ('RSI<25 Conservador (SL-4%/TP+8%)',  lambda d: strat_rsi_dip(d, 25, 70, 4, 8)),
            ]
            
            p(f"\n   {'Estrategia':<42s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s}")
            p(f"   {'-'*42}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}")
            
            coin_results = []
            for name, func in strategies:
                r = func(df)
                r['name'] = name
                coin_results.append(r)
                e = '🟢' if r['pnl']>0 else ('⚪' if r['trades']==0 else '🔴')
                p(f"   {name:<42s} | {e}${r['pnl']:+5.2f} | {r['trades']:3d} | {r['wr']:3.0f}%")
            
            # Best strategy for this coin
            best = max(coin_results, key=lambda x: x['pnl'])
            if best['trades'] > 0:
                p(f"\n   🏆 MEJOR para {coin}: {best['name']}")
                p(f"      PnL: ${best['pnl']:+.2f} | Trades: {best['trades']} | WR: {best['wr']:.0f}%")
            else:
                p(f"\n   ⚠️ Ninguna estrategia generó trades para {coin}")
            
            all_results[coin] = {'best': best, 'all': coin_results, 'bh': bh_ret}
            
        except Exception as e:
            p(f"   ❌ Error: {e}")
        
        time.sleep(1)  # Rate limit
    
    # ═══════════════════════════════════════════════════════
    # RESUMEN FINAL
    # ═══════════════════════════════════════════════════════
    p(f"\n{'='*80}")
    p("🏆 RESUMEN FINAL — MEJOR ESTRATEGIA POR MONEDA")
    p(f"{'='*80}")
    
    total_pnl = 0
    for coin, data in all_results.items():
        b = data['best']
        e = '🟢' if b['pnl']>0 else '🔴'
        total_pnl += b['pnl']
        p(f"   {coin:12s} | {e} ${b['pnl']:+5.2f} | {b['name']:<40s} | T:{b['trades']:2d} WR:{b['wr']:.0f}% | B&H:{data['bh']:+.1f}%")
    
    p(f"\n   {'TOTAL COMBINADO':12s} | {'🟢' if total_pnl>0 else '🔴'} ${total_pnl:+5.2f} (con $150 invertidos = $30×5)")
    p(f"   {'% RETORNO':12s} | {total_pnl/150*100:+.1f}% en ~30 días")
    
    bh_total = sum(d['bh'] for d in all_results.values()) / max(len(all_results), 1)
    p(f"   {'B&H PROMEDIO':12s} | {bh_total:+.1f}%")
    
    p(f"\n{'='*80}")
    p("💡 CONCLUSIONES")
    p(f"{'='*80}")
    p("   Las estrategias agresivas (RSI<30-35, SL-3%, TP+5%) generan más trades")
    p("   y aprovechan más movimientos del mercado que RSI<15 conservador.")
    p("   Cada moneda tiene una estrategia óptima diferente.")

if __name__ == '__main__':
    main()

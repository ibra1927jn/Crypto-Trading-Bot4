"""
Crypto-Trading-Bot4 — Laboratorio de Optimización
===================================================
Corre múltiples backtests con diferentes configuraciones
para encontrar la combinación óptima de parámetros.

Uso:
  python scripts/lab.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import pandas_ta as ta
import numpy as np
import ccxt.async_support as ccxt
from datetime import datetime, timezone
from utils.logger import setup_logger

logger = setup_logger("LAB")

# =============================================
# CONFIGURACIÓN DE EXPERIMENTOS
# =============================================

EXPERIMENTS = [
    # Exp 1: Baseline (actual) en diferentes períodos
    {"name": "BASELINE_30d_5m",   "days": 30,  "tf": "5m",  "adx": 25, "vol_filter": True,  "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "BASELINE_90d_5m",   "days": 90,  "tf": "5m",  "adx": 25, "vol_filter": True,  "sl_mult": 1.5, "tp_mult": 3.0},
    
    # Exp 2: Timeframe más alto (escapar del ruido)
    {"name": "TF_90d_15m",        "days": 90,  "tf": "15m", "adx": 25, "vol_filter": True,  "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "TF_90d_1h",         "days": 90,  "tf": "1h",  "adx": 25, "vol_filter": True,  "sl_mult": 1.5, "tp_mult": 3.0},
    
    # Exp 3: Aflojar el gatillo
    {"name": "ADX20_90d_5m",      "days": 90,  "tf": "5m",  "adx": 20, "vol_filter": True,  "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "ADX20_NoVol_90d_5m","days": 90,  "tf": "5m",  "adx": 20, "vol_filter": False, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "ADX15_90d_15m",     "days": 90,  "tf": "15m", "adx": 15, "vol_filter": False, "sl_mult": 1.5, "tp_mult": 3.0},
    
    # Exp 4: Combos ganadores potenciales
    {"name": "COMBO_90d_15m_ADX20",  "days": 90, "tf": "15m", "adx": 20, "vol_filter": True, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "COMBO_90d_1h_ADX20",   "days": 90, "tf": "1h",  "adx": 20, "vol_filter": True, "sl_mult": 1.5, "tp_mult": 3.0},
]

SYMBOL = "BTC/USDT"
RISK_PCT = 0.01  # 1% por trade


# =============================================
# MOTOR DE BACKTEST PARAMETRIZABLE
# =============================================

async def fetch_data(tf: str, days: int) -> pd.DataFrame:
    """Descarga datos históricos con retry."""
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'timeout': 30000,
    })
    
    all_ohlcv = []
    since = exchange.parse8601(
        (datetime.now(timezone.utc) - pd.Timedelta(days=days)).isoformat()
    )
    
    try:
        batch = 0
        while True:
            batch += 1
            ohlcv = None
            for attempt in range(3):
                try:
                    ohlcv = await exchange.fetch_ohlcv(
                        SYMBOL, tf, since=since, limit=1000
                    )
                    break
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(3 * (attempt + 1))
                    else:
                        raise
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            if batch % 5 == 0:
                logger.info(f"    ... {len(all_ohlcv):,} velas ({tf})")
            if len(ohlcv) < 1000:
                break
            await asyncio.sleep(0.3)
    finally:
        await exchange.close()

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula indicadores técnicos."""
    df['EMA_200'] = ta.ema(df['close'], length=200)
    df['EMA_9'] = ta.ema(df['close'], length=9)
    df['EMA_21'] = ta.ema(df['close'], length=21)
    
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None:
        df['ADX_14'] = adx_df['ADX_14']
    
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    if atr is not None:
        df['ATR_14'] = atr
    
    df['VOL_SMA_20'] = df['volume'].rolling(window=20).mean()
    df.dropna(subset=['EMA_200', 'ADX_14', 'ATR_14'], inplace=True)
    return df


def run_backtest(df: pd.DataFrame, config: dict) -> dict:
    """Simula la estrategia con parámetros configurables."""
    balance = 10000.0
    initial = balance
    trades = []
    equity_curve = [balance]
    position = None
    
    adx_threshold = config['adx']
    vol_filter = config['vol_filter']
    sl_mult = config['sl_mult']
    tp_mult = config['tp_mult']
    tf = config['tf']

    for i in range(2, len(df)):
        closed = df.iloc[i - 1]
        prev = df.iloc[i - 2]
        current = df.iloc[i]

        # Check SL/TP
        if position:
            if current['low'] <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['amt']
                balance += pnl
                trades.append({'pnl': pnl, 'reason': 'SL', 'bars': i - position['idx']})
                position = None
            elif current['high'] >= position['tp']:
                pnl = (position['tp'] - position['entry']) * position['amt']
                balance += pnl
                trades.append({'pnl': pnl, 'reason': 'TP', 'bars': i - position['idx']})
                position = None
            
            eq = balance + ((current['close'] - position['entry']) * position['amt']) if position else balance
            equity_curve.append(eq)
            continue

        # Evaluar señal
        if pd.isna(closed.get('EMA_200')) or pd.isna(closed.get('ADX_14')):
            equity_curve.append(balance)
            continue

        macro = closed['close'] > closed['EMA_200']
        strong = closed['ADX_14'] > adx_threshold
        volume = (closed['volume'] > closed.get('VOL_SMA_20', 0)) if vol_filter else True
        cross = (
            prev.get('EMA_9', 0) <= prev.get('EMA_21', 0) and
            closed.get('EMA_9', 0) > closed.get('EMA_21', 0)
        )

        if macro and strong and volume and cross:
            entry = current['open']
            atr = closed.get('ATR_14', 0)
            if atr > 0 and entry > 0:
                sl_dist = atr * sl_mult
                tp_dist = atr * tp_mult
                risk_amt = balance * RISK_PCT
                amt = risk_amt / sl_dist
                max_amt = (balance * 0.95) / entry
                amt = min(amt, max_amt)
                
                if amt * entry >= 10:
                    position = {
                        'entry': entry, 'amt': amt,
                        'sl': entry - sl_dist, 'tp': entry + tp_dist,
                        'idx': i,
                    }

        equity_curve.append(balance)

    # Cerrar posición abierta al final
    if position:
        pnl = (df.iloc[-1]['close'] - position['entry']) * position['amt']
        balance += pnl
        trades.append({'pnl': pnl, 'reason': 'END', 'bars': len(df) - position['idx']})

    # Métricas
    if not trades:
        return {
            'name': config['name'], 'trades': 0, 'win_rate': 0, 'pnl': 0,
            'pnl_pct': 0, 'max_dd': 0, 'sharpe': 0, 'pf': 0, 'avg_rr': 0,
            'sl_exits': 0, 'tp_exits': 0, 'avg_bars': 0,
        }

    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max() * 100
    
    rets = np.diff(eq) / eq[:-1]
    tf_min = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
    bpy = (365.25 * 24 * 60) / tf_min.get(tf, 5)
    sharpe = (np.mean(rets) / np.std(rets)) * np.sqrt(bpy) if np.std(rets) > 0 else 0
    
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 1
    pf = gp / gl if gl > 0 else 0
    
    avg_w = np.mean(wins) if wins else 0
    avg_l = abs(np.mean(losses)) if losses else 1
    rr = avg_w / avg_l if avg_l > 0 else 0

    return {
        'name': config['name'],
        'trades': len(trades),
        'win_rate': len(wins) / len(trades) * 100,
        'pnl': sum(pnls),
        'pnl_pct': (balance - initial) / initial * 100,
        'max_dd': dd,
        'sharpe': sharpe,
        'pf': pf,
        'avg_rr': rr,
        'sl_exits': len([t for t in trades if t['reason'] == 'SL']),
        'tp_exits': len([t for t in trades if t['reason'] == 'TP']),
        'avg_bars': np.mean([t['bars'] for t in trades]),
    }


# =============================================
# RUNNER PRINCIPAL
# =============================================

async def main():
    print("\n" + "=" * 80)
    print("🧪 LABORATORIO DE OPTIMIZACIÓN — Crypto-Trading-Bot4")
    print("=" * 80)

    # Cache de datos por (tf, days) para no re-descargar
    data_cache = {}
    results = []

    for exp in EXPERIMENTS:
        key = (exp['tf'], exp['days'])
        
        if key not in data_cache:
            logger.info(f"📥 Descargando {exp['days']}d @ {exp['tf']}...")
            try:
                df = await fetch_data(exp['tf'], exp['days'])
                df = add_indicators(df)
                data_cache[key] = df
                logger.info(f"   ✅ {len(df)} velas útiles")
            except Exception as e:
                logger.error(f"   ❌ Error descargando: {e}")
                results.append({
                    'name': exp['name'], 'trades': 0, 'win_rate': 0, 'pnl': 0,
                    'pnl_pct': 0, 'max_dd': 0, 'sharpe': 0, 'pf': 0, 'avg_rr': 0,
                    'sl_exits': 0, 'tp_exits': 0, 'avg_bars': 0,
                })
                continue
        
        df = data_cache[key]
        logger.info(f"🔬 Corriendo: {exp['name']}...")
        result = run_backtest(df, exp)
        results.append(result)

    # =============================================
    # TABLA COMPARATIVA
    # =============================================
    print("\n" + "=" * 80)
    print("📊 RESULTADOS COMPARATIVOS")
    print("=" * 80)
    print(f"{'Experimento':<28} {'Trades':>6} {'WR%':>6} {'PnL$':>10} {'PnL%':>7} {'MaxDD':>7} {'Sharpe':>7} {'PF':>6} {'R:R':>5} {'SL':>4} {'TP':>4}")
    print("-" * 80)
    
    for r in results:
        # Highlight profitable configs
        marker = "🟢" if r['pf'] > 1.0 else "🟡" if r['pf'] > 0.8 else "🔴"
        print(
            f"{marker} {r['name']:<25} "
            f"{r['trades']:>6} "
            f"{r['win_rate']:>5.1f}% "
            f"{r['pnl']:>+9.2f} "
            f"{r['pnl_pct']:>+6.1f}% "
            f"{r['max_dd']:>6.1f}% "
            f"{r['sharpe']:>+6.2f} "
            f"{r['pf']:>5.2f} "
            f"{r['avg_rr']:>4.2f} "
            f"{r['sl_exits']:>4} "
            f"{r['tp_exits']:>4}"
        )
    
    print("=" * 80)
    
    # Encontrar el ganador
    profitable = [r for r in results if r['pf'] > 1.0 and r['trades'] >= 5]
    if profitable:
        best = max(profitable, key=lambda x: x['sharpe'])
        print(f"\n🏆 GANADOR: {best['name']}")
        print(f"   Trades={best['trades']} | WR={best['win_rate']:.1f}% | PF={best['pf']:.2f} | Sharpe={best['sharpe']:.2f}")
        print(f"   → PnL: ${best['pnl']:+,.2f} ({best['pnl_pct']:+.1f}%) | Max DD: {best['max_dd']:.1f}%")
    else:
        best_attempt = max(results, key=lambda x: x['pf']) if results else None
        if best_attempt and best_attempt['trades'] > 0:
            print(f"\n🟡 MEJOR INTENTO: {best_attempt['name']} (PF={best_attempt['pf']:.2f}, aún no rentable)")
            breakeven_wr = 1 / (1 + best_attempt['avg_rr']) * 100 if best_attempt['avg_rr'] > 0 else 50
            print(f"   WR actual: {best_attempt['win_rate']:.1f}% | Breakeven WR: {breakeven_wr:.1f}% | Gap: {breakeven_wr - best_attempt['win_rate']:+.1f}%")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

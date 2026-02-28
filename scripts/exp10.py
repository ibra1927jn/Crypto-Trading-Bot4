"""
Crypto-Trading-Bot4 — Experimento 10: RSI Pullback + Breakeven Trail
=====================================================================
Hipótesis: El cruce EMA 9×21 compra el techo (lagging).
Solución: Comprar el retroceso (pullback) con RSI + trail a breakeven.

Arma 1: RSI Pullback → Comprar sangre en tendencia alcista
  - Macro: Precio > EMA 200 (tendencia alcista)
  - Fuerza: ADX > 20 (hay tendencia real)
  - Gatillo: RSI estaba < 40 y ahora rebota (prev RSI < 40, curr RSI > prev)

Arma 2: Trail a Breakeven → Eliminar pérdidas
  - Si el trade avanza +1.0 ATR a favor → mover SL a entrada
  - Efecto: pérdidas se convierten en empates ($0)

Uso:
  python scripts/exp10.py
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

logger = setup_logger("EXP10")

SYMBOL = "BTC/USDT"
RISK_PCT = 0.01


async def fetch_data(tf: str, days: int) -> pd.DataFrame:
    """Descarga datos históricos con retry."""
    exchange = ccxt.binance({'enableRateLimit': True, 'timeout': 30000})
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
                    ohlcv = await exchange.fetch_ohlcv(SYMBOL, tf, since=since, limit=1000)
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
    """Indicadores: EMA200, ADX, ATR, RSI."""
    df['EMA_200'] = ta.ema(df['close'], length=200)
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None:
        df['ADX_14'] = adx_df['ADX_14']
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    if atr is not None:
        df['ATR_14'] = atr
    # RSI 14 — EL NUEVO GATILLO
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    df.dropna(subset=['EMA_200', 'ADX_14', 'ATR_14', 'RSI_14'], inplace=True)
    return df


def run_experiment(df: pd.DataFrame, config: dict) -> dict:
    """
    Backtest con RSI Pullback + Breakeven Trail.
    """
    balance = 10000.0
    initial = balance
    trades = []
    equity_curve = [balance]
    position = None  # {entry, amt, sl, tp, atr, idx, be_triggered}

    adx_thresh = config['adx']
    rsi_entry = config['rsi_entry']       # RSI threshold para considerar pullback
    sl_mult = config['sl_mult']
    tp_mult = config['tp_mult']
    be_mult = config.get('be_mult', None)  # ATR mult para activar breakeven (None=disabled)

    for i in range(2, len(df)):
        closed = df.iloc[i - 1]
        prev = df.iloc[i - 2]
        current = df.iloc[i]

        # === POSICIÓN ABIERTA: Check SL/TP/Breakeven ===
        if position:
            # Arma 2: Breakeven Trail
            if be_mult and not position['be_triggered']:
                if current['high'] >= position['entry'] + (be_mult * position['atr']):
                    position['sl'] = position['entry']  # SL → Breakeven
                    position['be_triggered'] = True

            # Check SL hit
            if current['low'] <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['amt']
                balance += pnl
                trades.append({
                    'pnl': pnl,
                    'reason': 'BE' if position['be_triggered'] and pnl == 0 else 'SL',
                    'bars': i - position['idx'],
                    'be': position['be_triggered'],
                })
                position = None
            # Check TP hit
            elif current['high'] >= position['tp']:
                pnl = (position['tp'] - position['entry']) * position['amt']
                balance += pnl
                trades.append({
                    'pnl': pnl, 'reason': 'TP',
                    'bars': i - position['idx'],
                    'be': position['be_triggered'],
                })
                position = None

            eq = balance + ((current['close'] - position['entry']) * position['amt']) if position else balance
            equity_curve.append(eq)
            continue

        # === SIN POSICIÓN: Evaluar señal ===
        if pd.isna(closed.get('EMA_200')) or pd.isna(closed.get('RSI_14')):
            equity_curve.append(balance)
            continue

        # Arma 1: RSI Pullback en tendencia alcista
        macro = closed['close'] > closed['EMA_200']
        strong = closed['ADX_14'] > adx_thresh
        rsi_pullback = (prev['RSI_14'] < rsi_entry) and (closed['RSI_14'] > prev['RSI_14'])

        if macro and strong and rsi_pullback:
            entry = current['open']
            atr = closed['ATR_14']
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
                        'atr': atr, 'idx': i, 'be_triggered': False,
                    }

        equity_curve.append(balance)

    # Cerrar posición abierta
    if position:
        pnl = (df.iloc[-1]['close'] - position['entry']) * position['amt']
        balance += pnl
        trades.append({'pnl': pnl, 'reason': 'END', 'bars': len(df) - position['idx'], 'be': False})

    # === MÉTRICAS ===
    if not trades:
        return {'name': config['name'], 'trades': 0, 'win_rate': 0, 'pnl': 0,
                'pnl_pct': 0, 'max_dd': 0, 'sharpe': 0, 'pf': 0, 'avg_rr': 0,
                'sl': 0, 'tp': 0, 'be': 0, 'avg_bars': 0}

    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    breakevens = [p for p in pnls if p == 0]

    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max() * 100

    rets = np.diff(eq) / eq[:-1]
    tf_min = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240}
    bpy = (365.25 * 24 * 60) / tf_min.get(config['tf'], 5)
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
        'sl': len([t for t in trades if t['reason'] == 'SL']),
        'tp': len([t for t in trades if t['reason'] == 'TP']),
        'be': len([t for t in trades if t['reason'] == 'BE' or (t['pnl'] == 0 and t['be'])]),
        'avg_bars': np.mean([t['bars'] for t in trades]),
    }


# =============================================
# MATRIZ DE EXPERIMENTOS
# =============================================

CONFIGS = [
    # Control: EMA Cross original (para comparar)
    # (esto requiere lógica de cruce, lo omitimos y usamos el resultado anterior: PF=0.79)

    # Exp 10a: RSI Pullback PURO (sin breakeven)
    {"name": "RSI40_ADX20_NoBE",     "tf": "5m", "adx": 20, "rsi_entry": 40, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": None},
    {"name": "RSI35_ADX20_NoBE",     "tf": "5m", "adx": 20, "rsi_entry": 35, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": None},
    {"name": "RSI45_ADX20_NoBE",     "tf": "5m", "adx": 20, "rsi_entry": 45, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": None},
    
    # Exp 10b: RSI Pullback + Breakeven Trail
    {"name": "RSI40_ADX20_BE1.0",    "tf": "5m", "adx": 20, "rsi_entry": 40, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": 1.0},
    {"name": "RSI35_ADX20_BE1.0",    "tf": "5m", "adx": 20, "rsi_entry": 35, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": 1.0},
    {"name": "RSI45_ADX20_BE1.0",    "tf": "5m", "adx": 20, "rsi_entry": 45, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": 1.0},
    
    # Exp 10c: RSI en timeframe 15m
    {"name": "RSI40_ADX20_15m_NoBE", "tf": "15m", "adx": 20, "rsi_entry": 40, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": None},
    {"name": "RSI40_ADX20_15m_BE",   "tf": "15m", "adx": 20, "rsi_entry": 40, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": 1.0},
    
    # Exp 10d: Variaciones BE mult
    {"name": "RSI40_ADX20_BE0.8",    "tf": "5m", "adx": 20, "rsi_entry": 40, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": 0.8},
    {"name": "RSI40_ADX20_BE1.5",    "tf": "5m", "adx": 20, "rsi_entry": 40, "sl_mult": 1.5, "tp_mult": 3.0, "be_mult": 1.5},
]


async def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90

    print("\n" + "=" * 90)
    print("🧪 EXPERIMENTO 10: RSI Pullback + Breakeven Trail")
    print(f"   Período: {days} días | Símbolo: {SYMBOL}")
    print("=" * 90)

    # Cache de datos
    data_cache = {}
    results = []

    for cfg in CONFIGS:
        key = (cfg['tf'], days)
        if key not in data_cache:
            logger.info(f"📥 Descargando {days}d @ {cfg['tf']}...")
            try:
                df = await fetch_data(cfg['tf'], days)
                df = add_indicators(df)
                data_cache[key] = df
                logger.info(f"   ✅ {len(df)} velas con RSI")
            except Exception as e:
                logger.error(f"   ❌ {e}")
                continue

        df = data_cache[key]
        logger.info(f"🔬 {cfg['name']}...")
        result = run_experiment(df, cfg)
        results.append(result)

    # === TABLA ===
    print("\n" + "=" * 90)
    print("📊 RESULTADOS — Experimento 10")
    print("=" * 90)
    print(f"  Referencia: ADX20_EMA_Cross → PF=0.79 | WR=32.6% | 46 trades (Exp anterior)")
    print("-" * 90)
    print(f"{'Config':<28} {'#':>4} {'WR%':>6} {'PnL$':>10} {'PnL%':>7} {'DD':>6} {'Shrp':>6} {'PF':>6} {'R:R':>5} {'SL':>4} {'TP':>4} {'BE':>4}")
    print("-" * 90)

    for r in results:
        m = "🟢" if r['pf'] > 1.0 else "🟡" if r['pf'] > 0.8 else "🔴"
        print(
            f"{m} {r['name']:<25} "
            f"{r['trades']:>4} "
            f"{r['win_rate']:>5.1f}% "
            f"{r['pnl']:>+9.2f} "
            f"{r['pnl_pct']:>+6.1f}% "
            f"{r['max_dd']:>5.1f}% "
            f"{r['sharpe']:>+5.2f} "
            f"{r['pf']:>5.2f} "
            f"{r['avg_rr']:>4.2f} "
            f"{r['sl']:>4} "
            f"{r['tp']:>4} "
            f"{r['be']:>4}"
        )

    print("=" * 90)

    # Ganador
    profitable = [r for r in results if r['pf'] > 1.0 and r['trades'] >= 5]
    if profitable:
        best = max(profitable, key=lambda x: x['sharpe'])
        print(f"\n🏆 ¡¡¡PROBETA VERDE!!! {best['name']}")
        print(f"   Trades={best['trades']} | WR={best['win_rate']:.1f}% | PF={best['pf']:.2f} | Sharpe={best['sharpe']:.2f}")
        print(f"   PnL: ${best['pnl']:+,.2f} ({best['pnl_pct']:+.1f}%) | Max DD: {best['max_dd']:.1f}%")
        print(f"   Breakevens salvados: {best['be']} trades que habrían sido pérdidas 💪")
    else:
        best = max(results, key=lambda x: x['pf']) if results else None
        if best and best['trades'] > 0:
            bwr = 1 / (1 + best['avg_rr']) * 100 if best['avg_rr'] > 0 else 50
            print(f"\n🟡 Mejor: {best['name']} (PF={best['pf']:.2f})")
            print(f"   WR={best['win_rate']:.1f}% | Breakeven WR={bwr:.1f}% | Gap={bwr - best['win_rate']:+.1f}%")

    print("=" * 90 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

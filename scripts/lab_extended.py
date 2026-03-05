"""
Crypto-Trading-Bot4 — Laboratorio Extendido
=============================================
Banco de estrategias alternativas para comparar contra RSI35_ADX20.
Cuando tengamos datos de forward testing, comparamos cuál habría
funcionado mejor en el mismo período.

Estrategias probadas:
  A. RSI Pullback (ganador actual) — variaciones de threshold
  B. Stochastic RSI — oscilador más sensible
  C. MACD Histogram — momentum puro
  D. Bollinger Band Bounce — reversión a la media
  E. RSI + SL/TP ratio variations
  F. RSI sensibilidad (30, 25, 40, 45)

Uso:
  python scripts/lab_extended.py [DAYS]
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

logger = setup_logger("LAB2")

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


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Todos los indicadores para todos los experimentos."""
    df['EMA_200'] = ta.ema(df['close'], length=200)
    
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None:
        df['ADX_14'] = adx_df['ADX_14']
    
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    if atr is not None:
        df['ATR_14'] = atr

    # RSI
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    
    # Stochastic RSI
    stoch_rsi = ta.stochrsi(df['close'], length=14, rsi_length=14, k=3, d=3)
    if stoch_rsi is not None:
        df['STOCHRSI_K'] = stoch_rsi.iloc[:, 0]
        df['STOCHRSI_D'] = stoch_rsi.iloc[:, 1]

    # MACD
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_SIGNAL'] = macd.iloc[:, 1]
        df['MACD_HIST'] = macd.iloc[:, 2]

    # Bollinger Bands
    bb = ta.bbands(df['close'], length=20, std=2)
    if bb is not None:
        df['BB_LOWER'] = bb.iloc[:, 0]
        df['BB_MID'] = bb.iloc[:, 1]
        df['BB_UPPER'] = bb.iloc[:, 2]

    # Volume SMA
    df['VOL_SMA_20'] = df['volume'].rolling(window=20).mean()
    
    df.dropna(subset=['EMA_200', 'ADX_14', 'ATR_14', 'RSI_14'], inplace=True)
    return df


# =============================================
# SEÑALES DE ENTRADA POR ESTRATEGIA
# =============================================

def signal_rsi_pullback(closed, prev, config):
    """A: RSI Pullback (ganador actual)."""
    rsi_thresh = config.get('rsi_entry', 35)
    rsi_prev = prev.get('RSI_14', 50)
    rsi_now = closed.get('RSI_14', 50)
    if pd.isna(rsi_prev): rsi_prev = 50
    if pd.isna(rsi_now): rsi_now = 50
    return (rsi_prev < rsi_thresh) and (rsi_now > rsi_prev)


def signal_stoch_rsi(closed, prev, config):
    """B: Stochastic RSI cruce alcista en zona baja."""
    k = closed.get('STOCHRSI_K', 50)
    d = closed.get('STOCHRSI_D', 50)
    k_prev = prev.get('STOCHRSI_K', 50)
    d_prev = prev.get('STOCHRSI_D', 50)
    if any(pd.isna(x) for x in [k, d, k_prev, d_prev]):
        return False
    thresh = config.get('stoch_thresh', 20)
    return (k_prev <= d_prev) and (k > d) and (d < thresh)


def signal_macd_cross(closed, prev, config):
    """C: MACD Histogram se vuelve positivo (momentum alcista)."""
    hist = closed.get('MACD_HIST', 0)
    hist_prev = prev.get('MACD_HIST', 0)
    if pd.isna(hist) or pd.isna(hist_prev):
        return False
    return (hist_prev <= 0) and (hist > 0)


def signal_bb_bounce(closed, prev, config):
    """D: Precio toca Bollinger inferior y rebota."""
    bb_low = closed.get('BB_LOWER', 0)
    if pd.isna(bb_low) or bb_low == 0:
        return False
    prev_touched = prev.get('low', 0) <= prev.get('BB_LOWER', 0)
    now_above = closed['close'] > bb_low
    return prev_touched and now_above


SIGNAL_FUNCS = {
    'rsi': signal_rsi_pullback,
    'stoch': signal_stoch_rsi,
    'macd': signal_macd_cross,
    'bb': signal_bb_bounce,
}


# =============================================
# MOTOR DE BACKTEST GENÉRICO
# =============================================

def run_backtest(df: pd.DataFrame, config: dict) -> dict:
    """Backtest genérico: señal configurable + macro filtro."""
    balance = 10000.0
    initial = balance
    trades = []
    equity_curve = [balance]
    position = None
    
    adx_thresh = config.get('adx', 20)
    sl_mult = config.get('sl_mult', 1.5)
    tp_mult = config.get('tp_mult', 3.0)
    use_macro = config.get('use_macro', True)
    use_vol = config.get('use_vol', True)
    signal_type = config.get('signal_type', 'rsi')
    signal_func = SIGNAL_FUNCS[signal_type]

    for i in range(2, len(df)):
        closed = df.iloc[i - 1]
        prev = df.iloc[i - 2]
        current = df.iloc[i]

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

        # Filtros base
        adx_val = closed.get('ADX_14', 0)
        if pd.isna(adx_val): adx_val = 0
        
        macro_ok = (closed['close'] > closed['EMA_200']) if use_macro else True
        adx_ok = adx_val > adx_thresh
        vol_ok = (closed['volume'] > closed.get('VOL_SMA_20', 0)) if use_vol else True
        trigger = signal_func(closed, prev, config)

        if macro_ok and adx_ok and vol_ok and trigger:
            entry = current['open']
            atr = closed.get('ATR_14', 0)
            if not pd.isna(atr) and atr > 0 and entry > 0:
                sl_dist = atr * sl_mult
                tp_dist = atr * tp_mult
                risk_amt = balance * RISK_PCT
                amt = risk_amt / sl_dist
                max_amt = (balance * 0.95) / entry
                amt = min(amt, max_amt)
                if amt * entry >= 10:
                    position = {'entry': entry, 'amt': amt, 'sl': entry - sl_dist, 'tp': entry + tp_dist, 'idx': i}

        equity_curve.append(balance)

    if position:
        pnl = (df.iloc[-1]['close'] - position['entry']) * position['amt']
        balance += pnl
        trades.append({'pnl': pnl, 'reason': 'END', 'bars': len(df) - position['idx']})

    if not trades:
        return {'name': config['name'], 'trades': 0, 'win_rate': 0, 'pnl': 0,
                'pnl_pct': 0, 'max_dd': 0, 'sharpe': 0, 'pf': 0, 'avg_rr': 0, 'sl': 0, 'tp': 0}

    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max() * 100
    rets = np.diff(eq) / eq[:-1]
    tf_min = {'1m': 1, '5m': 5, '15m': 15, '1h': 60}
    bpy = (365.25 * 24 * 60) / tf_min.get(config.get('tf', '5m'), 5)
    sharpe = (np.mean(rets) / np.std(rets)) * np.sqrt(bpy) if np.std(rets) > 0 else 0
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 1
    pf = gp / gl if gl > 0 else 0
    avg_w = np.mean(wins) if wins else 0
    avg_l = abs(np.mean(losses)) if losses else 1
    rr = avg_w / avg_l if avg_l > 0 else 0

    return {
        'name': config['name'], 'trades': len(trades),
        'win_rate': len(wins) / len(trades) * 100,
        'pnl': sum(pnls), 'pnl_pct': (balance - initial) / initial * 100,
        'max_dd': dd, 'sharpe': sharpe, 'pf': pf, 'avg_rr': rr,
        'sl': len([t for t in trades if t['reason'] == 'SL']),
        'tp': len([t for t in trades if t['reason'] == 'TP']),
    }


# =============================================
# MATRIX DE EXPERIMENTOS
# =============================================

EXPERIMENTS = [
    # ── A: RSI Pullback variaciones (benchmark) ──
    {"name": "A1_RSI35_ADX20",       "signal_type": "rsi", "rsi_entry": 35, "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "A2_RSI30_ADX20",       "signal_type": "rsi", "rsi_entry": 30, "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "A3_RSI25_ADX20",       "signal_type": "rsi", "rsi_entry": 25, "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "A4_RSI40_ADX20",       "signal_type": "rsi", "rsi_entry": 40, "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "A5_RSI35_ADX15",       "signal_type": "rsi", "rsi_entry": 35, "adx": 15, "sl_mult": 1.5, "tp_mult": 3.0},
    
    # ── B: Stochastic RSI ──
    {"name": "B1_StochRSI20_ADX20",  "signal_type": "stoch", "stoch_thresh": 20, "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "B2_StochRSI30_ADX20",  "signal_type": "stoch", "stoch_thresh": 30, "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "B3_StochRSI20_ADX15",  "signal_type": "stoch", "stoch_thresh": 20, "adx": 15, "sl_mult": 1.5, "tp_mult": 3.0},
    
    # ── C: MACD Histogram ──
    {"name": "C1_MACD_ADX20",        "signal_type": "macd", "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "C2_MACD_ADX15",        "signal_type": "macd", "adx": 15, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "C3_MACD_NoVol",        "signal_type": "macd", "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0, "use_vol": False},
    
    # ── D: Bollinger Bounce ──
    {"name": "D1_BB_ADX20",          "signal_type": "bb", "adx": 20, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "D2_BB_ADX15",          "signal_type": "bb", "adx": 15, "sl_mult": 1.5, "tp_mult": 3.0},
    {"name": "D3_BB_NoMacro",        "signal_type": "bb", "adx": 15, "sl_mult": 1.5, "tp_mult": 3.0, "use_macro": False},
    
    # ── E: RSI35 con ratios SL/TP alternativos ──
    {"name": "E1_RSI35_SL1_TP2.5",   "signal_type": "rsi", "rsi_entry": 35, "adx": 20, "sl_mult": 1.0, "tp_mult": 2.5},
    {"name": "E2_RSI35_SL2_TP4",     "signal_type": "rsi", "rsi_entry": 35, "adx": 20, "sl_mult": 2.0, "tp_mult": 4.0},
    {"name": "E3_RSI35_SL1.5_TP4.5", "signal_type": "rsi", "rsi_entry": 35, "adx": 20, "sl_mult": 1.5, "tp_mult": 4.5},
    {"name": "E4_RSI35_SL2_TP3",     "signal_type": "rsi", "rsi_entry": 35, "adx": 20, "sl_mult": 2.0, "tp_mult": 3.0},
]


async def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    tf = sys.argv[2] if len(sys.argv) > 2 else "5m"

    print("\n" + "=" * 95)
    print("🧬 LABORATORIO EXTENDIDO — Banco de Estrategias Alternativas")
    print(f"   Período: {days}d | TF: {tf} | Símbolo: {SYMBOL}")
    print("=" * 95)

    logger.info(f"📥 Descargando {days}d @ {tf}...")
    df = await fetch_data(tf, days)
    df = add_all_indicators(df)
    logger.info(f"✅ {len(df)} velas con todos los indicadores")

    results = []
    for exp in EXPERIMENTS:
        exp['tf'] = tf
        logger.info(f"🔬 {exp['name']}...")
        result = run_backtest(df, exp)
        results.append(result)

    # Ordenar por Profit Factor
    results.sort(key=lambda x: x['pf'], reverse=True)

    print("\n" + "=" * 95)
    print("📊 RESULTADOS — Ordenados por Profit Factor")
    print("=" * 95)
    print(f"{'#':>2}  {'Config':<26} {'Trades':>6} {'WR%':>6} {'PnL$':>10} {'PnL%':>7} {'DD':>6} {'Shrp':>7} {'PF':>6} {'R:R':>5} {'SL':>4} {'TP':>4}")
    print("-" * 95)

    for i, r in enumerate(results, 1):
        m = "🟢" if r['pf'] > 1.0 else "🟡" if r['pf'] > 0.8 else "🔴"
        print(
            f"{i:>2}. {m} {r['name']:<23} "
            f"{r['trades']:>6} "
            f"{r['win_rate']:>5.1f}% "
            f"{r['pnl']:>+9.2f} "
            f"{r['pnl_pct']:>+6.1f}% "
            f"{r['max_dd']:>5.1f}% "
            f"{r['sharpe']:>+6.2f} "
            f"{r['pf']:>5.2f} "
            f"{r['avg_rr']:>4.2f} "
            f"{r['sl']:>4} "
            f"{r['tp']:>4}"
        )

    print("=" * 95)

    # Top 3
    profitable = [r for r in results if r['pf'] > 1.0 and r['trades'] >= 5]
    if profitable:
        print(f"\n🏆 TOP ESTRATEGIAS RENTABLES ({len(profitable)}):")
        for i, r in enumerate(profitable[:5], 1):
            print(f"   {i}. {r['name']} → PF={r['pf']:.2f} | Sharpe={r['sharpe']:+.2f} | PnL=${r['pnl']:+,.2f} | WR={r['win_rate']:.1f}%")
    else:
        print("\n🔴 Ninguna estrategia cruzó PF > 1.0")

    # Comparativa por familia
    families = {'A': 'RSI Pullback', 'B': 'Stoch RSI', 'C': 'MACD', 'D': 'Bollinger', 'E': 'SL/TP Ratio'}
    print(f"\n📋 RESUMEN POR FAMILIA:")
    for prefix, name in families.items():
        fam = [r for r in results if r['name'].startswith(prefix)]
        if fam:
            best = max(fam, key=lambda x: x['pf'])
            avg_pf = np.mean([r['pf'] for r in fam])
            print(f"   {name:.<20} Mejor: {best['name']} (PF={best['pf']:.2f}) | Media PF: {avg_pf:.2f}")

    print("=" * 95 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

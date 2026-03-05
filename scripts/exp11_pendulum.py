"""
Crypto-Trading-Bot4 — Experimento 11: "El Péndulo" (Mean Reversion)
====================================================================
Bot V2 diseñado para mercados LATERALES (ADX bajo).
Complemento ortogonal al V1 (RSI Pullback = tendencia).

Hipótesis: En rangos laterales, el precio actúa como una goma elástica.
           Si toca la Bollinger inferior → rebota al centro (SMA 20).

Entorno: ADX < threshold (mercado SIN tendencia)
Gatillo: Precio perfora BB inferior y rebota
Salida:  Precio toca BB media (SMA 20) — mordisco rápido
SL:      Debajo de BB inferior - 0.5× ATR

Variaciones:
  - BB std (2.0, 2.5)
  - ADX techo (15, 20, 25)
  - Con/sin filtro RSI (RSI < 30 para confirmar sobreventa)
  - SL distance variations

Uso:
  python scripts/exp11_pendulum.py [DAYS]
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

logger = setup_logger("EXP11")

SYMBOL = "BTC/USDT"
RISK_PCT = 0.01


async def fetch_data(tf: str, days: int) -> pd.DataFrame:
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
    """Indicadores para Mean Reversion."""
    # ADX (para detectar rango lateral)
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None:
        df['ADX_14'] = adx_df['ADX_14']
    
    # ATR (para el SL)
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    if atr is not None:
        df['ATR_14'] = atr

    # RSI (para confirmar sobreventa)
    df['RSI_14'] = ta.rsi(df['close'], length=14)

    # Bollinger Bands — 2.0 std
    bb2 = ta.bbands(df['close'], length=20, std=2.0)
    if bb2 is not None:
        df['BB_L_2'] = bb2.iloc[:, 0]
        df['BB_M'] = bb2.iloc[:, 1]    # SMA 20 (misma para ambos std)
        df['BB_U_2'] = bb2.iloc[:, 2]

    # Bollinger Bands — 2.5 std (más selectivo)
    bb25 = ta.bbands(df['close'], length=20, std=2.5)
    if bb25 is not None:
        df['BB_L_25'] = bb25.iloc[:, 0]
        df['BB_U_25'] = bb25.iloc[:, 2]

    df['VOL_SMA_20'] = df['volume'].rolling(window=20).mean()
    df.dropna(subset=['ADX_14', 'ATR_14', 'BB_L_2', 'BB_M', 'RSI_14'], inplace=True)
    return df


def run_pendulum(df: pd.DataFrame, config: dict) -> dict:
    """
    Backtest de Mean Reversion "El Péndulo".
    
    DIFERENCIA CLAVE vs V1:
    - Entramos cuando ADX es BAJO (lateral)
    - TP = BB media (SMA 20), no ATR fijo
    - Trades cortos y rápidos ("mordiscos")
    """
    balance = 10000.0
    initial = balance
    trades = []
    equity_curve = [balance]
    position = None  # {entry, amt, sl, tp_type, bb_mid_at_entry, idx}

    adx_max = config.get('adx_max', 20)
    bb_std = config.get('bb_std', 2.0)
    sl_mult = config.get('sl_mult', 0.5)  # ATR multiplier para SL bajo BB lower
    use_rsi = config.get('use_rsi', False)
    rsi_thresh = config.get('rsi_thresh', 30)

    bb_lower_col = f"BB_L_{int(bb_std)}" if bb_std == 2.0 else 'BB_L_25'

    for i in range(2, len(df)):
        closed = df.iloc[i - 1]
        prev = df.iloc[i - 2]
        current = df.iloc[i]

        # === POSICIÓN ABIERTA ===
        if position:
            # TP: Precio toca BB media (SMA 20) → salida rápida
            bb_mid_now = current.get('BB_M', position.get('bb_mid', 0))
            if current['high'] >= bb_mid_now:
                pnl = (bb_mid_now - position['entry']) * position['amt']
                balance += pnl
                trades.append({'pnl': pnl, 'reason': 'BB_MID', 'bars': i - position['idx']})
                position = None
            # SL: Hard stop
            elif current['low'] <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['amt']
                balance += pnl
                trades.append({'pnl': pnl, 'reason': 'SL', 'bars': i - position['idx']})
                position = None

            eq = balance + ((current['close'] - position['entry']) * position['amt']) if position else balance
            equity_curve.append(eq)
            continue

        # === EVALUAR SEÑAL ===
        adx_val = closed.get('ADX_14', 50)
        if pd.isna(adx_val): adx_val = 50
        
        bb_lower = closed.get(bb_lower_col, 0)
        bb_mid = closed.get('BB_M', 0)
        if pd.isna(bb_lower) or pd.isna(bb_mid) or bb_lower == 0:
            equity_curve.append(balance)
            continue

        # CONDICIÓN 1: Mercado LATERAL (ADX bajo)
        is_ranging = adx_val < adx_max

        # CONDICIÓN 2: Precio perforó BB inferior en la vela previa y rebota
        prev_touched = prev['low'] <= prev.get(bb_lower_col, 0)
        now_above = closed['close'] > bb_lower
        bb_bounce = prev_touched and now_above

        # CONDICIÓN 3 (opcional): RSI confirma sobreventa
        rsi_ok = True
        if use_rsi:
            rsi_val = closed.get('RSI_14', 50)
            if pd.isna(rsi_val): rsi_val = 50
            rsi_ok = rsi_val < rsi_thresh

        if is_ranging and bb_bounce and rsi_ok:
            entry = current['open']
            atr = closed.get('ATR_14', 0)
            if pd.isna(atr) or atr <= 0:
                equity_curve.append(balance)
                continue

            # SL: Debajo de BB inferior - sl_mult * ATR
            sl = bb_lower - (sl_mult * atr)
            sl_dist = entry - sl
            
            if sl_dist <= 0:
                equity_curve.append(balance)
                continue

            # Sizing (1% risk)
            risk_amt = balance * RISK_PCT
            amt = risk_amt / sl_dist
            max_amt = (balance * 0.95) / entry
            amt = min(amt, max_amt)

            if amt * entry >= 10:
                position = {
                    'entry': entry, 'amt': amt, 'sl': sl,
                    'bb_mid': bb_mid, 'idx': i,
                }

        equity_curve.append(balance)

    # Cerrar posición al final
    if position:
        pnl = (df.iloc[-1]['close'] - position['entry']) * position['amt']
        balance += pnl
        trades.append({'pnl': pnl, 'reason': 'END', 'bars': len(df) - position['idx']})

    # === MÉTRICAS ===
    if not trades:
        return {'name': config['name'], 'trades': 0, 'win_rate': 0, 'pnl': 0,
                'pnl_pct': 0, 'max_dd': 0, 'sharpe': 0, 'pf': 0, 'avg_rr': 0,
                'sl': 0, 'tp': 0, 'avg_bars': 0}

    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max() * 100
    rets = np.diff(eq) / eq[:-1]
    tf_min = {'1m': 1, '5m': 5, '15m': 15, '1h': 60}
    tf = config.get('tf', '5m')
    bpy = (365.25 * 24 * 60) / tf_min.get(tf, 5)
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
        'tp': len([t for t in trades if t['reason'] == 'BB_MID']),
        'avg_bars': np.mean([t['bars'] for t in trades]),
    }


# =============================================
# MATRIX DE EXPERIMENTOS
# =============================================

CONFIGS = [
    # Péndulo puro: BB bounce en rango (ADX < threshold)
    {"name": "P1_BB2_ADX<20",          "adx_max": 20, "bb_std": 2.0, "sl_mult": 0.5, "use_rsi": False},
    {"name": "P2_BB2_ADX<25",          "adx_max": 25, "bb_std": 2.0, "sl_mult": 0.5, "use_rsi": False},
    {"name": "P3_BB2_ADX<15",          "adx_max": 15, "bb_std": 2.0, "sl_mult": 0.5, "use_rsi": False},
    {"name": "P4_BB2.5_ADX<20",        "adx_max": 20, "bb_std": 2.5, "sl_mult": 0.5, "use_rsi": False},
    
    # Péndulo + RSI confirmation
    {"name": "P5_BB2_ADX<20_RSI30",    "adx_max": 20, "bb_std": 2.0, "sl_mult": 0.5, "use_rsi": True,  "rsi_thresh": 30},
    {"name": "P6_BB2_ADX<25_RSI35",    "adx_max": 25, "bb_std": 2.0, "sl_mult": 0.5, "use_rsi": True,  "rsi_thresh": 35},
    {"name": "P7_BB2.5_ADX<25_RSI35",  "adx_max": 25, "bb_std": 2.5, "sl_mult": 0.5, "use_rsi": True,  "rsi_thresh": 35},
    
    # Péndulo SL variations
    {"name": "P8_BB2_ADX<20_SL1.0",    "adx_max": 20, "bb_std": 2.0, "sl_mult": 1.0, "use_rsi": False},
    {"name": "P9_BB2_ADX<20_SL0.3",    "adx_max": 20, "bb_std": 2.0, "sl_mult": 0.3, "use_rsi": False},
    {"name": "P10_BB2_ADX<25_SL1.0",   "adx_max": 25, "bb_std": 2.0, "sl_mult": 1.0, "use_rsi": False},
]


async def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    tf = sys.argv[2] if len(sys.argv) > 2 else "5m"

    print("\n" + "=" * 95)
    print("🧬 EXPERIMENTO 11: EL PÉNDULO (Mean Reversion)")
    print(f"   Período: {days}d | TF: {tf} | Símbolo: {SYMBOL}")
    print("   Hipótesis: ADX BAJO + BB Bounce → Comprar suelo, vender en media")
    print("=" * 95)

    logger.info(f"📥 Descargando {days}d @ {tf}...")
    df = await fetch_data(tf, days)
    df = add_indicators(df)
    logger.info(f"✅ {len(df)} velas con indicadores")

    results = []
    for cfg in CONFIGS:
        cfg['tf'] = tf
        logger.info(f"🔬 {cfg['name']}...")
        result = run_pendulum(df, cfg)
        results.append(result)

    # Ordenar por PF
    results.sort(key=lambda x: x['pf'], reverse=True)

    print("\n" + "=" * 95)
    print("📊 RESULTADOS — El Péndulo (Ordenados por PF)")
    print("=" * 95)
    print(f"  Referencia V1: RSI35_ADX20 → PF=1.21 | Sharpe=+1.43 | PnL=$+238")
    print("-" * 95)
    print(f"{'#':>2}  {'Config':<28} {'#Tr':>4} {'WR%':>6} {'PnL$':>10} {'PnL%':>7} {'DD':>6} {'Shrp':>7} {'PF':>6} {'R:R':>5} {'SL':>4} {'TP':>4} {'AvgB':>5}")
    print("-" * 95)

    for i, r in enumerate(results, 1):
        m = "🟢" if r['pf'] > 1.0 else "🟡" if r['pf'] > 0.8 else "🔴"
        print(
            f"{i:>2}. {m} {r['name']:<25} "
            f"{r['trades']:>4} "
            f"{r['win_rate']:>5.1f}% "
            f"{r['pnl']:>+9.2f} "
            f"{r['pnl_pct']:>+6.1f}% "
            f"{r['max_dd']:>5.1f}% "
            f"{r['sharpe']:>+6.2f} "
            f"{r['pf']:>5.2f} "
            f"{r['avg_rr']:>4.2f} "
            f"{r['sl']:>4} "
            f"{r['tp']:>4} "
            f"{r['avg_bars']:>4.0f}"
        )

    print("=" * 95)

    profitable = [r for r in results if r['pf'] > 1.0 and r['trades'] >= 5]
    if profitable:
        best = max(profitable, key=lambda x: x['sharpe'])
        print(f"\n🏆 GANADOR PÉNDULO: {best['name']}")
        print(f"   PF={best['pf']:.2f} | Sharpe={best['sharpe']:+.2f} | PnL=${best['pnl']:+,.2f}")
        print(f"   Trades={best['trades']} | WR={best['win_rate']:.1f}% | Avg Hold={best['avg_bars']:.0f} velas")
        print(f"\n🧬 COMBO SUPER-BOT (V1 + V2):")
        print(f"   V1 (Tendencia): RSI35_ADX20     → ADX > 20 → Compra pullbacks")
        print(f"   V2 (Lateral):   {best['name']:<17} → ADX < {best['name'].split('ADX<')[1].split('_')[0] if 'ADX<' in best['name'] else '?'} → Compra Bollinger bounce")
        print(f"   → Fusión: Si ADX>20 → V1 | Si ADX<20 → V2")
    else:
        print("\n🔴 Ninguna config del Péndulo cruzó PF > 1.0 con >5 trades")

    print("=" * 95 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

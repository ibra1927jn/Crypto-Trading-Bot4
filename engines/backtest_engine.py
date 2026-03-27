"""
Crypto-Trading-Bot4 — Backtest Engine v3 (Sniper Rotativo)
===========================================================
Backtesting integrado multi-moneda con el mismo scoring del bot real.

Uso:
  python -m engines.backtest_engine                    # Default: 30 días, 5 monedas
  python -m engines.backtest_engine --days 90          # 90 días
  python -m engines.backtest_engine --coins XRP DOGE   # Solo 2 monedas
  python -m engines.backtest_engine --sweep            # Parameter sweep
"""

import asyncio
import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import pandas as pd
import pandas_ta as ta
import ccxt

from config.settings import (
    SYMBOLS, TIMEFRAME, EXCHANGE_ID,
    POSITION_RISK_PCT, RSI_EXTREME_THRESHOLD, RSI_EXIT_THRESHOLD,
    SL_PCT, TP_PCT, TRAIL_PCT, ATR_PERIOD, ADX_PERIOD, BB_PERIOD, BB_STD
)
from utils.logger import setup_logger

logger = setup_logger("BACKTEST")


# ═══════════════════════════════════════════════════════
# SCORING (idéntico al Alpha Engine real)
# ═══════════════════════════════════════════════════════

def _safe(row, col, default=0.0):
    val = row.get(col) if isinstance(row, dict) else (
        row[col] if col in row.index else None)
    return float(val) if val is not None and not pd.isna(val) else default


def score_buy(row, prev, rsi_threshold=None):
    """Score 0-100 — IDENTICO al Alpha Engine."""
    rsi_th = rsi_threshold or RSI_EXTREME_THRESHOLD
    rsi7 = _safe(row, 'RSI_7', 50)
    rsi7_prev = _safe(prev, 'RSI_7', 50)

    if rsi7 >= rsi_th or rsi7 <= rsi7_prev:
        return 0.0

    score = min((rsi_th - rsi7) * 2, 40)

    vol_r = _safe(row, 'VOL_RATIO', 1)
    if vol_r > 2.0:
        score += 20
    elif vol_r > 1.5:
        score += 15
    elif vol_r > 1.2:
        score += 10
    elif vol_r > 1.0:
        score += 5

    macd, macd_s = _safe(row, 'MACD', 0), _safe(row, 'MACD_S', 0)
    if macd > macd_s:
        score += 10

    stoch = _safe(row, 'STOCH_K', 50)
    if stoch < 20:
        score += 10
    elif stoch < 30:
        score += 5

    rsi14 = _safe(row, 'RSI_14', 50)
    if rsi14 < 30:
        score += 5
    elif rsi14 < 40:
        score += 2

    return score


# ═══════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════

class BacktestEngine:
    """
    Motor de backtesting integrado para el Sniper Rotativo.
    Simula EXACTAMENTE la lógica del bot real:
      - Vigila N monedas
      - Solo 1 posición a la vez
      - Score 0-100, compra la MEJOR
      - SL/TP/RSI exit + trailing
    """

    def __init__(self, initial_balance: float = 30.0):
        self.initial_balance = initial_balance
        self.exchange = None

    # ─── DATA ───

    def _init_exchange(self):
        if not self.exchange:
            self.exchange = ccxt.binance({
                'timeout': 30000,
                'enableRateLimit': True,
            })

    def fetch_data(self, symbols: List[str], timeframe: str = '1h',
                   days: int = 30) -> Dict[str, pd.DataFrame]:
        """Descarga datos históricos para N monedas."""
        self._init_exchange()
        data = {}

        for symbol in symbols:
            try:
                limit = min(days * (24 if timeframe == '1h' else
                              288 if timeframe == '5m' else 24), 1000)
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(ohlcv,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                df = df[~df.index.duplicated(keep='last')]
                self._add_indicators(df)
                data[symbol] = df
                logger.info(f"  ✅ {symbol}: {len(df)} velas")
            except Exception as e:
                logger.error(f"  ❌ {symbol}: {e}")

        return data

    def _add_indicators(self, df: pd.DataFrame):
        """Calcula indicadores — idénticos al Data Engine real."""
        df['RSI_14'] = ta.rsi(df['close'], length=14)
        df['RSI_7'] = ta.rsi(df['close'], length=7)

        for l in [5, 9, 13, 21, 50, 200]:
            ema = ta.ema(df['close'], l)
            if ema is not None:
                df[f'EMA_{l}'] = ema

        df['VOL_SMA_20'] = df['volume'].rolling(20).mean()
        df['VOL_RATIO'] = df['volume'] / df['VOL_SMA_20'].replace(0, 1e-10)

        mc = ta.macd(df['close'])
        if mc is not None:
            for px, nm in [('MACD_', 'MACD'), ('MACDs_', 'MACD_S')]:
                cc = [c for c in mc.columns if c.startswith(px)]
                if cc:
                    df[nm] = mc[cc[0]]

        st = ta.stoch(df['high'], df['low'], df['close'])
        if st is not None:
            sk = [c for c in st.columns if 'STOCHk' in c]
            if sk:
                df['STOCH_K'] = st[sk[0]]

        bb = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
        if bb is not None:
            for px, nm in [('BBL_', 'BB_LO'), ('BBM_', 'BB_MID'), ('BBU_', 'BB_HI')]:
                cc = [c for c in bb.columns if c.startswith(px)]
                if cc:
                    df[nm] = bb[cc[0]]

        atr = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
        if atr is not None:
            df['ATR_14'] = atr

        adx = ta.adx(df['high'], df['low'], df['close'], length=ADX_PERIOD)
        if adx is not None:
            ac = [c for c in adx.columns if c.startswith('ADX_')]
            if ac:
                df['ADX_14'] = adx[ac[0]]

    # ─── BACKTEST CORE ───

    def run(self, data: Dict[str, pd.DataFrame],
            sl_pct: float = None, tp_pct: float = None,
            rsi_entry: float = None, rsi_exit: float = None,
            trail_pct: float = None, position_pct: float = None,
            min_score: float = 20.0,
            verbose: bool = True) -> dict:
        """
        Ejecuta backtest Sniper Rotativo sobre datos multi-moneda.

        Returns dict con métricas completas.
        """
        sl = abs(sl_pct or SL_PCT)
        tp = abs(tp_pct or TP_PCT)
        rsi_e = rsi_entry or RSI_EXTREME_THRESHOLD
        rsi_x = rsi_exit or RSI_EXIT_THRESHOLD
        trail = trail_pct or TRAIL_PCT
        pos_pct = position_pct or (POSITION_RISK_PCT * 100)

        # Alinear timestamps
        coins = list(data.keys())
        common_ts = data[coins[0]].index
        for coin in coins[1:]:
            common_ts = common_ts.intersection(data[coin].index)

        if len(common_ts) < 60:
            return {'error': 'Insufficient common data'}

        bal = self.initial_balance
        pos = None
        trades = []
        peak = bal
        max_dd = 0
        equity_curve = []

        for i in range(60, len(common_ts)):
            ts = common_ts[i]

            if pos is not None:
                # ── MONITOR ──
                price = data[pos['coin']].loc[ts, 'close']
                rsi7 = _safe(data[pos['coin']].loc[ts], 'RSI_7', 50)

                # Trailing stop
                gain = (price - pos['entry']) / pos['entry'] * 100
                if gain > trail:
                    new_sl = price * (1 - trail / 100)
                    if new_sl > pos['sl']:
                        pos['sl'] = new_sl

                hit_sl = price <= pos['sl']
                hit_tp = price >= pos['tp']
                rsi_out = rsi7 > rsi_x

                if hit_sl or hit_tp or rsi_out:
                    pnl = (price - pos['entry']) * pos['amount']
                    bal += pnl
                    peak = max(peak, bal)
                    dd = (peak - bal) / peak * 100 if peak > 0 else 0
                    max_dd = max(max_dd, dd)

                    reason = 'SL' if hit_sl else ('TP' if hit_tp else 'RSI')
                    trades.append({
                        'coin': pos['coin'], 'pnl': pnl, 'reason': reason,
                        'pct': (price / pos['entry'] - 1) * 100,
                        'dur': i - pos['i'], 'bal': bal,
                        'entry': pos['entry'], 'exit': price,
                        'ts_entry': pos['ts'], 'ts_exit': ts,
                        'score': pos.get('score', 0),
                    })
                    pos = None
            else:
                # ── HUNT ──
                best_coin, best_score = None, 0
                for coin in coins:
                    row = data[coin].loc[ts]
                    prev = data[coin].loc[common_ts[i - 1]]
                    sc = score_buy(row, prev, rsi_e)
                    if sc > best_score:
                        best_score = sc
                        best_coin = coin

                if best_coin and best_score >= min_score:
                    price = data[best_coin].loc[ts, 'close']
                    amount = (bal * pos_pct / 100) / price
                    pos = {
                        'coin': best_coin, 'entry': price, 'amount': amount,
                        'sl': price * (1 - sl / 100),
                        'tp': price * (1 + tp / 100),
                        'i': i, 'ts': ts, 'score': best_score,
                    }

            equity_curve.append({'ts': ts, 'equity': bal if pos is None else
                bal + (data[pos['coin']].loc[ts, 'close'] - pos['entry']) * pos['amount']})

        # Close open position
        if pos:
            price = data[pos['coin']].iloc[-1]['close']
            pnl = (price - pos['entry']) * pos['amount']
            bal += pnl
            trades.append({
                'coin': pos['coin'], 'pnl': pnl, 'reason': 'END',
                'pct': 0, 'dur': 0, 'bal': bal,
                'entry': pos['entry'], 'exit': price,
                'ts_entry': pos['ts'], 'ts_exit': common_ts[-1],
                'score': pos.get('score', 0),
            })

        return self._calc_metrics(trades, equity_curve, common_ts, coins, data,
                                  bal, peak, max_dd, verbose)

    def _calc_metrics(self, trades, equity_curve, common_ts, coins, data,
                      final_bal, peak, max_dd, verbose) -> dict:
        """Calcula métricas de rendimiento."""
        days = max((common_ts[-1] - common_ts[60]).days, 1)
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]

        pnl = final_bal - self.initial_balance
        wr = len(wins) / max(len(trades), 1) * 100
        avg_win = sum(t['pnl'] for t in wins) / max(len(wins), 1)
        avg_loss = sum(abs(t['pnl']) for t in losses) / max(len(losses), 1)
        profit_factor = sum(t['pnl'] for t in wins) / max(
            sum(abs(t['pnl']) for t in losses), 0.01)

        # Buy & Hold comparison
        bh_returns = {}
        for coin in coins:
            df = data[coin]
            start_p = df.iloc[60]['close']
            end_p = df.iloc[-1]['close']
            bh_returns[coin] = (end_p / start_p - 1) * 100

        bh_avg = sum(bh_returns.values()) / max(len(bh_returns), 1)

        # Per-coin breakdown
        coin_stats = {}
        for coin in coins:
            ct = [t for t in trades if t['coin'] == coin]
            cw = [t for t in ct if t['pnl'] > 0]
            coin_stats[coin] = {
                'trades': len(ct),
                'wins': len(cw),
                'pnl': sum(t['pnl'] for t in ct),
                'wr': len(cw) / max(len(ct), 1) * 100,
                'bh': bh_returns.get(coin, 0),
            }

        # Exit reasons
        reasons = {}
        for reason in ['SL', 'TP', 'RSI', 'END']:
            rt = [t for t in trades if t['reason'] == reason]
            if rt:
                reasons[reason] = {
                    'count': len(rt),
                    'pnl': sum(t['pnl'] for t in rt),
                }

        metrics = {
            'initial': self.initial_balance,
            'final': final_bal,
            'pnl': pnl,
            'pnl_pct': (pnl / self.initial_balance) * 100,
            'days': days,
            'daily_pnl': pnl / days,
            'monthly_pnl': pnl / days * 30,
            'trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'wr': wr,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_dd': max_dd,
            'bh_avg': bh_avg,
            'coin_stats': coin_stats,
            'reasons': reasons,
            'equity_curve': equity_curve,
            'trades_list': trades,
        }

        if verbose:
            self.print_report(metrics)

        return metrics

    # ─── REPORT ───

    def print_report(self, m: dict):
        """Imprime reporte visual."""
        p = lambda msg: print(msg, flush=True)

        p("\n" + "=" * 70)
        p("📊 BACKTEST SNIPER ROTATIVO — REPORTE")
        p("=" * 70)
        p(f"   Capital:     ${m['initial']:.2f} → ${m['final']:.2f}")
        p(f"   PnL:         ${m['pnl']:+.2f} ({m['pnl_pct']:+.1f}%)")
        p(f"   Período:     {m['days']} días")
        p(f"   PnL/día:     ${m['daily_pnl']:.2f}")
        p(f"   PnL/mes:     ${m['monthly_pnl']:.2f}")
        p(f"   Max DD:      {m['max_dd']:.1f}%")

        p(f"\n   Trades:      {m['trades']}")
        p(f"   Ganados:     {m['wins']} ({m['wr']:.0f}%)")
        p(f"   Avg Win:     ${m['avg_win']:.2f}")
        p(f"   Avg Loss:    ${m['avg_loss']:.2f}")
        p(f"   P.Factor:    {m['profit_factor']:.2f}")
        p(f"   B&H Avg:     {m['bh_avg']:+.1f}%")

        p(f"\n   📊 Por moneda:")
        for coin, cs in m['coin_stats'].items():
            e = '🟢' if cs['pnl'] > 0 else ('⚪' if cs['trades'] == 0 else '🔴')
            p(f"   {coin:12s}: {cs['trades']:3d}T | {e} ${cs['pnl']:+.2f} | "
              f"WR:{cs['wr']:.0f}% | B&H:{cs['bh']:+.1f}%")

        if m['reasons']:
            p(f"\n   📊 Razones de cierre:")
            for reason, rs in m['reasons'].items():
                p(f"   {reason:4s}: {rs['count']:3d}T | ${rs['pnl']:+.2f}")

        # Projections
        d = m['daily_pnl']
        p(f"\n   📈 Proyecciones (manteniendo {m['wr']:.0f}% WR):")
        for cap_name, mult in [('$30', 1), ('$150', 5), ('$600', 20), ('$1,000', 33)]:
            p(f"   {cap_name:>6s}: ${d*mult:.2f}/día → ${d*mult*30:.2f}/mes")

        p("=" * 70)

    # ─── SWEEP ───

    def sweep(self, data: Dict[str, pd.DataFrame],
              configs: List[dict] = None) -> List[dict]:
        """Ejecuta sweep de parámetros y devuelve ranking."""
        if configs is None:
            configs = [
                {'rsi_entry': 25, 'sl_pct': 2, 'tp_pct': 3, 'label': 'RSI25 SL2/TP3'},
                {'rsi_entry': 25, 'sl_pct': 3, 'tp_pct': 5, 'label': 'RSI25 SL3/TP5'},
                {'rsi_entry': 30, 'sl_pct': 2, 'tp_pct': 3, 'label': 'RSI30 SL2/TP3'},
                {'rsi_entry': 30, 'sl_pct': 3, 'tp_pct': 5, 'label': 'RSI30 SL3/TP5'},
                {'rsi_entry': 30, 'sl_pct': 3, 'tp_pct': 6, 'label': 'RSI30 SL3/TP6'},
                {'rsi_entry': 30, 'sl_pct': 4, 'tp_pct': 8, 'label': 'RSI30 SL4/TP8'},
                {'rsi_entry': 30, 'sl_pct': 5, 'tp_pct': 10, 'label': 'RSI30 SL5/TP10'},
                {'rsi_entry': 35, 'sl_pct': 3, 'tp_pct': 5, 'label': 'RSI35 SL3/TP5'},
                {'rsi_entry': 35, 'sl_pct': 3, 'tp_pct': 6, 'label': 'RSI35 SL3/TP6'},
                {'rsi_entry': 35, 'sl_pct': 4, 'tp_pct': 8, 'label': 'RSI35 SL4/TP8'},
            ]

        results = []
        p = lambda msg: print(msg, flush=True)

        p(f"\n{'Config':<25s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s} | {'DD':>5s} | {'$/day':>6s}")
        p(f"{'-'*25}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}-+-{'-'*5}-+-{'-'*6}")

        for cfg in configs:
            m = self.run(data,
                         rsi_entry=cfg.get('rsi_entry'),
                         sl_pct=cfg.get('sl_pct'),
                         tp_pct=cfg.get('tp_pct'),
                         rsi_exit=cfg.get('rsi_exit'),
                         trail_pct=cfg.get('trail_pct'),
                         verbose=False)
            if 'error' in m:
                continue
            m['label'] = cfg.get('label', str(cfg))
            results.append(m)
            e = '🟢' if m['pnl'] > 0 else ('⚪' if m['trades'] == 0 else '🔴')
            p(f"{m['label']:<25s} | {e}${m['pnl']:+5.2f} | {m['trades']:3d} | "
              f"{m['wr']:3.0f}% | {m['max_dd']:4.1f}% | ${m['daily_pnl']:+.2f}")

        # Ranking
        results.sort(key=lambda x: x['pnl'], reverse=True)
        if results:
            p(f"\n🏆 MEJOR: {results[0]['label']} → ${results[0]['pnl']:+.2f}")

        return results


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='🎯 Backtest Sniper Rotativo')
    parser.add_argument('--days', type=int, default=30,
                        help='Días de datos (default: 30)')
    parser.add_argument('--coins', nargs='+', default=None,
                        help='Monedas (default: las 5 de settings)')
    parser.add_argument('--capital', type=float, default=30.0,
                        help='Capital inicial (default: 30)')
    parser.add_argument('--tf', default='1h',
                        help='Timeframe (default: 1h)')
    parser.add_argument('--sweep', action='store_true',
                        help='Ejecutar parameter sweep')
    parser.add_argument('--rsi', type=float, default=None,
                        help='RSI entry threshold')
    parser.add_argument('--sl', type=float, default=None,
                        help='Stop Loss %')
    parser.add_argument('--tp', type=float, default=None,
                        help='Take Profit %')

    args = parser.parse_args()
    coins = [f"{c}/USDT" if '/' not in c else c for c in (args.coins or SYMBOLS)]

    bt = BacktestEngine(initial_balance=args.capital)

    print(f"📥 Descargando datos: {', '.join(coins)} ({args.tf}, {args.days}d)")
    data = bt.fetch_data(coins, timeframe=args.tf, days=args.days)

    if not data:
        print("❌ No se pudieron descargar datos")
        return

    if args.sweep:
        bt.sweep(data)
    else:
        bt.run(data, rsi_entry=args.rsi, sl_pct=args.sl, tp_pct=args.tp)


if __name__ == "__main__":
    main()

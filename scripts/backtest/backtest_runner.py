#!/usr/bin/env python3
"""
Crypto-Trading-Bot4 — Backtest Runner con Scoring Engine
=========================================================
Descarga datos historicos via CCXT, simula trades usando el
ScoringEngine, y genera metricas completas en JSON.

Metricas: PnL, win rate, max drawdown, Sharpe ratio, profit factor.

Uso:
  python scripts/backtest/backtest_runner.py
  python scripts/backtest/backtest_runner.py --days 180 --tf 1h
  python scripts/backtest/backtest_runner.py --coins BTC/USDT ETH/USDT --capital 100
  python scripts/backtest/backtest_runner.py --output results.json
"""

import os
import sys
import json
import argparse
import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pandas as pd
import pandas_ta as ta
import ccxt

from engines.scoring_engine import ScoringEngine
from config.settings import (
    SYMBOLS, EXCHANGE_ID,
    SL_PCT, TP_PCT, TRAIL_PCT,
    ATR_PERIOD, ADX_PERIOD, BB_PERIOD, BB_STD,
)
from utils.logger import setup_logger

logger = setup_logger("BT_RUNNER")

# Configuracion por defecto
DEFAULT_DAYS = 180       # 6 meses
DEFAULT_TF = '1h'
DEFAULT_CAPITAL = 100.0
DEFAULT_MIN_SCORE = 40   # Score minimo para entrar
DEFAULT_SL = abs(SL_PCT)
DEFAULT_TP = abs(TP_PCT)
DEFAULT_TRAIL = TRAIL_PCT


class BacktestRunner:
    """
    Runner de backtesting que usa ScoringEngine para decidir entradas.
    Descarga datos de CCXT, simula trades, calcula metricas.
    """

    def __init__(
        self,
        capital: float = DEFAULT_CAPITAL,
        sl_pct: float = DEFAULT_SL,
        tp_pct: float = DEFAULT_TP,
        trail_pct: float = DEFAULT_TRAIL,
        min_score: int = DEFAULT_MIN_SCORE,
    ):
        self.initial_capital = capital
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.trail_pct = trail_pct
        self.min_score = min_score
        self.scorer = ScoringEngine()

    # ─── DESCARGA DE DATOS ───

    def fetch_data(
        self,
        symbols: List[str],
        timeframe: str = DEFAULT_TF,
        days: int = DEFAULT_DAYS,
    ) -> Dict[str, pd.DataFrame]:
        """Descarga OHLCV historico para N simbolos via CCXT."""
        exchange = ccxt.binance({
            'timeout': 30000,
            'enableRateLimit': True,
        })

        since = exchange.parse8601(
            (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        )

        data = {}
        for symbol in symbols:
            try:
                logger.info(f"Descargando {symbol} ({days}d, {timeframe})...")
                ohlcv = []
                current_since = since

                # Paginacion para obtener todos los datos
                while True:
                    batch = exchange.fetch_ohlcv(
                        symbol, timeframe,
                        since=current_since, limit=1000
                    )
                    if not batch:
                        break
                    ohlcv.extend(batch)
                    current_since = batch[-1][0] + 1
                    if len(batch) < 1000:
                        break

                df = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                df = df[~df.index.duplicated(keep='last')]

                self._add_indicators(df)
                data[symbol] = df
                logger.info(f"  {symbol}: {len(df)} velas descargadas")

            except Exception as e:
                logger.error(f"  Error descargando {symbol}: {e}")

        return data

    def _add_indicators(self, df: pd.DataFrame):
        """Calcula indicadores tecnicos sobre el DataFrame."""
        # RSI
        df['RSI_14'] = ta.rsi(df['close'], length=14)
        df['RSI_7'] = ta.rsi(df['close'], length=7)

        # EMAs
        for length in [9, 21, 50, 200]:
            ema = ta.ema(df['close'], length)
            if ema is not None:
                df[f'EMA_{length}'] = ema

        # Volumen ratio
        df['VOL_SMA_20'] = df['volume'].rolling(20).mean()
        df['VOL_RATIO'] = df['volume'] / df['VOL_SMA_20'].replace(0, 1e-10)

        # MACD
        mc = ta.macd(df['close'])
        if mc is not None:
            for prefix, name in [('MACD_', 'MACD'), ('MACDs_', 'MACD_S')]:
                cols = [c for c in mc.columns if c.startswith(prefix)]
                if cols:
                    df[name] = mc[cols[0]]
            hist_cols = [c for c in mc.columns if c.startswith('MACDh_')]
            if hist_cols:
                df['MACD_H'] = mc[hist_cols[0]]

        # Stochastic
        st = ta.stoch(df['high'], df['low'], df['close'])
        if st is not None:
            sk = [c for c in st.columns if 'STOCHk' in c]
            if sk:
                df['STOCH_K'] = st[sk[0]]

        # Bollinger Bands
        bb = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
        if bb is not None:
            for prefix, name in [('BBL_', 'BB_LO'), ('BBM_', 'BB_MID'), ('BBU_', 'BB_HI')]:
                cols = [c for c in bb.columns if c.startswith(prefix)]
                if cols:
                    df[name] = bb[cols[0]]

        # ATR
        atr = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
        if atr is not None:
            df['ATR_14'] = atr

        # ADX
        adx = ta.adx(df['high'], df['low'], df['close'], length=ADX_PERIOD)
        if adx is not None:
            ac = [c for c in adx.columns if c.startswith('ADX_')]
            if ac:
                df['ADX_14'] = adx[ac[0]]

    # ─── SIMULACION ───

    def run(
        self,
        data: Dict[str, pd.DataFrame],
        verbose: bool = True,
    ) -> dict:
        """
        Ejecuta backtest sobre datos multi-moneda con ScoringEngine.

        Logica:
          1. Solo 1 posicion abierta a la vez
          2. Escanea todas las monedas, puntua con ScoringEngine
          3. Entra en la mejor si score >= min_score
          4. Sale por SL, TP, trailing, o RSI exit
        """
        coins = list(data.keys())
        if not coins:
            return {'error': 'No hay datos para simular'}

        # Alinear timestamps comunes
        common_ts = data[coins[0]].index
        for coin in coins[1:]:
            common_ts = common_ts.intersection(data[coin].index)

        if len(common_ts) < 60:
            return {'error': 'Datos insuficientes (< 60 velas comunes)'}

        common_ts = common_ts.sort_values()
        balance = self.initial_capital
        position = None
        trades = []
        peak_balance = balance
        max_drawdown = 0.0
        equity_curve = []
        daily_returns = []
        prev_day_equity = balance

        for i in range(60, len(common_ts)):
            ts = common_ts[i]

            # Tracking diario para Sharpe
            current_day = ts.date() if hasattr(ts, 'date') else ts
            if i > 60:
                prev_ts = common_ts[i - 1]
                prev_day = prev_ts.date() if hasattr(prev_ts, 'date') else prev_ts
                if current_day != prev_day:
                    current_equity = balance
                    if position:
                        price_now = data[position['coin']].loc[ts, 'close']
                        current_equity += (price_now - position['entry']) * position['amount']
                    daily_ret = (current_equity - prev_day_equity) / max(prev_day_equity, 1e-10)
                    daily_returns.append(daily_ret)
                    prev_day_equity = current_equity

            if position is not None:
                # ── MONITOREAR POSICION ABIERTA ──
                price = data[position['coin']].loc[ts, 'close']
                high = data[position['coin']].loc[ts, 'high']
                low = data[position['coin']].loc[ts, 'low']

                # Trailing stop update
                gain_pct = (price - position['entry']) / position['entry'] * 100
                if gain_pct > self.trail_pct:
                    new_sl = price * (1 - self.trail_pct / 100)
                    if new_sl > position['sl']:
                        position['sl'] = new_sl

                # Verificar salida
                hit_sl = low <= position['sl']
                hit_tp = high >= position['tp']

                if hit_sl or hit_tp:
                    # Precio de salida: SL o TP segun cual se toco primero
                    exit_price = position['sl'] if hit_sl else position['tp']
                    pnl = (exit_price - position['entry']) * position['amount']
                    balance += pnl
                    peak_balance = max(peak_balance, balance)
                    dd = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0
                    max_drawdown = max(max_drawdown, dd)

                    trades.append({
                        'coin': position['coin'],
                        'entry_price': position['entry'],
                        'exit_price': exit_price,
                        'pnl': round(pnl, 4),
                        'pnl_pct': round((exit_price / position['entry'] - 1) * 100, 2),
                        'reason': 'SL' if hit_sl else 'TP',
                        'score': position['score'],
                        'duration_bars': i - position['bar_idx'],
                        'entry_time': str(position['ts']),
                        'exit_time': str(ts),
                        'balance_after': round(balance, 4),
                    })
                    position = None

            else:
                # ── BUSCAR NUEVA ENTRADA ──
                best_coin = None
                best_score = 0
                best_result = None

                for coin in coins:
                    row = data[coin].loc[ts]
                    prev_row = data[coin].loc[common_ts[i - 1]]

                    # Convertir row a formato ScoringEngine
                    market_data = ScoringEngine.from_dataframe_row(row, prev_row)
                    result = self.scorer.score(market_data)

                    if result['score'] > best_score:
                        best_score = result['score']
                        best_coin = coin
                        best_result = result

                if best_coin and best_score >= self.min_score:
                    price = data[best_coin].loc[ts, 'close']
                    amount = (balance * 0.90) / price  # 90% de capital
                    position = {
                        'coin': best_coin,
                        'entry': price,
                        'amount': amount,
                        'sl': price * (1 - self.sl_pct / 100),
                        'tp': price * (1 + self.tp_pct / 100),
                        'bar_idx': i,
                        'ts': ts,
                        'score': best_score,
                        'signals': best_result['signals'],
                    }

            # Registrar equity
            equity = balance
            if position:
                mark_price = data[position['coin']].loc[ts, 'close']
                equity += (mark_price - position['entry']) * position['amount']
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})

        # Cerrar posicion abierta al final
        if position:
            price = data[position['coin']].iloc[-1]['close']
            pnl = (price - position['entry']) * position['amount']
            balance += pnl
            trades.append({
                'coin': position['coin'],
                'entry_price': position['entry'],
                'exit_price': price,
                'pnl': round(pnl, 4),
                'pnl_pct': round((price / position['entry'] - 1) * 100, 2),
                'reason': 'END',
                'score': position['score'],
                'duration_bars': len(common_ts) - position['bar_idx'],
                'entry_time': str(position['ts']),
                'exit_time': str(common_ts[-1]),
                'balance_after': round(balance, 4),
            })

        return self._calculate_metrics(
            trades, equity_curve, daily_returns,
            balance, peak_balance, max_drawdown,
            common_ts, coins, data, verbose
        )

    def _calculate_metrics(
        self, trades, equity_curve, daily_returns,
        final_balance, peak_balance, max_drawdown,
        common_ts, coins, data, verbose
    ) -> dict:
        """Calcula metricas completas del backtest."""
        total_pnl = final_balance - self.initial_capital
        total_trades = len(trades)
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]

        win_rate = len(wins) / max(total_trades, 1) * 100
        avg_win = sum(t['pnl'] for t in wins) / max(len(wins), 1)
        avg_loss = sum(abs(t['pnl']) for t in losses) / max(len(losses), 1)

        # Profit Factor
        gross_profit = sum(t['pnl'] for t in wins)
        gross_loss = sum(abs(t['pnl']) for t in losses)
        profit_factor = gross_profit / max(gross_loss, 0.01)

        # Sharpe Ratio (anualizado, asumiendo ~252 dias de trading)
        sharpe_ratio = 0.0
        if daily_returns and len(daily_returns) > 1:
            avg_daily_ret = sum(daily_returns) / len(daily_returns)
            std_daily_ret = (
                sum((r - avg_daily_ret) ** 2 for r in daily_returns)
                / (len(daily_returns) - 1)
            ) ** 0.5
            if std_daily_ret > 0:
                sharpe_ratio = (avg_daily_ret / std_daily_ret) * math.sqrt(252)

        # Duracion del periodo
        days = max((common_ts[-1] - common_ts[60]).days, 1)

        # Buy & Hold para comparacion
        bh_returns = {}
        for coin in coins:
            df = data[coin]
            start_p = df.iloc[60]['close']
            end_p = df.iloc[-1]['close']
            bh_returns[coin] = round((end_p / start_p - 1) * 100, 2)

        bh_avg = sum(bh_returns.values()) / max(len(bh_returns), 1)

        # Estadisticas por moneda
        coin_stats = {}
        for coin in coins:
            ct = [t for t in trades if t['coin'] == coin]
            cw = [t for t in ct if t['pnl'] > 0]
            coin_stats[coin] = {
                'trades': len(ct),
                'wins': len(cw),
                'pnl': round(sum(t['pnl'] for t in ct), 4),
                'win_rate': round(len(cw) / max(len(ct), 1) * 100, 1),
                'buy_hold_pct': bh_returns.get(coin, 0),
            }

        # Razon de cierre
        exit_reasons = {}
        for reason in ['SL', 'TP', 'END']:
            rt = [t for t in trades if t['reason'] == reason]
            if rt:
                exit_reasons[reason] = {
                    'count': len(rt),
                    'pnl': round(sum(t['pnl'] for t in rt), 4),
                }

        metrics = {
            'summary': {
                'initial_capital': self.initial_capital,
                'final_balance': round(final_balance, 4),
                'total_pnl': round(total_pnl, 4),
                'total_pnl_pct': round(total_pnl / self.initial_capital * 100, 2),
                'period_days': days,
                'daily_pnl': round(total_pnl / days, 4),
                'monthly_pnl': round(total_pnl / days * 30, 4),
            },
            'performance': {
                'total_trades': total_trades,
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': round(win_rate, 1),
                'avg_win': round(avg_win, 4),
                'avg_loss': round(avg_loss, 4),
                'profit_factor': round(profit_factor, 2),
                'max_drawdown_pct': round(max_drawdown, 2),
                'sharpe_ratio': round(sharpe_ratio, 2),
            },
            'comparison': {
                'buy_hold_avg_pct': round(bh_avg, 2),
                'buy_hold_by_coin': bh_returns,
                'bot_vs_bh_pct': round(
                    total_pnl / self.initial_capital * 100 - bh_avg, 2
                ),
            },
            'config': {
                'sl_pct': self.sl_pct,
                'tp_pct': self.tp_pct,
                'trail_pct': self.trail_pct,
                'min_score': self.min_score,
                'exchange': EXCHANGE_ID,
            },
            'coin_stats': coin_stats,
            'exit_reasons': exit_reasons,
            'trades': trades,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        if verbose:
            self._print_report(metrics)

        return metrics

    def _print_report(self, m: dict):
        """Imprime reporte visual del backtest."""
        s = m['summary']
        p = m['performance']
        c = m['comparison']

        print("\n" + "=" * 65)
        print("  BACKTEST RUNNER — Scoring Engine Results")
        print("=" * 65)
        print(f"  Capital:      ${s['initial_capital']:.2f} -> ${s['final_balance']:.2f}")
        print(f"  PnL:          ${s['total_pnl']:+.2f} ({s['total_pnl_pct']:+.1f}%)")
        print(f"  Periodo:      {s['period_days']} dias")
        print(f"  PnL/dia:      ${s['daily_pnl']:.4f}")
        print(f"  PnL/mes:      ${s['monthly_pnl']:.2f}")

        print(f"\n  Trades:       {p['total_trades']}")
        print(f"  Win Rate:     {p['win_rate']:.1f}%")
        print(f"  Avg Win:      ${p['avg_win']:.4f}")
        print(f"  Avg Loss:     ${p['avg_loss']:.4f}")
        print(f"  P.Factor:     {p['profit_factor']:.2f}")
        print(f"  Max Drawdown: {p['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe Ratio: {p['sharpe_ratio']:.2f}")

        print(f"\n  B&H Avg:      {c['buy_hold_avg_pct']:+.1f}%")
        print(f"  Bot vs B&H:   {c['bot_vs_bh_pct']:+.1f}%")

        print(f"\n  Por moneda:")
        for coin, cs in m['coin_stats'].items():
            icon = '+' if cs['pnl'] > 0 else ('-' if cs['pnl'] < 0 else '=')
            print(
                f"    {coin:12s}: {cs['trades']:3d}T | "
                f"[{icon}] ${cs['pnl']:+.2f} | "
                f"WR:{cs['win_rate']:.0f}% | "
                f"B&H:{cs['buy_hold_pct']:+.1f}%"
            )

        if m['exit_reasons']:
            print(f"\n  Razones de salida:")
            for reason, rs in m['exit_reasons'].items():
                print(f"    {reason:4s}: {rs['count']:3d} trades | ${rs['pnl']:+.2f}")

        print("=" * 65)


# ── CLI ──
def main():
    parser = argparse.ArgumentParser(
        description='Backtest Runner con Scoring Engine'
    )
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS,
                        help=f'Dias de datos historicos (default: {DEFAULT_DAYS})')
    parser.add_argument('--tf', default=DEFAULT_TF,
                        help=f'Timeframe (default: {DEFAULT_TF})')
    parser.add_argument('--coins', nargs='+', default=None,
                        help='Simbolos (default: los de settings.py)')
    parser.add_argument('--capital', type=float, default=DEFAULT_CAPITAL,
                        help=f'Capital inicial (default: {DEFAULT_CAPITAL})')
    parser.add_argument('--min-score', type=int, default=DEFAULT_MIN_SCORE,
                        help=f'Score minimo para entrada (default: {DEFAULT_MIN_SCORE})')
    parser.add_argument('--sl', type=float, default=DEFAULT_SL,
                        help=f'Stop Loss %% (default: {DEFAULT_SL})')
    parser.add_argument('--tp', type=float, default=DEFAULT_TP,
                        help=f'Take Profit %% (default: {DEFAULT_TP})')
    parser.add_argument('--output', type=str, default=None,
                        help='Guardar resultados en archivo JSON')
    parser.add_argument('--quiet', action='store_true',
                        help='Solo output JSON, sin reporte visual')

    args = parser.parse_args()

    coins = args.coins or SYMBOLS
    coins = [f"{c}/USDT" if '/' not in c else c for c in coins]

    runner = BacktestRunner(
        capital=args.capital,
        sl_pct=args.sl,
        tp_pct=args.tp,
        min_score=args.min_score,
    )

    print(f"Descargando datos: {', '.join(coins)} ({args.tf}, {args.days}d)")
    data = runner.fetch_data(coins, timeframe=args.tf, days=args.days)

    if not data:
        print("Error: no se pudieron descargar datos")
        sys.exit(1)

    results = runner.run(data, verbose=not args.quiet)

    if 'error' in results:
        print(f"Error: {results['error']}")
        sys.exit(1)

    # Guardar JSON si se pidio
    output_path = args.output
    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'logs', f'backtest_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )

    # Remover equity_curve del JSON (muy grande)
    output_data = {k: v for k, v in results.items() if k != 'equity_curve'}

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, default=str)

    print(f"\nResultados guardados en: {output_path}")


if __name__ == "__main__":
    main()

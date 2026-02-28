"""
Crypto-Trading-Bot4 — Backtesting Engine
=========================================
Simula la estrategia sobre datos históricos para medir:
  - Win Rate, Total PnL, Max Drawdown
  - Sharpe Ratio, Profit Factor
  - R:R promedio, Racha ganadora/perdedora

Usa los mismos indicadores y reglas del Alpha Engine real.
CERO repainting: siempre evalúa sobre la vela cerrada (iloc[-2]).

Uso:
  python -m engines.backtest_engine
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
from config.settings import (
    SYMBOL, TIMEFRAME, EXCHANGE_ID,
    POSITION_RISK_PCT, ATR_PERIOD, ADX_PERIOD
)
from utils.logger import setup_logger

logger = setup_logger("BACKTEST")


class BacktestEngine:
    """
    Motor de backtesting vectorizado.
    
    Descarga datos históricos, aplica indicadores, simula la estrategia
    y calcula métricas de rendimiento institucional.
    """

    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.trades = []
        self.equity_curve = []
        self.position = None  # {'entry_price', 'amount', 'sl', 'tp', 'entry_idx'}

    async def fetch_historical_data(self, days: int = 90) -> pd.DataFrame:
        """Descarga datos OHLCV históricos del exchange."""
        logger.info(f"📥 Descargando {days} días de {SYMBOL} ({TIMEFRAME})...")

        exchange = ccxt.binance({
            'enableRateLimit': True,
            'timeout': 30000,  # 30s timeout for large fetches
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
                            SYMBOL, TIMEFRAME, since=since, limit=1000
                        )
                        break
                    except Exception as e:
                        if attempt < 2:
                            logger.warning(f"  ⚠️ Retry {attempt+1}/3: {e}")
                            await asyncio.sleep(2 * (attempt + 1))
                        else:
                            logger.error(f"  ❌ Failed after 3 retries: {e}")
                            raise
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                
                if batch % 5 == 0:
                    logger.info(f"  ... {len(all_ohlcv):,} velas descargadas")
                
                if len(ohlcv) < 1000:
                    break
                
                await asyncio.sleep(0.3)  # Rate limiting
        finally:
            await exchange.close()

        df = pd.DataFrame(
            all_ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df = df[~df.index.duplicated(keep='last')]
        
        logger.info(f"✅ Descargadas {len(df)} velas ({df.index[0]} → {df.index[-1]})")
        return df

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula los mismos indicadores que el Data Engine real."""
        logger.info("📊 Calculando indicadores...")

        df['EMA_200'] = ta.ema(df['close'], length=200)
        df['EMA_9'] = ta.ema(df['close'], length=9)
        df['EMA_21'] = ta.ema(df['close'], length=21)
        
        adx_df = ta.adx(df['high'], df['low'], df['close'], length=ADX_PERIOD)
        if adx_df is not None:
            df['ADX_14'] = adx_df[f'ADX_{ADX_PERIOD}']

        atr = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
        if atr is not None:
            df['ATRr_14'] = atr

        df['VOL_SMA_20'] = df['volume'].rolling(window=20).mean()
        
        # Dropear filas sin indicadores completos
        df.dropna(subset=['EMA_200', 'ADX_14', 'ATRr_14'], inplace=True)
        
        logger.info(f"✅ Indicadores calculados. {len(df)} velas útiles.")
        return df

    def run_backtest(self, df: pd.DataFrame) -> dict:
        """
        Simula la estrategia sobre datos históricos.
        
        REGLA ANTI-REPAINTING: Evalúa sobre i-1 (la vela cerrada),
        nunca sobre la vela viva i.
        """
        logger.info("🚀 Ejecutando backtest...")
        
        self.balance = self.initial_balance
        self.trades = []
        self.equity_curve = [self.initial_balance]
        self.position = None

        for i in range(2, len(df)):
            closed = df.iloc[i - 1]   # Vela cerrada (anti-repainting)
            prev = df.iloc[i - 2]     # Vela anterior
            current = df.iloc[i]      # Vela actual (donde se ejecutaría)

            # Si tenemos posición → chequear SL/TP hit
            if self.position:
                self._check_sl_tp(current, i)
                self.equity_curve.append(self._calc_equity(current['close']))
                continue

            # EVALUAR LAS 4 LEYES (igual que Alpha Engine real)
            signal = self._evaluate_signal(closed, prev)

            if signal == 'BUY':
                self._open_position(current, closed, i)

            self.equity_curve.append(self._calc_equity(current['close']))

        # Cerrar posición abierta al final
        if self.position:
            self._close_position(df.iloc[-1]['close'], len(df)-1, 'END')

        return self._calculate_metrics(df)

    def _evaluate_signal(self, closed, prev) -> str:
        """Las 4 leyes del Alpha Engine — idénticas al bot real."""
        if pd.isna(closed.get('EMA_200')) or pd.isna(closed.get('ADX_14')):
            return 'HOLD'

        macro = closed['close'] > closed['EMA_200']
        strong = closed['ADX_14'] > 25
        volume = closed['volume'] > closed.get('VOL_SMA_20', 0)
        cross = (
            prev.get('EMA_9', 0) <= prev.get('EMA_21', 0) and
            closed.get('EMA_9', 0) > closed.get('EMA_21', 0)
        )

        if macro and strong and volume and cross:
            return 'BUY'
        return 'HOLD'

    def _open_position(self, current, closed, idx):
        """Abre posición simulada con ATR sizing."""
        entry = current['open']  # Entrada al open de la siguiente vela
        atr = closed.get('ATRr_14', 0)
        
        if atr <= 0:
            return

        sl_distance = atr * 1.5
        tp_distance = atr * 3.0
        
        capital_at_risk = self.balance * POSITION_RISK_PCT
        amount = capital_at_risk / sl_distance
        max_amount = (self.balance * 0.95) / entry
        amount = min(amount, max_amount)

        if amount * entry < 10:  # Min notional
            return

        self.position = {
            'entry_price': entry,
            'amount': amount,
            'sl': entry - sl_distance,
            'tp': entry + tp_distance,
            'entry_idx': idx,
        }

    def _check_sl_tp(self, candle, idx):
        """Verifica si el SL o TP fue tocado en esta vela."""
        if not self.position:
            return

        # SL hit (low <= sl)
        if candle['low'] <= self.position['sl']:
            self._close_position(self.position['sl'], idx, 'SL')
        # TP hit (high >= tp)
        elif candle['high'] >= self.position['tp']:
            self._close_position(self.position['tp'], idx, 'TP')

    def _close_position(self, exit_price, idx, reason):
        """Cierra posición y registra trade."""
        pos = self.position
        pnl = (exit_price - pos['entry_price']) * pos['amount']
        pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
        
        self.balance += pnl
        self.trades.append({
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'amount': pos['amount'],
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'reason': reason,
            'holding_bars': idx - pos['entry_idx'],
        })
        self.position = None

    def _calc_equity(self, current_price):
        """Calcula equity total incluyendo posición abierta."""
        if self.position:
            unrealized = (current_price - self.position['entry_price']) * self.position['amount']
            return self.balance + unrealized
        return self.balance

    def _calculate_metrics(self, df) -> dict:
        """Calcula métricas de rendimiento institucional."""
        if not self.trades:
            return {"error": "No trades executed"}

        pnls = [t['pnl'] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        # Equity curve stats
        eq = np.array(self.equity_curve)
        peak = np.maximum.accumulate(eq)
        drawdowns = (peak - eq) / peak
        max_dd = drawdowns.max()

        # Sharpe Ratio (anualizado)
        returns = np.diff(eq) / eq[:-1]
        sharpe = 0
        if len(returns) > 1 and np.std(returns) > 0:
            # Anualizar según timeframe
            tf_minutes = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
            bars_per_year = (365.25 * 24 * 60) / tf_minutes.get(TIMEFRAME, 5)
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(bars_per_year)

        # Profit Factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Rachas
        streak_w = streak_l = max_streak_w = max_streak_l = 0
        for p in pnls:
            if p > 0:
                streak_w += 1
                streak_l = 0
                max_streak_w = max(max_streak_w, streak_w)
            else:
                streak_l += 1
                streak_w = 0
                max_streak_l = max(max_streak_l, streak_l)

        # Avg R:R
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 1
        avg_rr = avg_win / avg_loss if avg_loss > 0 else 0

        metrics = {
            'period': f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}",
            'total_bars': len(df),
            'total_trades': len(self.trades),
            'win_rate': len(wins) / len(self.trades) * 100 if self.trades else 0,
            'total_pnl': sum(pnls),
            'total_pnl_pct': (self.balance - self.initial_balance) / self.initial_balance * 100,
            'final_balance': self.balance,
            'max_drawdown': max_dd * 100,
            'sharpe_ratio': sharpe,
            'profit_factor': profit_factor,
            'avg_rr': avg_rr,
            'avg_win': avg_win,
            'avg_loss': -abs(np.mean(losses)) if losses else 0,
            'max_streak_win': max_streak_w,
            'max_streak_loss': max_streak_l,
            'avg_holding_bars': np.mean([t['holding_bars'] for t in self.trades]),
            'wins_by_sl': len([t for t in self.trades if t['reason'] == 'SL']),
            'wins_by_tp': len([t for t in self.trades if t['reason'] == 'TP']),
        }

        return metrics

    def print_report(self, metrics: dict):
        """Imprime reporte de rendimiento estandarizado."""
        print("\n" + "=" * 60)
        print("🧪 BACKTEST REPORT — Trend-Momentum Híbrido")
        print("=" * 60)
        print(f"  Período:        {metrics['period']}")
        print(f"  Velas:          {metrics['total_bars']:,}")
        print(f"  Trades:         {metrics['total_trades']}")
        print("-" * 60)
        print(f"  💰 PnL Total:   ${metrics['total_pnl']:+,.2f} ({metrics['total_pnl_pct']:+.1f}%)")
        print(f"  📊 Balance:     ${metrics['final_balance']:,.2f}")
        print(f"  🏆 Win Rate:    {metrics['win_rate']:.1f}%")
        print(f"  📐 Avg R:R:     {metrics['avg_rr']:.2f}")
        print(f"  💵 Avg Win:     ${metrics['avg_win']:+,.2f}")
        print(f"  💸 Avg Loss:    ${metrics['avg_loss']:,.2f}")
        print("-" * 60)
        print(f"  📉 Max DD:      {metrics['max_drawdown']:.1f}%")
        print(f"  📈 Sharpe:      {metrics['sharpe_ratio']:.2f}")
        print(f"  ⚖️ Profit F:    {metrics['profit_factor']:.2f}")
        print(f"  🔥 Best Streak: {metrics['max_streak_win']}W / {metrics['max_streak_loss']}L")
        print(f"  ⏱️ Avg Hold:    {metrics['avg_holding_bars']:.0f} velas")
        print(f"  🎯 Exits:       SL={metrics['wins_by_sl']} / TP={metrics['wins_by_tp']}")
        print("=" * 60)

        # Verdicto
        if metrics['sharpe_ratio'] > 1.5 and metrics['win_rate'] > 45:
            print("  ✅ VEREDICTO: Estrategia RENTABLE — luz verde para producción")
        elif metrics['sharpe_ratio'] > 0.5:
            print("  🟡 VEREDICTO: Estrategia ACEPTABLE — necesita optimización")
        else:
            print("  🔴 VEREDICTO: Estrategia DEFICIENTE — no operar en vivo")
        print("=" * 60 + "\n")


async def main():
    """Ejecuta el backtest completo."""
    bt = BacktestEngine(initial_balance=10000.0)
    
    # Descargar datos (30 días para test rápido, subir a 90/180 despues)
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    df = await bt.fetch_historical_data(days=days)
    
    # Calcular indicadores
    df = bt.calculate_indicators(df)
    
    # Ejecutar backtest
    metrics = bt.run_backtest(df)
    
    # Imprimir reporte
    bt.print_report(metrics)
    
    return metrics


if __name__ == "__main__":
    asyncio.run(main())

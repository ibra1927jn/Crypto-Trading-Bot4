"""
🏟️ BOT ARENA — Laboratorio Ciego de Mejoras
=============================================
Simula N variantes del bot sobre los mismos datos históricos,
vela por vela, sin conocer el futuro. Cada bot decide en tiempo
real como si estuviera en producción.

Soporta: LONG + SHORT, multi-posición (3 max), OVERRIDE,
         trailing stop, timeout, blacklist, scoring dual.

Uso:
  python scripts/lab_arena.py                    # 30 días, 20 coins
  python scripts/lab_arena.py --days 90          # 90 días
  python scripts/lab_arena.py --days 7 --fast    # Rápido, pocas coins
"""

import sys, time, argparse, copy
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd
import pandas_ta as ta
import numpy as np
import ccxt

def p(msg): print(msg, flush=True)

# ═══════════════════════════════════════════════════════
# COINS (mismas que el bot live)
# ═══════════════════════════════════════════════════════

COINS_FULL = [
    'DOGE/USDT', 'XRP/USDT', 'ADA/USDT', 'GALA/USDT', 'CHZ/USDT',
    'JASMY/USDT', 'FLOKI/USDT', 'PEPE/USDT', 'BONK/USDT', 'WIF/USDT',
    'HUMA/USDT', 'MBOX/USDT', 'COS/USDT', 'DEGO/USDT', 'BABY/USDT',
    'RESOLV/USDT', 'PLUME/USDT', 'SIGN/USDT', 'FLOW/USDT', 'SXT/USDT',
]

COINS_FAST = [
    'DOGE/USDT', 'XRP/USDT', 'FLOW/USDT', 'GALA/USDT', 'CHZ/USDT',
    'FLOKI/USDT', 'PEPE/USDT', 'BONK/USDT',
]

# Coin groups for correlation filter
COIN_GROUPS = {
    'DOGE/USDT': 'meme', 'FLOKI/USDT': 'meme', 'PEPE/USDT': 'meme',
    'BONK/USDT': 'meme', 'WIF/USDT': 'meme', 'BABY/USDT': 'meme',
    'XRP/USDT': 'L1', 'ADA/USDT': 'L1', 'FLOW/USDT': 'L1', 'SXT/USDT': 'L1',
    'GALA/USDT': 'gaming', 'CHZ/USDT': 'gaming', 'JASMY/USDT': 'gaming',
    'HUMA/USDT': 'defi', 'MBOX/USDT': 'defi', 'DEGO/USDT': 'defi',
    'COS/USDT': 'small', 'RESOLV/USDT': 'small', 'PLUME/USDT': 'small',
    'SIGN/USDT': 'small',
}

# Dead hours UTC (low volume, bad fills)
DEAD_HOURS = {4, 5, 6, 7}


# ═══════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════

def download_data(coins: List[str], days: int = 30, tf: str = '1h') -> Dict[str, pd.DataFrame]:
    """Descarga datos históricos. Devuelve {symbol: DataFrame}."""
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    data = {}

    for symbol in coins:
        try:
            limit = min(days * 24, 1000) if tf == '1h' else min(days * 288, 1000)
            ohlcv = ex.fetch_ohlcv(symbol, tf, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df[~df.index.duplicated(keep='last')]
            _add_indicators(df)
            data[symbol] = df
            p(f"   ✅ {symbol}: {len(df)} velas")
        except Exception as e:
            p(f"   ❌ {symbol}: {e}")
        time.sleep(0.15)

    return data


def _add_indicators(df: pd.DataFrame):
    """Calcula indicadores — idénticos al Data Engine real."""
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    df['RSI_7'] = ta.rsi(df['close'], length=7)

    for l in [9, 21, 50, 200]:
        ema = ta.ema(df['close'], l)
        if ema is not None:
            df[f'EMA_{l}'] = ema

    df['VOL_SMA_20'] = df['volume'].rolling(20).mean()
    df['VOL_RATIO'] = df['volume'] / df['VOL_SMA_20'].replace(0, 1e-10)

    mc = ta.macd(df['close'])
    if mc is not None:
        for px, nm in [('MACD_', 'MACD'), ('MACDs_', 'MACD_S'), ('MACDh_', 'MACD_H')]:
            cc = [c for c in mc.columns if c.startswith(px)]
            if cc:
                df[nm] = mc[cc[0]]

    bb = ta.bbands(df['close'], length=20, std=2)
    if bb is not None:
        for px, nm in [('BBL_', 'BB_LO'), ('BBM_', 'BB_MID'), ('BBU_', 'BB_HI')]:
            cc = [c for c in bb.columns if c.startswith(px)]
            if cc:
                df[nm] = bb[cc[0]]

    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    if atr is not None:
        df['ATR_14'] = atr

    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None:
        ac = [c for c in adx_df.columns if c.startswith('ADX_')]
        if ac:
            df['ADX_14'] = adx_df[ac[0]]


# ═══════════════════════════════════════════════════════
# SCORING (idéntico al monitor_engine real)
# ═══════════════════════════════════════════════════════

def _s(row, col, default=0.0):
    val = row.get(col, None) if isinstance(row, dict) else (row[col] if col in row.index else None)
    return float(val) if val is not None and not pd.isna(val) else default


def score_coin(df: pd.DataFrame, i: int) -> dict:
    """
    Calcula long_score y short_score para la vela i.
    Réplica fiel del live bot (dual direction).
    """
    if i < 50:
        return {'long_score': 0, 'short_score': 0, 'ema_trend': 'neutral'}

    row = df.iloc[i]
    price = row['close']

    # — EMA trend —
    ema_200 = _s(row, 'EMA_200', price)
    ema_trend = 'bullish' if price > ema_200 else 'bearish'

    # — Range 24h position —
    start = max(0, i - 24)
    high_24h = df['high'].iloc[start:i+1].max()
    low_24h = df['low'].iloc[start:i+1].min()
    rng = high_24h - low_24h
    range_pos = (price - low_24h) / rng if rng > 0 else 0.5

    # — RSI —
    rsi14 = _s(row, 'RSI_14', 50)
    rsi7 = _s(row, 'RSI_7', 50)

    # — Volume —
    vol_ratio = _s(row, 'VOL_RATIO', 1.0)

    # — Bollinger position —
    bb_lo = _s(row, 'BB_LO', price)
    bb_hi = _s(row, 'BB_HI', price)
    bb_rng = bb_hi - bb_lo
    bb_pos = (price - bb_lo) / bb_rng if bb_rng > 0 else 0.5

    # — Green streak —
    green_streak = 0
    for j in range(max(0, i-2), i+1):
        if df['close'].iloc[j] > df['open'].iloc[j]:
            green_streak += 1

    # — Rate of change —
    roc_1h = (price / df['close'].iloc[i-1] - 1) * 100 if i > 0 else 0
    change_24h = (price / df['close'].iloc[max(0,i-24)] - 1) * 100 if i >= 24 else 0

    # — ATR for dynamic trailing —
    atr = _s(row, 'ATR_14', price * 0.02)

    # ═══════════════════════════════════════════════════
    # LONG SCORE (comprar, esperar que suba)
    # ═══════════════════════════════════════════════════
    long_score = 0

    # Cerca del mínimo 24h (20 pts)
    if range_pos < 0.15:
        long_score += 20
    elif range_pos < 0.30:
        long_score += 15
    elif range_pos < 0.45:
        long_score += 8

    # RSI sobrevendida (20 pts)
    if rsi14 < 25:
        long_score += 20
    elif rsi14 < 35:
        long_score += 15
    elif rsi14 < 45:
        long_score += 8

    # Bollinger inferior (15 pts)
    if bb_pos < 0.10:
        long_score += 15
    elif bb_pos < 0.25:
        long_score += 10

    # Velas verdes (15 pts)
    if green_streak >= 3:
        long_score += 15
    elif green_streak >= 2:
        long_score += 10

    # Momentum rebote (15 pts)
    if roc_1h > 0 and change_24h < -5:
        long_score += 15
    elif roc_1h > 0 and change_24h < -2:
        long_score += 8

    # ═══════════════════════════════════════════════════
    # SHORT SCORE (vender, esperar que baje)
    # ═══════════════════════════════════════════════════
    short_score = 0

    # Cerca del máximo 24h (20 pts)
    if range_pos > 0.85:
        short_score += 20
    elif range_pos > 0.70:
        short_score += 15
    elif range_pos > 0.55:
        short_score += 8

    # RSI sobrecomprada (20 pts)
    if rsi14 > 75:
        short_score += 20
    elif rsi14 > 65:
        short_score += 15
    elif rsi14 > 55:
        short_score += 8

    # Bollinger superior (15 pts)
    if bb_pos > 0.90:
        short_score += 15
    elif bb_pos > 0.75:
        short_score += 10

    # Velas rojas (15 pts)
    red_streak = 3 - green_streak
    if red_streak >= 3:
        short_score += 15
    elif red_streak >= 2:
        short_score += 10

    # Cayendo después de pump (15 pts)
    if roc_1h < 0 and change_24h > 10:
        short_score += 15
    elif roc_1h < -0.5:
        short_score += 8

    # ═══════════════════════════════════════════════════
    # CANDLE PATTERNS (optional, adds to score)
    # ═══════════════════════════════════════════════════
    candle_bonus_long = 0
    candle_bonus_short = 0

    if i >= 3:
        o1, c1 = df['open'].iloc[i], df['close'].iloc[i]
        o2, c2 = df['open'].iloc[i-1], df['close'].iloc[i-1]
        h1, l1 = df['high'].iloc[i], df['low'].iloc[i]
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        range1 = h1 - l1 if h1 > l1 else 0.0001
        upper_w = h1 - max(o1, c1)
        lower_w = min(o1, c1) - l1

        # Hammer (bullish)
        if lower_w > body1 * 2 and upper_w < body1 * 0.5 and c2 < o2:
            candle_bonus_long += 12
        # Shooting Star (bearish)
        if upper_w > body1 * 2 and lower_w < body1 * 0.5 and c2 > o2:
            candle_bonus_short += 12
        # Bullish Engulfing
        if c1 > o1 and c2 < o2 and c1 > o2 and o1 < c2 and body1 > body2 * 1.2:
            candle_bonus_long += 12
        # Bearish Engulfing
        if c1 < o1 and c2 > o2 and o1 > c2 and c1 < o2 and body1 > body2 * 1.2:
            candle_bonus_short += 12
        # Doji
        if body1 < range1 * 0.1:
            o3, c3 = df['open'].iloc[i-2], df['close'].iloc[i-2]
            if c2 > o2 and c3 > o3: candle_bonus_short += 8
            elif c2 < o2 and c3 < o3: candle_bonus_long += 8

    return {
        'long_score': long_score,
        'short_score': short_score,
        'ema_trend': ema_trend,
        'range_pos': range_pos,
        'rsi_14': rsi14,
        'vol_ratio': vol_ratio,
        'atr': atr,
        'price': price,
        'candle_bonus_long': candle_bonus_long,
        'candle_bonus_short': candle_bonus_short,
    }


# ═══════════════════════════════════════════════════════
# BOT PROFILE (configuración de cada variante)
# ═══════════════════════════════════════════════════════

@dataclass
class BotProfile:
    name: str
    sl_pct: float = 2.0
    tp_pct: float = 5.0
    min_score: int = 55
    override_score: int = 70
    max_positions: int = 3
    trail_pct: float = 1.5
    trailing_trigger: float = 1.5     # EARLY_TRAIL default
    timeout_hours: int = 4
    use_blacklist: bool = False
    blacklist_hours: int = 4
    smart_trail: bool = False
    smart_timeout: bool = True        # SMART_TIMEOUT default
    min_vol_ratio: float = 0.0
    amount_per_trade: float = 10.0
    cooldown_hours: int = 0
    # V3 features
    hour_filter: bool = False         # skip dead hours (04-08 UTC)
    dynamic_tp: bool = False          # ATR-based TP per coin
    corr_filter: bool = False         # max 1 position per coin group
    candle_patterns: bool = False     # add candle pattern scoring
    conf_sizing: bool = False         # $8/$12 based on score
    auto_ban: bool = False            # auto-blacklist after N losses
    auto_ban_threshold: int = 3       # losses to trigger ban


# ═══════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════

@dataclass
class Position:
    symbol: str
    side: str               # 'long' or 'short'
    entry_price: float
    amount_usd: float
    units: float
    sl_price: float
    tp_price: float
    entry_i: int
    entry_score: int
    peak_price: float = 0.0  # for trailing

    def pnl(self, current_price: float) -> float:
        if self.side == 'long':
            return (current_price - self.entry_price) * self.units
        else:
            return (self.entry_price - current_price) * self.units

    def pnl_pct(self, current_price: float) -> float:
        if self.side == 'long':
            return (current_price / self.entry_price - 1) * 100
        else:
            return (self.entry_price / current_price - 1) * 100


def simulate_bot(profile: BotProfile, data: Dict[str, pd.DataFrame],
                 common_idx: pd.DatetimeIndex) -> dict:
    """
    Simula un bot con su perfil sobre los datos, vela por vela.
    Returns dict con métricas.
    """
    balance = 30.0
    positions: Dict[str, Position] = {}   # symbol -> Position
    trades = []
    peak_equity = balance
    max_dd = 0
    blacklist = {}   # symbol -> expiry index
    cooldowns = {}   # symbol -> expiry index (after SL)
    coin_losses = {}  # symbol -> consecutive loss count (for auto_ban)
    perma_ban = set()  # permanently banned coins

    n = len(common_idx)

    for i in range(50, n):
        # ── Evaluar posiciones abiertas ──
        closed_this_step = []

        for sym, pos in list(positions.items()):
            df = data[sym]
            row_i = df.index.get_indexer([common_idx[i]], method='nearest')[0]
            if row_i < 0:
                continue
            price = df['close'].iloc[row_i]
            high = df['high'].iloc[row_i]
            low = df['low'].iloc[row_i]

            # Intrabar SL/TP check (use high/low of candle)
            hit_sl = False
            hit_tp = False

            if pos.side == 'long':
                hit_sl = low <= pos.sl_price
                hit_tp = high >= pos.tp_price
                # Trailing: update peak and SL
                if high > pos.peak_price:
                    pos.peak_price = high
                    if profile.smart_trail:
                        atr = _s(df.iloc[row_i], 'ATR_14', price * 0.02)
                        trail = min(max(atr / price * 100, 1.0), 4.0)
                    else:
                        trail = profile.trail_pct
                    gain_pct = (pos.peak_price / pos.entry_price - 1) * 100
                    if gain_pct > profile.trailing_trigger:
                        new_sl = pos.peak_price * (1 - trail / 100)
                        if new_sl > pos.sl_price:
                            pos.sl_price = new_sl
            else:  # short
                hit_sl = high >= pos.sl_price
                hit_tp = low <= pos.tp_price
                # Trailing: update peak (lowest) and SL
                if low < pos.peak_price or pos.peak_price == 0:
                    pos.peak_price = low
                    if profile.smart_trail:
                        atr = _s(df.iloc[row_i], 'ATR_14', price * 0.02)
                        trail = min(max(atr / price * 100, 1.0), 4.0)
                    else:
                        trail = profile.trail_pct
                    gain_pct = (pos.entry_price / pos.peak_price - 1) * 100
                    if gain_pct > profile.trailing_trigger:
                        new_sl = pos.peak_price * (1 + trail / 100)
                        if new_sl < pos.sl_price:
                            pos.sl_price = new_sl

            # Timeout check
            hours_held = i - pos.entry_i  # ~1h per candle
            timeout_hit = hours_held >= profile.timeout_hours

            if timeout_hit and profile.smart_timeout:
                # Solo cierra si está en negativo
                current_pnl = pos.pnl(price)
                if current_pnl >= 0:
                    timeout_hit = False  # dejar correr

            # Determinar cierre
            reason = None
            exit_price = price

            if hit_sl and hit_tp:
                # Ambos en la misma vela — asumimos SL primero
                reason = 'SL'
                exit_price = pos.sl_price if pos.side == 'long' else pos.sl_price
            elif hit_sl:
                reason = 'SL'
                exit_price = pos.sl_price if pos.side == 'long' else pos.sl_price
            elif hit_tp:
                reason = 'TP'
                exit_price = pos.tp_price if pos.side == 'long' else pos.tp_price
            elif timeout_hit:
                reason = 'TIMEOUT'
                exit_price = price

            if reason:
                pnl = pos.pnl(exit_price)
                pnl_pct = pos.pnl_pct(exit_price)
                balance += pnl

                trades.append({
                    'symbol': sym, 'side': pos.side, 'reason': reason,
                    'pnl': pnl, 'pnl_pct': pnl_pct,
                    'entry_price': pos.entry_price, 'exit_price': exit_price,
                    'entry_i': pos.entry_i, 'exit_i': i,
                    'score': pos.entry_score,
                })

                # Blacklist on SL
                if reason == 'SL' and profile.use_blacklist:
                    blacklist[sym] = i + profile.blacklist_hours
                # Auto-ban: permanent blacklist after N losses
                if profile.auto_ban and reason == 'SL':
                    coin_losses[sym] = coin_losses.get(sym, 0) + 1
                    if coin_losses[sym] >= profile.auto_ban_threshold:
                        perma_ban.add(sym)
                elif reason != 'SL':
                    coin_losses.pop(sym, None)  # reset on non-SL
                # Extra cooldown after SL
                if reason == 'SL' and profile.cooldown_hours > 0:
                    cooldowns[sym] = i + profile.cooldown_hours

                closed_this_step.append(sym)

        for sym in closed_this_step:
            del positions[sym]

        # Track equity
        equity = balance
        for sym, pos in positions.items():
            df = data[sym]
            row_i = df.index.get_indexer([common_idx[i]], method='nearest')[0]
            if row_i >= 0:
                equity += pos.pnl(df['close'].iloc[row_i])
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        max_dd = max(max_dd, dd)

        if balance < 2:
            break  # Bancarrota

        # ── Buscar nuevas señales ──
        if len(positions) >= profile.max_positions:
            continue

        # Hour filter: skip dead hours
        if profile.hour_filter:
            hour_utc = common_idx[i].hour
            if hour_utc in DEAD_HOURS:
                continue

        if False:  # placeholder to keep indent
            continue

        candidates = []

        for sym in data:
            if sym in positions:
                continue
            # Permanent ban
            if sym in perma_ban:
                continue
            # Blacklist
            if profile.use_blacklist and sym in blacklist:
                if i < blacklist[sym]:
                    continue
                else:
                    del blacklist[sym]
            # Cooldown after SL
            if sym in cooldowns:
                if i < cooldowns[sym]:
                    continue
                else:
                    del cooldowns[sym]
            # Correlation filter: max 1 per group
            if profile.corr_filter:
                grp = COIN_GROUPS.get(sym, sym)
                group_occupied = any(
                    COIN_GROUPS.get(ps, ps) == grp
                    for ps in positions
                )
                if group_occupied:
                    continue

            df = data[sym]
            row_i = df.index.get_indexer([common_idx[i]], method='nearest')[0]
            if row_i < 50:
                continue

            sc = score_coin(df, row_i)

            # Vol filter
            if profile.min_vol_ratio > 0 and sc['vol_ratio'] < profile.min_vol_ratio:
                continue

            # Determine best side
            ls, ss = sc['long_score'], sc['short_score']
            ema = sc['ema_trend']

            # Add candle pattern bonus if enabled
            if profile.candle_patterns:
                ls += sc.get('candle_bonus_long', 0)
                ss += sc.get('candle_bonus_short', 0)

            # LONG
            if ls >= profile.min_score:
                override = ls >= profile.override_score
                if ema == 'bullish' or override:
                    candidates.append({
                        'symbol': sym, 'side': 'long', 'score': ls,
                        'price': sc['price'], 'atr': sc['atr'], 'override': override
                    })

            # SHORT
            if ss >= profile.min_score:
                override = ss >= profile.override_score
                if ema == 'bearish' or override:
                    candidates.append({
                        'symbol': sym, 'side': 'short', 'score': ss,
                        'price': sc['price'], 'atr': sc['atr'], 'override': override
                    })

        # Sort by score desc, take top slots available
        candidates.sort(key=lambda c: c['score'], reverse=True)
        slots = profile.max_positions - len(positions)

        for c in candidates[:slots]:
            price = c['price']

            # Confidence sizing
            if profile.conf_sizing:
                amt = 12.0 if c['score'] >= 70 else 8.0
            else:
                amt = profile.amount_per_trade
            units = amt / price

            # Dynamic TP by ATR
            if profile.dynamic_tp:
                atr_pct = c['atr'] / price * 100
                tp_pct = min(max(atr_pct * 2.5, 2.0), 8.0)  # 2-8% range
            else:
                tp_pct = profile.tp_pct

            if c['side'] == 'long':
                sl = price * (1 - profile.sl_pct / 100)
                tp = price * (1 + tp_pct / 100)
                peak = price
            else:
                sl = price * (1 + profile.sl_pct / 100)
                tp = price * (1 - tp_pct / 100)
                peak = price

            positions[c['symbol']] = Position(
                symbol=c['symbol'], side=c['side'],
                entry_price=price, amount_usd=amt,
                units=units, sl_price=sl, tp_price=tp,
                entry_i=i, entry_score=c['score'], peak_price=peak,
            )

    # Close any remaining positions at last price
    for sym, pos in positions.items():
        df = data[sym]
        price = df['close'].iloc[-1]
        pnl = pos.pnl(price)
        balance += pnl
        trades.append({
            'symbol': sym, 'side': pos.side, 'reason': 'END',
            'pnl': pnl, 'pnl_pct': pos.pnl_pct(price),
            'entry_price': pos.entry_price, 'exit_price': price,
            'entry_i': pos.entry_i, 'exit_i': n - 1,
            'score': pos.entry_score,
        })

    # ── Métricas ──
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = balance - 30.0
    wr = len(wins) / max(len(trades), 1) * 100
    avg_win = sum(t['pnl'] for t in wins) / max(len(wins), 1)
    avg_loss = sum(abs(t['pnl']) for t in losses) / max(len(losses), 1)
    gross_win = sum(t['pnl'] for t in wins)
    gross_loss = sum(abs(t['pnl']) for t in losses)
    pf = gross_win / max(gross_loss, 0.01)

    # Per-exit-reason breakdown
    reasons = {}
    for reason in ['SL', 'TP', 'TRAIL', 'TIMEOUT', 'END']:
        rt = [t for t in trades if t['reason'] == reason]
        if rt:
            reasons[reason] = {'count': len(rt), 'pnl': sum(t['pnl'] for t in rt)}

    # Per-coin
    coin_pnl = {}
    for t in trades:
        coin_pnl[t['symbol']] = coin_pnl.get(t['symbol'], 0) + t['pnl']

    # Best and worst trades
    best_trade = max(trades, key=lambda t: t['pnl']) if trades else None
    worst_trade = min(trades, key=lambda t: t['pnl']) if trades else None

    # Side split
    longs = [t for t in trades if t['side'] == 'long']
    shorts = [t for t in trades if t['side'] == 'short']
    long_pnl = sum(t['pnl'] for t in longs)
    short_pnl = sum(t['pnl'] for t in shorts)

    return {
        'name': profile.name,
        'pnl': total_pnl,
        'final_balance': balance,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'wr': wr,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': pf,
        'max_dd': max_dd,
        'reasons': reasons,
        'coin_pnl': coin_pnl,
        'best_trade': best_trade,
        'worst_trade': worst_trade,
        'longs': len(longs),
        'shorts': len(shorts),
        'long_pnl': long_pnl,
        'short_pnl': short_pnl,
        'trades_list': trades,
    }


# ═══════════════════════════════════════════════════════
# BOT PROFILES
# ═══════════════════════════════════════════════════════

def get_profiles() -> List[BotProfile]:
    # BASELINE = current live config (SL 2%, trail trigger 1.5, smart_timeout)
    BASE = dict(sl_pct=2.0, tp_pct=5.0, min_score=55, trail_pct=1.5,
                trailing_trigger=1.5, timeout_hours=4, smart_timeout=True)

    return [
        BotProfile(name="BASELINE", **BASE),

        # V3 IMPROVEMENTS (each tested individually)
        BotProfile(name="HOUR_FILTER", **{**BASE, 'hour_filter': True}),
        BotProfile(name="DYNAMIC_TP", **{**BASE, 'dynamic_tp': True}),
        BotProfile(name="CORR_FILTER", **{**BASE, 'corr_filter': True}),
        BotProfile(name="CANDLE_PAT", **{**BASE, 'candle_patterns': True}),
        BotProfile(name="CONF_SIZING", **{**BASE, 'conf_sizing': True}),
        BotProfile(name="AUTO_BAN", **{**BASE, 'auto_ban': True, 'auto_ban_threshold': 3}),

        # ULTRA_V3: ALL improvements combined
        BotProfile(name="\U0001f3c6 ULTRA_V3", **{**BASE,
            'hour_filter': True, 'dynamic_tp': True, 'corr_filter': True,
            'candle_patterns': True, 'conf_sizing': True,
            'auto_ban': True, 'auto_ban_threshold': 3}),
    ]


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def print_results(results: List[dict], days: int, n_coins: int):
    """Imprime ranking comparativo."""
    p(f"\n{'='*90}")
    p(f"🏟️  BOT ARENA — {days} días, {n_coins} monedas")
    p(f"{'='*90}")

    # Header
    p(f"\n  {'Bot':<16s} | {'PnL':>8s} | {'#T':>4s} | {'WR':>5s} | "
      f"{'AvgW':>6s} | {'AvgL':>6s} | {'PF':>5s} | {'MaxDD':>6s} | "
      f"{'L/S':>7s}")
    p(f"  {'-'*16}-+-{'-'*8}-+-{'-'*4}-+-{'-'*5}-+-"
      f"{'-'*6}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}-+-{'-'*7}")

    results.sort(key=lambda r: r['pnl'], reverse=True)

    for r in results:
        e = '🟢' if r['pnl'] > 0 else '🔴'
        p(f"  {r['name']:<16s} | {e}${r['pnl']:+6.2f} | {r['trades']:4d} | "
          f"{r['wr']:4.1f}% | ${r['avg_win']:5.2f} | ${r['avg_loss']:5.2f} | "
          f"{r['profit_factor']:4.1f}x | {r['max_dd']:5.1f}% | "
          f"{r['longs']:>2d}L/{r['shorts']:>2d}S")

    # Winner
    if results:
        w = results[0]
        p(f"\n  🏆 GANADOR: {w['name']} → PnL ${w['pnl']:+.2f} | "
          f"WR {w['wr']:.1f}% | PF {w['profit_factor']:.1f}x | DD {w['max_dd']:.1f}%")

    # Detailed breakdown for each bot
    p(f"\n{'='*90}")
    p(f"📋 DETALLE POR BOT")
    p(f"{'='*90}")

    for r in results:
        p(f"\n  ── {r['name']} ──")
        p(f"     Balance: $30.00 → ${r['final_balance']:.2f}")

        # Exit reasons
        if r['reasons']:
            parts = []
            for reason, info in r['reasons'].items():
                e = '🟢' if info['pnl'] > 0 else '🔴'
                parts.append(f"{reason}:{info['count']}({e}${info['pnl']:+.2f})")
            p(f"     Salidas: {' | '.join(parts)}")

        # Side split
        p(f"     LONG: {r['longs']}T ${r['long_pnl']:+.2f} | "
          f"SHORT: {r['shorts']}T ${r['short_pnl']:+.2f}")

        # Best/worst
        if r['best_trade']:
            bt = r['best_trade']
            p(f"     Mejor:  {bt['symbol']} {bt['side'].upper()} "
              f"${bt['pnl']:+.2f} ({bt['reason']})")
        if r['worst_trade']:
            wt = r['worst_trade']
            p(f"     Peor:   {wt['symbol']} {wt['side'].upper()} "
              f"${wt['pnl']:+.2f} ({wt['reason']})")

        # Top coins
        if r['coin_pnl']:
            sorted_coins = sorted(r['coin_pnl'].items(), key=lambda x: x[1], reverse=True)
            top3 = sorted_coins[:3]
            bot3 = sorted_coins[-3:]
            p(f"     Top 3:  {', '.join(f'{c}=${v:+.2f}' for c, v in top3)}")
            p(f"     Bot 3:  {', '.join(f'{c}=${v:+.2f}' for c, v in bot3)}")

    # Delta analysis
    p(f"\n{'='*90}")
    p(f"📊 IMPACTO DE CADA MEJORA (vs BASELINE)")
    p(f"{'='*90}")

    baseline = next((r for r in results if r['name'] == 'BASELINE'), None)
    if baseline:
        for r in results:
            if r['name'] == 'BASELINE':
                continue
            dpnl = r['pnl'] - baseline['pnl']
            dwr = r['wr'] - baseline['wr']
            dpf = r['profit_factor'] - baseline['profit_factor']
            ddd = r['max_dd'] - baseline['max_dd']
            dt = r['trades'] - baseline['trades']

            icon = '📈' if dpnl > 0 else '📉'
            p(f"  {icon} {r['name']:<16s}: PnL {'+' if dpnl>=0 else ''}{dpnl:.2f} | "
              f"WR {'+' if dwr>=0 else ''}{dwr:.1f}% | "
              f"PF {'+' if dpf>=0 else ''}{dpf:.1f}x | "
              f"DD {'+' if ddd>=0 else ''}{ddd:.1f}% | "
              f"Trades {'+' if dt>=0 else ''}{dt}")

    p(f"\n{'='*90}\n")


def main():
    parser = argparse.ArgumentParser(description='🏟️ Bot Arena — Laboratorio Ciego')
    parser.add_argument('--days', type=int, default=30, help='Días de datos (default: 30)')
    parser.add_argument('--fast', action='store_true', help='Modo rápido (menos coins)')
    parser.add_argument('--tf', default='1h', help='Timeframe (default: 1h)')
    args = parser.parse_args()

    coins = COINS_FAST if args.fast else COINS_FULL

    p(f"\n{'='*90}")
    p(f"🏟️  BOT ARENA — Laboratorio Ciego de Mejoras")
    p(f"{'='*90}")
    p(f"   Monedas:  {len(coins)}")
    p(f"   Período:  {args.days} días ({args.tf})")
    p(f"   Capital:  $30.00")
    p(f"   Bots:     {len(get_profiles())} variantes")
    p(f"{'='*90}")

    # Download data
    p(f"\n📥 Descargando datos históricos...")
    data = download_data(coins, days=args.days, tf=args.tf)

    if len(data) < 3:
        p("❌ Datos insuficientes")
        return

    # Build common index
    all_idx = None
    for sym, df in data.items():
        if all_idx is None:
            all_idx = df.index
        else:
            all_idx = all_idx.intersection(df.index)

    p(f"\n   📊 Velas comunes: {len(all_idx)}")

    if len(all_idx) < 60:
        p("❌ Insuficientes velas comunes")
        return

    # Run each bot
    profiles = get_profiles()
    results = []

    p(f"\n🤖 Simulando {len(profiles)} bots...")
    for prof in profiles:
        p(f"   ⏳ {prof.name}...")
        t0 = time.time()
        r = simulate_bot(prof, data, all_idx)
        dt = time.time() - t0
        p(f"   ✅ {prof.name}: {r['trades']} trades, ${r['pnl']:+.2f} ({dt:.1f}s)")
        results.append(r)

    # Print results
    days_actual = max((all_idx[-1] - all_idx[0]).days, 1)
    print_results(results, days_actual, len(data))


if __name__ == '__main__':
    main()

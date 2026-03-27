"""
📡 MONITOR SERVER v7 — TREND FOLLOWING + NEWS
====================================================
V7 upgrades:
- 50+ coins (was 20) — more opportunities
- Momentum/trend following scoring — ride the wave
- News sentiment boost — react to breaking news
- Wider discovery — 20 hot coins from Binance scanner
"""
import asyncio, ccxt, pandas_ta as ta, pandas as pd, numpy as np
import aiohttp, time, logging, logging.handlers, os, json, pathlib, csv
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

load_dotenv()

# ═══ LOG ROTATION (5MB max, 3 backups) ═══
_base = pathlib.Path(__file__).parent
os.makedirs(_base / 'logs', exist_ok=True)
_log_file = str(_base / 'logs' / 'monitor.log')
_handler = logging.handlers.RotatingFileHandler(_log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
_handler.setFormatter(logging.Formatter('%(asctime)s [MON] %(message)s', datefmt='%H:%M:%S'))
# Safe console handler — errors='replace' prevents emoji UnicodeEncodeError from crashing the bot
import sys, io as _io
_safe_stream = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
_console = logging.StreamHandler(_safe_stream)
_console.setFormatter(logging.Formatter('%(asctime)s [MON] %(message)s', datefmt='%H:%M:%S'))
log = logging.getLogger('monitor')
log.setLevel(logging.INFO)
log.propagate = False  # Prevent duplicate output via root logger
log.addHandler(_handler)
log.addHandler(_console)
# Suppress noisy uvicorn HTTP warnings
logging.getLogger('uvicorn.error').setLevel(logging.ERROR)

# ═══════════════════════════════════════════════════════
# CONFIG — loaded from config.json (fallback to defaults)
# ═══════════════════════════════════════════════════════

_cfg_path = _base / 'config.json'
def _load_config():
    try:
        with open(_cfg_path) as f: return json.load(f)
    except: return {}
_cfg = _load_config()
_strat = _cfg.get('strategy', {})
_atr_cfg = _cfg.get('atr', {})
_kill_cfg = _cfg.get('kill_switch', {})
_btc_cfg = _cfg.get('btc_filter', {})

BASE_WATCH = [
    # --- Top caps (liquid, tight spread) ---
    'DOGE/USDT', 'XRP/USDT', 'ADA/USDT', 'SOL/USDT', 'AVAX/USDT',
    'DOT/USDT', 'MATIC/USDT', 'LINK/USDT', 'NEAR/USDT', 'ATOM/USDT',
    # --- Memes (volatile, big moves) ---
    'PEPE/USDT', 'FLOKI/USDT', 'BONK/USDT', 'WIF/USDT', 'SHIB/USDT',
    'TURBO/USDT', 'BABY/USDT',
    # --- Gaming / Metaverse ---
    'GALA/USDT', 'CHZ/USDT', 'JASMY/USDT', 'MBOX/USDT', 'PIXEL/USDT',
    'CHESS/USDT', 'VOXEL/USDT',
    # --- DeFi ---
    'HUMA/USDT', 'DEGO/USDT', 'COS/USDT', 'SIGN/USDT', 'PLUME/USDT',
    'RESOLV/USDT', 'SXT/USDT',
    # --- L1/L2 mid caps ---
    'FET/USDT', 'RENDER/USDT', 'INJ/USDT', 'SEI/USDT', 'SUI/USDT',
    'TIA/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT', 'FLOW/USDT',
    # --- Small caps (high volatility) ---
    'BANANAS31/USDT', 'GRT/USDT', 'FTM/USDT', 'ALGO/USDT', 'SAND/USDT',
    'MANA/USDT', 'ENJ/USDT', 'AXS/USDT', 'AAVE/USDT', 'COMP/USDT',
    # --- BTC for correlation filter ---
    'BTC/USDT',
]
SCAN_INTERVAL = _strat.get('scan_interval_sec', 60)
FEE_PCT = _strat.get('fee_pct', 0.1)
CAPITAL = float(os.getenv('CAPITAL', '30.0'))
MAX_POSITIONS = _strat.get('max_positions', 3)
COOLDOWN_MIN = _strat.get('cooldown_min', 30)
TIMEOUT_HOURS = _strat.get('timeout_hours', 4)
TIMEOUT_MIN_GAIN = _strat.get('timeout_min_gain_pct', 0.5)
MIN_VOLUME_24H_USDT = _strat.get('min_volume_24h_usdt', 500_000)
TRAILING_TRIGGER = _strat.get('trailing_trigger_pct', 1.5)
MAX_SL_STRIKES = _strat.get('max_sl_strikes', 1)   # Ban after 1st SL (was 2 — caused WAXP double-loss)
SL_BAN_HOURS = _strat.get('sl_ban_hours', 4)          # 4h ban (was 2h)
EMA_OVERRIDE_SCORE = _strat.get('ema_override_score', 70)
MIN_DIMS = _strat.get('min_dimensions', 3)
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TG_CHAT = os.getenv('TELEGRAM_CHAT_ID', '')
CRYPTOPANIC_TOKEN = os.getenv('CRYPTOPANIC_TOKEN', '')

# ATR multipliers (from config.json)
ATR_SL_MULT = _atr_cfg.get('sl_multiplier', 1.5)
ATR_TP_MULT = _atr_cfg.get('tp_multiplier', 2.5)
ATR_SL_MIN = _atr_cfg.get('sl_min_pct', 1.0)
ATR_SL_MAX = _atr_cfg.get('sl_max_pct', 5.0)
ATR_TP_MIN = _atr_cfg.get('tp_min_pct', 1.5)
ATR_TP_MAX = _atr_cfg.get('tp_max_pct', 8.0)
ATR_TRAIL_MULT = _atr_cfg.get('trailing_multiplier', 0.8)
ATR_TRAIL_MIN = _atr_cfg.get('trailing_min_pct', 0.8)

# BTC crash filter
BTC_CRASH_THRESHOLD = _btc_cfg.get('crash_threshold_24h_pct', -3.0)

# ═══ LIVE TRADING CONFIG ═══
TRADING_MODE = os.getenv('TRADING_MODE', 'paper')
API_KEY = os.getenv('API_KEY', '')
API_SECRET = os.getenv('API_SECRET', '')
DAILY_LOSS_LIMIT = float(os.getenv('DAILY_LOSS_LIMIT', str(_kill_cfg.get('daily_loss_limit_pct', -5.0))))
MAX_DRAWDOWN_LIMIT = float(os.getenv('MAX_DRAWDOWN_LIMIT', str(_kill_cfg.get('max_drawdown_limit_pct', 15.0))))
SLIPPAGE_MAX = float(os.getenv('SLIPPAGE_MAX', str(_kill_cfg.get('slippage_max_pct', 1.0))))
STATE_FILE = str(_base / 'state' / 'trader_state.json')
AUDIT_LOG = str(_base / 'logs' / 'trades.csv')
KILL_FILE = str(_base / 'KILL_SWITCH')

# Modes from config or defaults
_modes_cfg = _cfg.get('modes', {})
MODES = {
    'fear':   _modes_cfg.get('fear',   {'min_score': 55, 'tp': 5.0, 'sl': 3.0, 'label': 'CAUTIOUS'}),
    'normal': _modes_cfg.get('normal', {'min_score': 50, 'tp': 3.0, 'sl': 2.0, 'label': 'NORMAL'}),
    'greed':  _modes_cfg.get('greed',  {'min_score': 45, 'tp': 2.0, 'sl': 1.5, 'label': 'AGGRESSIVE'}),
}
for k, v in MODES.items():
    v.setdefault('label', k.upper())

def get_mode(fg_value):
    if fg_value < 25: return 'fear'   # Was 20; raised so F&G=23 uses CAUTIOUS (72.4% WR config)
    if fg_value < 50: return 'normal'
    return 'greed'

# ═══════════════════════════════════════════════════════
# BASE TRADER — shared logic for Paper + Live
# ═══════════════════════════════════════════════════════

class BaseTrader(ABC):
    def __init__(self, capital):
        self.initial_capital = capital
        self.balance = capital
        self.positions = {}
        self.trades_history = []
        self.total_trades = 0
        self.total_wins = 0
        self.total_pnl = 0
        self.cooldowns = {}
        self.sl_strikes = {}
        self.sl_ban_until = {}
        self.peak_balance = capital
        self.max_drawdown = 0
        self.daily_pnl = 0
        self.daily_trades = 0
        self.day_start = time.time()
        self.killed = False
        self.kill_reason = ''
        self.mode = 'paper'

    # ── Kill switch ──
    def get_equity(self, prices=None):
        """Total equity = balance + market value of open positions."""
        pos_value = 0
        for sym, pos in self.positions.items():
            try:
                cur = (prices or {}).get(sym, pos['entry_price'])
                if cur <= 0: cur = pos['entry_price']
                if pos['side'] == 'long':
                    pos_value += pos['units'] * cur
                else:
                    pnl_pct = (pos['entry_price'] / cur - 1)
                    pos_value += pos['amount'] * (1 + pnl_pct)
            except Exception as e:
                log.error(f"Error calculating equity for {sym}: {e}")
                pos_value += pos.get('amount', 0)
        return self.balance + pos_value

    def check_kill_switch(self, prices=None):
        if time.time() - self.day_start > 86400:
            self.daily_pnl = 0; self.daily_trades = 0; self.day_start = time.time()
            self.killed = False; self.kill_reason = ''
        if os.path.exists(KILL_FILE):
            self.killed = True; self.kill_reason = '⛔ KILL_SWITCH file detected'; return True
        dl = (self.daily_pnl / self.initial_capital * 100) if self.initial_capital > 0 else 0
        if dl < DAILY_LOSS_LIMIT:
            self.killed = True; self.kill_reason = f'⛔ Daily loss {dl:.1f}% < {DAILY_LOSS_LIMIT}%'; return True
        equity = self.get_equity(prices)
        if equity > self.peak_balance: self.peak_balance = equity
        dd = (self.peak_balance - equity) / self.peak_balance * 100 if self.peak_balance > 0 else 0
        self.max_drawdown = max(self.max_drawdown, dd)
        if dd > MAX_DRAWDOWN_LIMIT:
            self.killed = True; self.kill_reason = f'⛔ Equity DD {dd:.1f}% > {MAX_DRAWDOWN_LIMIT}%'; return True
        return False

    def can_open(self, symbol):
        if self.killed: return False
        if len(self.positions) >= MAX_POSITIONS: return False
        if symbol in self.positions: return False
        if symbol in self.cooldowns:
            if time.time() - self.cooldowns[symbol] < COOLDOWN_MIN * 60: return False
        if symbol in self.sl_ban_until:
            if time.time() < self.sl_ban_until[symbol]:
                remaining = (self.sl_ban_until[symbol] - time.time()) / 3600
                log.info(f"⛔ {symbol} SL-banned ({self.sl_strikes.get(symbol,1)} strikes, {remaining:.1f}h left)")
                return False
            else:
                log.info(f"✅ {symbol} SL-ban lifted")
                del self.sl_ban_until[symbol]; self.sl_strikes.pop(symbol, None)
                self.save_state()  # Persist ban removal
        if self.balance < 5: return False
        return True

    def check_exits(self, prices):
        closed = []; now = time.time()
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            pos = self.positions[symbol]; price = prices[symbol]; side = pos['side']; reason = None
            if side == 'long':
                pnl_pct = (price / pos['entry_price'] - 1) * 100
                if price > pos.get('peak_price', 0): pos['peak_price'] = price
            else:
                pnl_pct = (pos['entry_price'] / price - 1) * 100
                if price < pos.get('peak_price', float('inf')): pos['peak_price'] = price
            # V9.1: ATR-based trailing distance (from config)
            trail_dist = max(ATR_TRAIL_MIN / 100, pos.get('atr_pct', 1.5) / 100 * ATR_TRAIL_MULT)
            if not pos['trailing_active'] and pnl_pct >= TRAILING_TRIGGER:
                pos['trailing_active'] = True
                pos['sl_price'] = pos['entry_price'] * (1.001 if side == 'long' else 0.999)
                log.info(f"\U0001f6e1\ufe0f TRAILING {symbol} ({side}) — SL→breakeven (trail:{trail_dist*100:.1f}%)")
            if pos['trailing_active']:
                if side == 'long':
                    ns = pos['peak_price'] * (1 - trail_dist)
                    if ns > pos['sl_price']: pos['sl_price'] = ns
                else:
                    ns = pos['peak_price'] * (1 + trail_dist)
                    if ns < pos['sl_price']: pos['sl_price'] = ns
            if side == 'long':
                if price >= pos['tp_price']: reason = 'TP'
                elif price <= pos['sl_price']: reason = 'SL' if not pos['trailing_active'] else 'TRAIL'
            else:
                if price <= pos['tp_price']: reason = 'TP'
                elif price >= pos['sl_price']: reason = 'SL' if not pos['trailing_active'] else 'TRAIL'
            hours_held = (now - pos['entry_ts']) / 3600
            if hours_held >= TIMEOUT_HOURS and pnl_pct < TIMEOUT_MIN_GAIN:
                reason = f'TIMEOUT ({hours_held:.1f}h)'
            if reason:
                self._close(symbol, price, reason, pnl_pct, closed)
        return closed

    def _record_trade(self, symbol, pos, price, reason, pnl, pnl_pct):
        self.total_trades += 1; self.total_pnl += pnl; self.daily_pnl += pnl; self.daily_trades += 1
        if pnl > 0: self.total_wins += 1
        self.cooldowns[symbol] = time.time()
        if 'SL' in reason:
            self.sl_strikes[symbol] = self.sl_strikes.get(symbol, 0) + 1
            if self.sl_strikes[symbol] >= MAX_SL_STRIKES:
                self.sl_ban_until[symbol] = time.time() + SL_BAN_HOURS * 3600
                log.info(f"🚫 {symbol} BANNED {SL_BAN_HOURS}h ({self.sl_strikes[symbol]} SLs)")
        else:
            self.sl_strikes.pop(symbol, None)
        # DD now calculated by check_kill_switch using equity
        trade = {
            'symbol': symbol, 'reason': reason, 'side': pos['side'],
            'entry_price': pos['entry_price'], 'exit_price': price,
            'pnl': round(pnl, 4), 'pnl_pct': round(pnl_pct, 2),
            'entry_time': pos['entry_time'],
            'exit_time': datetime.now(timezone.utc).isoformat(),
            'entry_score': pos['entry_score'], 'amount': pos['amount'],
            'mode': self.mode,
        }
        self.trades_history.insert(0, trade)
        self.trades_history = self.trades_history[:100]
        del self.positions[symbol]
        self._audit_log(trade)
        self.save_state()
        icon = '🟢' if pnl > 0 else '🔴'
        log.info(f"{icon} CLOSE {pos['side'].upper()} {symbol} @ ${price:.6f} ({reason}) | PnL: ${pnl:+.4f} ({pnl_pct:+.1f}%) | Bal: ${self.balance:.2f}")
        return trade

    def _audit_log(self, trade):
        try:
            os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
            exists = os.path.exists(AUDIT_LOG)
            with open(AUDIT_LOG, 'a', newline='') as f:
                w = csv.DictWriter(f, fieldnames=['exit_time','symbol','side','reason','entry_price','exit_price','amount','pnl','pnl_pct','mode','entry_time','entry_score'])
                if not exists: w.writeheader()
                w.writerow({k: trade.get(k,'') for k in w.fieldnames})
        except Exception as e:
            log.warning(f"Audit log error: {e}")

    # ── State persistence ──
    def save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            data = {
                'balance': self.balance, 'initial_capital': self.initial_capital,
                'total_pnl': self.total_pnl, 'total_trades': self.total_trades,
                'total_wins': self.total_wins, 'peak_balance': self.peak_balance,
                'max_drawdown': self.max_drawdown, 'daily_pnl': self.daily_pnl,
                'daily_trades': self.daily_trades, 'day_start': self.day_start,
                'positions': self.positions, 'trades_history': self.trades_history[:50],
                'cooldowns': {k: v for k, v in self.cooldowns.items()},
                'sl_strikes': self.sl_strikes, 'sl_ban_until': self.sl_ban_until,
                'mode': self.mode, 'saved_at': datetime.now(timezone.utc).isoformat(),
            }
            with open(STATE_FILE + '.tmp', 'w') as f: json.dump(data, f, indent=2, default=str)
            os.replace(STATE_FILE + '.tmp', STATE_FILE)
        except Exception as e:
            log.warning(f"State save error: {e}")

    def load_state(self):
        if not os.path.exists(STATE_FILE): return False
        try:
            with open(STATE_FILE) as f: data = json.load(f)
            self.balance = data.get('balance', self.initial_capital)
            self.total_pnl = data.get('total_pnl', 0)
            self.total_trades = data.get('total_trades', 0)
            self.total_wins = data.get('total_wins', 0)
            self.peak_balance = data.get('peak_balance', self.balance)
            self.max_drawdown = data.get('max_drawdown', 0)
            self.daily_pnl = data.get('daily_pnl', 0)
            self.daily_trades = data.get('daily_trades', 0)
            self.day_start = data.get('day_start', time.time())
            self.positions = data.get('positions', {})
            for p in self.positions.values():
                if 'entry_ts' not in p: p['entry_ts'] = time.time()
            self.trades_history = data.get('trades_history', [])
            self.cooldowns = {k: float(v) for k, v in data.get('cooldowns', {}).items()}
            self.sl_strikes = data.get('sl_strikes', {})
            self.sl_ban_until = {k: float(v) for k, v in data.get('sl_ban_until', {}).items()}
            n = len(self.positions)
            log.info(f"📂 State restored: ${self.balance:.2f} | {self.total_trades} trades | {n} open positions")
            return True
        except Exception as e:
            log.error(f"State load error: {e}"); return False

    def get_state(self):
        return {
            'balance': round(self.balance, 4), 'initial_capital': self.initial_capital,
            'total_pnl': round(self.total_pnl, 4),
            'pnl_pct': round((self.balance / self.initial_capital - 1) * 100, 2) if self.initial_capital > 0 else 0,
            'total_trades': self.total_trades, 'total_wins': self.total_wins,
            'win_rate': round(self.total_wins / self.total_trades * 100, 1) if self.total_trades > 0 else 0,
            'max_drawdown': round(self.max_drawdown, 2), 'mode': self.mode,
            'killed': self.killed, 'kill_reason': self.kill_reason,
            'daily_pnl': round(self.daily_pnl, 4), 'daily_trades': self.daily_trades,
            'positions': {k: {
                'side': v['side'], 'entry_price': v['entry_price'], 'units': v['units'],
                'amount': v['amount'], 'tp_price': v['tp_price'], 'sl_price': v['sl_price'],
                'entry_time': v['entry_time'], 'entry_score': v['entry_score'],
                'trailing_active': v['trailing_active'], 'peak_price': v['peak_price'],
                'tp_pct': v['tp_pct'], 'sl_pct': v['sl_pct'],
                'hours_held': round((time.time() - v.get('entry_ts', time.time())) / 3600, 1),
            } for k, v in self.positions.items()},
            'history': self.trades_history[:20],
        }

    @abstractmethod
    def open_position(self, symbol, price, score, mode_cfg, side='long', atr_pct=None): pass
    @abstractmethod
    def _close(self, symbol, price, reason, pnl_pct, out): pass

# ═══════════════════════════════════════════════════════
# PAPER TRADER — simulation (default)
# ═══════════════════════════════════════════════════════

class PaperTrader(BaseTrader):
    def __init__(self, capital):
        super().__init__(capital)
        self.mode = 'paper'

    def open_position(self, symbol, price, score, mode_cfg, side='long', atr_pct=None, prices=None):
        slots_free = MAX_POSITIONS - len(self.positions)
        if slots_free <= 0: return False
        # V11: Equity-based position sizing — max 25% of total equity per trade
        equity = self.get_equity(prices or {})
        max_by_equity = equity * 0.25
        max_by_balance = self.balance * 0.33
        amount = min(max_by_equity, max_by_balance, CAPITAL / MAX_POSITIONS)
        if amount < 5.5: return False
        fee = amount * FEE_PCT / 100; invested = amount - fee; units = invested / price
        # ═══ V9.1: ATR-based dynamic SL/TP (from config) ═══
        if atr_pct and atr_pct > 0:
            sl_pct = max(ATR_SL_MIN, min(ATR_SL_MAX, atr_pct * ATR_SL_MULT))
            tp_pct = max(ATR_TP_MIN, min(ATR_TP_MAX, atr_pct * ATR_TP_MULT))
        else:
            tp_pct = mode_cfg['tp']; sl_pct = mode_cfg['sl']  # Fallback to fixed
        if side == 'long': tp_price = price * (1 + tp_pct/100); sl_price = price * (1 - sl_pct/100)
        else: tp_price = price * (1 - tp_pct/100); sl_price = price * (1 + sl_pct/100)
        self.balance -= amount
        self.positions[symbol] = {
            'side': side, 'entry_price': price, 'units': units, 'amount': amount,
            'invested': invested, 'tp_price': tp_price, 'sl_price': sl_price, 'original_sl': sl_price,
            'entry_time': datetime.now(timezone.utc).isoformat(), 'entry_ts': time.time(),
            'entry_score': score, 'fee_paid': fee, 'trailing_active': False, 'peak_price': price,
            'tp_pct': round(tp_pct, 1), 'sl_pct': round(sl_pct, 1),
            'atr_pct': round(atr_pct, 2) if atr_pct else 0,
        }
        icon = '\U0001f7e2' if side == 'long' else '\U0001f534'
        atr_tag = f' ATR:{atr_pct:.1f}%' if atr_pct else ''
        log.info(f"{icon} [PAPER] {side.upper()} {symbol} @ ${price:.6f} | ${amount:.2f} | TP:{tp_pct:.1f}% SL:{sl_pct:.1f}%{atr_tag} | {mode_cfg['label']}")
        self.save_state()
        return True

    def _close(self, symbol, price, reason, pnl_pct, out):
        pos = self.positions[symbol]; side = pos['side']
        if side == 'long': sell_val = pos['units'] * price
        else: sell_val = pos['invested'] + (pos['units'] * (pos['entry_price'] - price))
        fee = abs(sell_val) * FEE_PCT / 100; net = sell_val - fee; pnl = net - pos['amount']
        self.balance += max(0, net)
        trade = self._record_trade(symbol, pos, price, reason, pnl, pnl_pct)
        out.append(trade)

# ═══════════════════════════════════════════════════════
# LIVE TRADER — real orders via ccxt (SPOT LONG only)
# ═══════════════════════════════════════════════════════

class LiveTrader(BaseTrader):
    def __init__(self, capital, exchange):
        super().__init__(capital)
        self.mode = 'live'
        self.exchange = exchange
        self._sync_balance()

    def _sync_balance(self):
        try:
            bal = self.exchange.fetch_balance()
            usdt = float(bal.get('USDT', {}).get('free', 0) or bal.get('total', {}).get('USDT', 0))
            if usdt > 0: self.balance = usdt
            log.info(f"💰 [LIVE] Exchange balance: ${self.balance:.2f} USDT")
        except Exception as e:
            log.error(f"Balance sync error: {e}")

    def _sync_positions(self):
        """Verify local positions match exchange holdings."""
        try:
            bal = self.exchange.fetch_balance()
            for sym in list(self.positions.keys()):
                base = sym.replace('/USDT', '')
                held = float(bal.get(base, {}).get('free', 0) or 0) + float(bal.get(base, {}).get('used', 0) or 0)
                if held < self.positions[sym].get('units', 0) * 0.5:
                    log.warning(f"⚠️ Position {sym} not found on exchange! Removing local.")
                    del self.positions[sym]
        except Exception as e:
            log.warning(f"Position sync error: {e}")

    def open_position(self, symbol, price, score, mode_cfg, side='long', atr_pct=None):
        if side != 'long':
            log.info(f"\u23ed\ufe0f [LIVE] Skipping SHORT {symbol} \u2014 Spot only supports LONG")
            return False
        slots_free = MAX_POSITIONS - len(self.positions)
        if slots_free <= 0: return False
        amount = min(CAPITAL / MAX_POSITIONS, self.balance * 0.33)
        if amount < 5.5: return False
        base = symbol.replace('/USDT', '')
        qty = amount / price
        # Round to exchange precision
        try:
            market = self.exchange.market(symbol)
            qty = float(self.exchange.amount_to_precision(symbol, qty))
            if qty <= 0: log.warning(f"Qty too small for {symbol}"); return False
        except: pass
        # Execute with retry
        order = None
        for attempt in range(3):
            try:
                log.info(f"\U0001f504 [LIVE] Attempt {attempt+1}: BUY {qty} {base} (~${amount:.2f})")
                order = self.exchange.create_market_buy_order(symbol, qty)
                break
            except Exception as e:
                log.error(f"Order error (attempt {attempt+1}): {e}")
                if attempt < 2: time.sleep(2 ** attempt)
        if not order:
            log.error(f"\u274c [LIVE] Failed to open {symbol} after 3 attempts"); return False
        # Parse fill
        fill_price = float(order.get('average', order.get('price', price)) or price)
        fill_qty = float(order.get('filled', qty) or qty)
        fill_cost = float(order.get('cost', fill_price * fill_qty) or fill_price * fill_qty)
        fee_total = sum(float(f.get('cost', 0)) for f in order.get('fees', [])) if order.get('fees') else fill_cost * FEE_PCT / 100
        # Slippage check
        slip = abs(fill_price - price) / price * 100
        if slip > SLIPPAGE_MAX:
            log.warning(f"\u26a0\ufe0f Slippage {slip:.2f}% > {SLIPPAGE_MAX}% on {symbol}")
        # V9.1: ATR-based dynamic SL/TP (from config)
        if atr_pct and atr_pct > 0:
            sl_pct = max(ATR_SL_MIN, min(ATR_SL_MAX, atr_pct * ATR_SL_MULT))
            tp_pct = max(ATR_TP_MIN, min(ATR_TP_MAX, atr_pct * ATR_TP_MULT))
        else:
            tp_pct = mode_cfg['tp']; sl_pct = mode_cfg['sl']
        tp_price = fill_price * (1 + tp_pct/100); sl_price = fill_price * (1 - sl_pct/100)
        self.balance -= fill_cost
        self.positions[symbol] = {
            'side': 'long', 'entry_price': fill_price, 'units': fill_qty,
            'amount': fill_cost, 'invested': fill_cost - fee_total,
            'tp_price': tp_price, 'sl_price': sl_price, 'original_sl': sl_price,
            'entry_time': datetime.now(timezone.utc).isoformat(), 'entry_ts': time.time(),
            'entry_score': score, 'fee_paid': fee_total, 'trailing_active': False,
            'peak_price': fill_price, 'tp_pct': tp_pct, 'sl_pct': sl_pct,
            'atr_pct': round(atr_pct, 2) if atr_pct else 0,
            'order_id': order.get('id', ''),
        }
        log.info(f"🟢 [LIVE] LONG {symbol} @ ${fill_price:.6f} | ${fill_cost:.2f} | slip:{slip:.2f}% | TP:{tp_pct}% SL:{sl_pct}% | ATR:{atr_pct:.1f}%")
        self.save_state()
        return True

    def _close(self, symbol, price, reason, pnl_pct, out):
        pos = self.positions[symbol]
        if pos['side'] != 'long':
            trade = self._record_trade(symbol, pos, price, reason, 0, pnl_pct)
            out.append(trade); return
        qty = pos['units']
        try:
            market = self.exchange.market(symbol)
            qty = float(self.exchange.amount_to_precision(symbol, qty))
        except: pass
        order = None
        for attempt in range(3):
            try:
                log.info(f"🔄 [LIVE] Attempt {attempt+1}: SELL {qty} {symbol} ({reason})")
                order = self.exchange.create_market_sell_order(symbol, qty)
                break
            except Exception as e:
                log.error(f"Sell error (attempt {attempt+1}): {e}")
                if attempt < 2: time.sleep(2 ** attempt)
        if not order:
            log.error(f"❌ [LIVE] Failed to sell {symbol}! Position stuck!"); return
        fill_price = float(order.get('average', order.get('price', price)) or price)
        sell_val = float(order.get('cost', fill_price * qty) or fill_price * qty)
        fee = sum(float(f.get('cost', 0)) for f in order.get('fees', [])) if order.get('fees') else sell_val * FEE_PCT / 100
        net = sell_val - fee; pnl = net - pos['amount']
        self._sync_balance()
        trade = self._record_trade(symbol, pos, fill_price, reason, pnl, pnl_pct)
        out.append(trade)

# ═══════════════════════════════════════════════════════
# TRADER INIT
# ═══════════════════════════════════════════════════════

def create_trader():
    if TRADING_MODE == 'live' and API_KEY and API_SECRET:
        ex = ccxt.binance({'apiKey': API_KEY, 'secret': API_SECRET, 'timeout': 30000, 'enableRateLimit': True})
        t = LiveTrader(CAPITAL, ex)
        log.info(f"🔴 LIVE TRADING MODE — Real orders on Binance Spot")
    else:
        t = PaperTrader(CAPITAL)
        log.info(f"📝 PAPER TRADING MODE — Simulated orders")
    t.load_state()
    return t

trader = create_trader()

# ═══════════════════════════════════════════════════════
# Global state
# ═══════════════════════════════════════════════════════

monitor_state = {'coins': [], 'alerts': [], 'scan_count': 0, 'fear_greed': {'value': 50, 'label': 'Neutral'},
    'market_mode': 'normal', 'dynamic_coins': [], 'last_scan': '', 'news_cache': {},
    'regime': 'unknown', 'regime_adx': 0,
}

# ═══════════════════════════════════════════════════════
# V10: REGIME DETECTION (4h timeframe)
# ═══════════════════════════════════════════════════════

def detect_regime(df_4h):
    """Detect market regime from 4h data using ADX + EMA.
    Returns (regime_name, adx_value)
    Regimes: 'trending_up', 'trending_down', 'ranging', 'weak_trend_up', 'weak_trend_down', 'unknown'
    """
    if df_4h is None or len(df_4h) < 50:
        return 'unknown', 0
    close = df_4h['close']
    adx = ta.adx(df_4h['high'], df_4h['low'], close, 14)
    if adx is None:
        return 'unknown', 0
    adx_col = [c for c in adx.columns if 'ADX' in c]
    if not adx_col:
        return 'unknown', 0
    adx_val = float(adx[adx_col[0]].iloc[-1])
    # EMA for trend direction on 4h
    ema20 = ta.ema(close, 20)
    ema50 = ta.ema(close, 50)
    if ema20 is None or ema50 is None:
        direction = 'neutral'
    else:
        direction = 'up' if float(ema20.iloc[-1]) > float(ema50.iloc[-1]) else 'down'
    if adx_val < 20:
        return 'ranging', adx_val
    elif adx_val >= 25:
        return f'trending_{direction}', adx_val
    else:
        return f'weak_trend_{direction}', adx_val

# ═══════════════════════════════════════════════════════
# NEWS & SENTIMENT
# ═══════════════════════════════════════════════════════

async def get_fear_greed():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get('https://api.alternative.me/fng/?limit=1', timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json(); return int(data['data'][0]['value']), data['data'][0]['value_classification']
    except: return 50, 'Neutral'

async def get_coin_news(coin_symbol):
    base = coin_symbol.replace('/USDT', '')
    try:
        url = f"https://cryptopanic.com/api/free/v1/posts/?currencies={base}&kind=news&limit=5"
        if CRYPTOPANIC_TOKEN: url += f"&auth_token={CRYPTOPANIC_TOKEN}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    data = await r.json()
                    return [{'title':p.get('title',''),'url':p.get('url',''),
                        'source':p.get('source',{}).get('title',''),
                        'published':p.get('published_at','')[:16],
                        'sentiment':'positive' if (p.get('votes',{}).get('positive',0)+p.get('votes',{}).get('liked',0)) > (p.get('votes',{}).get('negative',0)+p.get('votes',{}).get('disliked',0)+1) else 'negative' if (p.get('votes',{}).get('negative',0)+p.get('votes',{}).get('disliked',0)) > (p.get('votes',{}).get('positive',0)+p.get('votes',{}).get('liked',0)+1) else 'neutral',
                    } for p in data.get('results', [])[:5]]
    except: pass
    return []

async def discover_hot_coins(ex):
    try:
        tickers = ex.fetch_tickers()
        movers = []
        for sym, t in tickers.items():
            if not sym.endswith('/USDT') or ':' in sym: continue
            price = t.get('last', 0) or 0
            if price <= 0 or price > 50: continue  # wider price range
            vol = t.get('quoteVolume', 0) or 0
            if vol < 500000: continue  # lower volume threshold for more coins
            chg = t.get('percentage', 0) or 0
            if sym not in BASE_WATCH and abs(chg) > 2:  # lower change threshold
                movers.append({'symbol': sym, 'price': price, 'change': chg, 'volume': vol})
        movers.sort(key=lambda x: -abs(x['change']))
        return movers[:20]  # was 10, now 20
    except Exception as e:
        log.warning(f"Discovery error: {e}"); return []

# ═══════════════════════════════════════════════════════
# ANALYSIS — LONG + SHORT scores
# ═══════════════════════════════════════════════════════

def analyze_coin(df, symbol):
    if df is None or len(df) < 50: return None
    # V9.1: Use CLOSED candles only (drop current incomplete candle)
    df_closed = df.iloc[:-1].copy()  # Only completed candles for indicators
    close = df_closed['close']
    price = float(df['close'].iloc[-1])  # Current price for position tracking
    # Volume gate: reject illiquid coins
    vol_24h_usdt = float((df['volume'].tail(24) * df['close'].tail(24)).sum())

    result = {
        'symbol': symbol, 'price': price,
        'long_score': 0, 'short_score': 0, 'score': 0,
        'long_signals': [], 'short_signals': [],
        'trend_score': 0, 'momentum_score': 0,
        'vol_24h_usdt': vol_24h_usdt,
        'tradeable': vol_24h_usdt >= MIN_VOLUME_24H_USDT,
    }
    h24 = df_closed['high'].tail(24).max(); l24 = df_closed['low'].tail(24).min(); rng = h24 - l24
    rpos = (price - l24) / rng if rng > 0 else 0.5
    result['range_pos'] = float(rpos)
    result['range_pct'] = float((rng / l24 * 100) if l24 > 0 else 0)
    result['high_24h'] = float(h24); result['low_24h'] = float(l24)

    # V9.1: UNIFIED PRICE ZONE (Range + BB merged, max 20pts)
    # Instead of scoring Range and BB separately (35pts combined), one score
    price_zone_long = 0; price_zone_short = 0
    if rpos < 0.15: price_zone_long = 20
    elif rpos < 0.30: price_zone_long = 15
    elif rpos < 0.45: price_zone_long = 8
    if rpos > 0.85: price_zone_short = 20
    elif rpos > 0.70: price_zone_short = 15
    elif rpos > 0.55: price_zone_short = 8

    # --- RSI ---
    rsi = ta.rsi(close, 14); rsi7 = ta.rsi(close, 7)
    r14 = float(rsi.iloc[-1]) if rsi is not None and not pd.isna(rsi.iloc[-1]) else 50
    r7 = float(rsi7.iloc[-1]) if rsi7 is not None and not pd.isna(rsi7.iloc[-1]) else 50
    result['rsi_14'] = r14; result['rsi_7'] = r7
    # LONG: oversold
    if r14 < 25: result['long_score'] += 20; result['long_signals'].append(f'🔴 RSI={r14:.0f} sobrevendida')
    elif r14 < 35: result['long_score'] += 15; result['long_signals'].append(f'🟡 RSI={r14:.0f} baja')
    elif r14 < 45: result['long_score'] += 8
    # SHORT: overbought
    if r14 > 75: result['short_score'] += 20; result['short_signals'].append(f'🔴 RSI={r14:.0f} sobrecomprada')
    elif r14 > 65: result['short_score'] += 15; result['short_signals'].append(f'🟡 RSI={r14:.0f} alta')
    elif r14 > 55: result['short_score'] += 8

    # --- Volume ---
    vs = df_closed['volume'].rolling(20).mean()
    vr = float(df_closed['volume'].iloc[-1] / vs.iloc[-1]) if vs.iloc[-1] > 0 else 1
    result['vol_ratio'] = vr
    if vr > 3:
        result['long_score'] += 15; result['long_signals'].append(f'🔊 Vol {vr:.1f}x!')
        result['short_score'] += 15; result['short_signals'].append(f'🔊 Vol {vr:.1f}x!')
    elif vr > 2:
        result['long_score'] += 10; result['short_score'] += 10
    elif vr > 1.5:
        result['long_score'] += 5; result['short_score'] += 5

    # --- Candle patterns (basic, on CLOSED candles) ---
    greens = sum(1 for i in range(-3,0) if close.iloc[i] > df_closed['open'].iloc[i])
    reds = 3 - greens
    result['green_streak'] = greens
    if greens >= 3: result['long_score'] += 15; result['long_signals'].append('🟢 3 velas verdes')
    elif greens >= 2: result['long_score'] += 10
    if reds >= 3: result['short_score'] += 15; result['short_signals'].append('🔴 3 velas rojas')
    elif reds >= 2: result['short_score'] += 10

    # --- Advanced candle patterns (on CLOSED candles) ---
    o1, h1, l1, c1 = float(df_closed['open'].iloc[-1]), float(df_closed['high'].iloc[-1]), float(df_closed['low'].iloc[-1]), float(close.iloc[-1])
    o2, h2, l2, c2 = float(df_closed['open'].iloc[-2]), float(df_closed['high'].iloc[-2]), float(df_closed['low'].iloc[-2]), float(close.iloc[-2])
    o3, h3, l3, c3 = float(df_closed['open'].iloc[-3]), float(df_closed['high'].iloc[-3]), float(df_closed['low'].iloc[-3]), float(close.iloc[-3])
    body1 = abs(c1 - o1); body2 = abs(c2 - o2)
    range1 = h1 - l1 if h1 > l1 else 0.0001
    upper_wick1 = h1 - max(o1, c1)
    lower_wick1 = min(o1, c1) - l1
    candle_patterns = []

    # 🔨 HAMMER (bullish reversal): small body on top, long lower wick
    if lower_wick1 > body1 * 2 and upper_wick1 < body1 * 0.5 and c2 < o2:
        result['long_score'] += 12; result['long_signals'].append('🔨 Hammer (rebote)')
        candle_patterns.append('🔨 Hammer')

    # ⭐ SHOOTING STAR (bearish reversal): small body at bottom, long upper wick
    if upper_wick1 > body1 * 2 and lower_wick1 < body1 * 0.5 and c2 > o2:
        result['short_score'] += 12; result['short_signals'].append('💫 Shooting Star (caída)')
        candle_patterns.append('💫 Shooting Star')

    # 🟢 BULLISH ENGULFING: current green candle engulfs previous red
    if c1 > o1 and c2 < o2 and c1 > o2 and o1 < c2 and body1 > body2 * 1.2:
        result['long_score'] += 12; result['long_signals'].append('🟢 Envolvente alcista')
        candle_patterns.append('🟢 Engulfing alcista')

    # 🔴 BEARISH ENGULFING: current red candle engulfs previous green
    if c1 < o1 and c2 > o2 and o1 > c2 and c1 < o2 and body1 > body2 * 1.2:
        result['short_score'] += 12; result['short_signals'].append('🔴 Envolvente bajista')
        candle_patterns.append('🔴 Engulfing bajista')

    # ✳️ DOJI: very small body relative to range (indecision)
    if body1 < range1 * 0.1 and range1 > 0:
        candle_patterns.append('✳️ Doji')
        # Doji after uptrend = bearish signal
        if c2 > o2 and c3 > o3:
            result['short_score'] += 8; result['short_signals'].append('✳️ Doji tras subida')
        # Doji after downtrend = bullish signal
        elif c2 < o2 and c3 < o3:
            result['long_score'] += 8; result['long_signals'].append('✳️ Doji tras bajada')

    # 🌅 MORNING STAR (bullish, 3 candles): big red → small body → big green
    if c3 < o3 and body2 < body1 * 0.4 and c1 > o1 and c1 > (o3 + c3) / 2:
        result['long_score'] += 10; result['long_signals'].append('🌅 Morning Star')
        candle_patterns.append('🌅 Morning Star')

    # 🌙 EVENING STAR (bearish, 3 candles): big green → small body → big red
    if c3 > o3 and body2 < body1 * 0.4 and c1 < o1 and c1 < (o3 + c3) / 2:
        result['short_score'] += 10; result['short_signals'].append('🌙 Evening Star')
        candle_patterns.append('🌙 Evening Star')

    result['candle_patterns'] = candle_patterns


    # --- Bollinger ---
    bb = ta.bbands(close, 20, 2)
    if bb is not None:
        bbl = [c for c in bb.columns if c.startswith('BBL_')]; bbu = [c for c in bb.columns if c.startswith('BBU_')]
        if bbl and bbu:
            bl = float(bb[bbl[0]].iloc[-1]); bh = float(bb[bbu[0]].iloc[-1]); br = bh - bl
            if br > 0:
                bp = (price - bl) / br; result['bb_pos'] = float(bp)
                if bp < 0.10: result['long_score'] += 15; result['long_signals'].append('🎯 BB inferior')
                elif bp < 0.25: result['long_score'] += 10
                if bp > 0.90: result['short_score'] += 15; result['short_signals'].append('🎯 BB superior')
                elif bp > 0.75: result['short_score'] += 10

    # --- Momentum ---
    roc1 = float((close.iloc[-1]/close.iloc[-2]-1)*100) if len(close)>1 else 0
    roc3 = float((close.iloc[-1]/close.iloc[-4]-1)*100) if len(close)>3 else 0
    result['roc_1h'] = roc1; result['roc_3h'] = roc3
    if roc1 > 0 and roc3 < -2: result['long_score'] += 15; result['long_signals'].append('⬆️ Rebotando')
    if roc1 < 0 and roc3 > 2: result['short_score'] += 15; result['short_signals'].append('⬇️ Cayendo')

    result['change_1h'] = roc1
    result['change_24h'] = float((close.iloc[-1]/close.iloc[-24]-1)*100) if len(close) > 24 else 0
    result['change_7d'] = float((close.iloc[-1]/close.iloc[max(0,len(close)-168)]-1)*100) if len(close) > 168 else 0

    # --- EMA trend (CRITICAL for filtering) ---
    ema9 = ta.ema(close, 9); ema21 = ta.ema(close, 21)
    if ema9 is not None and ema21 is not None:
        e9 = float(ema9.iloc[-1]); e21 = float(ema21.iloc[-1])
        result['ema_trend'] = 'bullish' if e9 > e21 else 'bearish'
        if e9 > e21:
            result['long_score'] += 10; result['long_signals'].append('📈 EMA alcista')
        else:
            result['short_score'] += 10; result['short_signals'].append('📉 EMA bajista')
    else:
        result['ema_trend'] = 'neutral'

    # --- 🚀 MOMENTUM / TREND FOLLOWING ---
    chg24 = result.get('change_24h', 0)
    chg7d = result.get('change_7d', 0)
    chg1h = result.get('change_1h', 0)
    ema_bull = result.get('ema_trend') == 'bullish'

    # == BUY THE DIP (mean reversion, works in neutral/greed) ==
    if ema_bull and chg24 > 20 and chg1h < -0.5:
        result['long_score'] += 20; result['long_signals'].append(f'🚀 Mega dip! 24h:{chg24:+.0f}% 1h:{chg1h:.1f}%')
    elif ema_bull and chg24 > 10 and chg1h < 0 and roc3 < 0:
        result['long_score'] += 15; result['long_signals'].append(f'🚀 Dip en rally 24h:{chg24:+.0f}%')
    elif ema_bull and chg24 > 5 and chg1h < -0.3:
        result['long_score'] += 10; result['long_signals'].append(f'📈 Pullback 24h:{chg24:+.0f}%')

    # == RIDE THE TREND (trend following, works in ALL conditions) ==
    # Strong momentum UP → LONG (ride the pump)
    if chg1h > 2 and chg24 > 5 and vr > 1.5:
        result['long_score'] += 18; result['long_signals'].append(f'⚡ Pump activo! 1h:{chg1h:+.1f}%')
    elif chg1h > 1 and roc3 > 3 and ema_bull:
        result['long_score'] += 12; result['long_signals'].append(f'🔥 Momentum alcista 3h:{roc3:+.1f}%')

    # Strong momentum DOWN → SHORT (ride the dump)
    if chg1h < -2 and chg24 < -5 and vr > 1.5:
        result['short_score'] += 18; result['short_signals'].append(f'⚡ Dump activo! 1h:{chg1h:+.1f}%')
    elif chg1h < -1 and roc3 < -3 and not ema_bull:
        result['short_score'] += 12; result['short_signals'].append(f'🔥 Momentum bajista 3h:{roc3:+.1f}%')

    # == SHORT the bounce in downtrend ==
    if not ema_bull and chg24 < -10 and chg1h > 0.5:
        result['short_score'] += 20; result['short_signals'].append(f'🔻 Rebote en caída 24h:{chg24:+.0f}%')
    elif not ema_bull and chg24 < -5 and chg1h > 0:
        result['short_score'] += 15; result['short_signals'].append(f'🔻 Subida temporal 24h:{chg24:+.0f}%')

    # --- Other indicators (on CLOSED candles) ---
    adx = ta.adx(df_closed['high'], df_closed['low'], close, 14)
    if adx is not None:
        adx_col = [c for c in adx.columns if 'ADX' in c]
        if adx_col: result['adx_14'] = float(adx[adx_col[0]].iloc[-1])

    mc = ta.macd(close, 12, 26, 9)
    if mc is not None:
        cols = mc.columns.tolist()
        if len(cols) >= 3: result['macd_hist'] = float(mc[cols[2]].iloc[-1])

    # ═══ ATR — Dynamic volatility measure (on CLOSED candles) ═══
    atr_raw = ta.atr(df_closed['high'], df_closed['low'], close, 14)
    if atr_raw is not None and not pd.isna(atr_raw.iloc[-1]):
        atr_val = float(atr_raw.iloc[-1])
        result['atr'] = atr_val
        result['atr_pct'] = float(atr_val / price * 100)  # ATR as % of price
    else:
        result['atr'] = 0
        result['atr_pct'] = 2.0  # Fallback

    # ═══ DIMENSION SCORING (v9) ═══
    # 4 independent dimensions for confluence check
    long_dims = 0; short_dims = 0
    # DIM 1: TREND (EMA direction)
    if result.get('ema_trend') == 'bullish': long_dims += 1
    if result.get('ema_trend') == 'bearish': short_dims += 1
    # DIM 2: MOMENTUM (RSI + MACD agree)
    rsi_long = r14 < 40; rsi_short = r14 > 60
    macd_long = result.get('macd_hist', 0) > 0; macd_short = result.get('macd_hist', 0) < 0
    if rsi_long or macd_long: long_dims += 1
    if rsi_short or macd_short: short_dims += 1
    # DIM 3: PRICE ACTION (BB position or candle pattern or range position)
    bb_long = result.get('bb_pos', 0.5) < 0.3; bb_short = result.get('bb_pos', 0.5) > 0.7
    rng_long = rpos < 0.3; rng_short = rpos > 0.7
    if bb_long or rng_long: long_dims += 1
    if bb_short or rng_short: short_dims += 1
    # DIM 4: VOLUME (above average)
    if vr > 1.3: long_dims += 1; short_dims += 1
    result['long_dims'] = long_dims
    result['short_dims'] = short_dims

    result['units'] = float(CAPITAL / price) if price > 0 else 0
    result['potential_3pct'] = float(result['units'] * price * 0.03)

    # Backward compat: keep 'score' as max of long/short
    result['score'] = max(result['long_score'], result['short_score'])
    result['signals'] = result['long_signals'] if result['long_score'] >= result['short_score'] else result['short_signals']
    result['best_side'] = 'long' if result['long_score'] >= result['short_score'] else 'short'

    # Win prob
    sc = result['score']
    if sc >= 70: result['win_prob'] = 52
    elif sc >= 65: result['win_prob'] = 48
    elif sc >= 55: result['win_prob'] = 44
    else: result['win_prob'] = 40

    return result

async def send_tg(msg):
    if not TG_TOKEN or not TG_CHAT: return
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'Markdown'})
    except: pass

# ═══════════════════════════════════════════════════════
# SCANNER + TRADER LOOP
# ═══════════════════════════════════════════════════════

async def scan_loop():
    global monitor_state
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})

    while True:
        try:
            # Kill switch check
            if trader.check_kill_switch(prices={}):
                if not hasattr(trader, '_kill_notified'):
                    log.warning(trader.kill_reason)
                    await send_tg(f"\u26d4 *BOT STOPPED*\n{trader.kill_reason}\nBal: ${trader.balance:.2f}")
                    trader._kill_notified = True
                await asyncio.sleep(60)  # Check every minute but don't trade
                continue
            elif hasattr(trader, '_kill_notified'):
                del trader._kill_notified
                log.info("\u2705 Kill switch cleared — resuming trading")
                await send_tg("\u2705 *BOT RESUMED* — Kill switch cleared")

            # Position sync for LiveTrader
            if hasattr(trader, '_sync_positions') and monitor_state['scan_count'] % 30 == 0:
                trader._sync_positions()

            monitor_state['scan_count'] += 1; sc = monitor_state['scan_count']
            log.info(f"\ud83d\udd0d Scan #{sc}")

            if sc == 1 or sc % 10 == 0:
                fg = await get_fear_greed()
                monitor_state['fear_greed'] = {'value': fg[0], 'label': fg[1]}

            fg_val = monitor_state['fear_greed']['value']
            mode_name = get_mode(fg_val)
            mode_cfg = MODES[mode_name]
            monitor_state['market_mode'] = mode_name

            if sc % 60 == 1:
                log.info(f"🌍 F&G:{fg_val} Mode:{mode_cfg['label']} SC≥{mode_cfg['min_score']} TP:{mode_cfg['tp']}% SL:{mode_cfg['sl']}%")

            if sc == 1 or sc % 15 == 0:
                hot = await discover_hot_coins(ex)
                if hot:
                    monitor_state['dynamic_coins'] = hot
                    log.info(f"🔥 Hot: {', '.join(h['symbol'] for h in hot[:5])}")

            if sc == 1 or sc % 30 == 0:
                for sym in BASE_WATCH[:20]:  # was 10, cover more coins
                    news = await get_coin_news(sym)
                    if news: monitor_state['news_cache'][sym] = news
                    await asyncio.sleep(0.3)

            watch = list(BASE_WATCH)
            for h in monitor_state.get('dynamic_coins', []):
                if h['symbol'] not in watch: watch.append(h['symbol'])
            # FIX: Always include coins with open positions in scan!
            for pos_sym in list(trader.positions.keys()):
                if pos_sym not in watch: watch.append(pos_sym)

            results = []; prices = {}; data_4h_cache = {}
            # V10: fetch 4h data every 15 scans for regime detection
            if sc == 1 or sc % 15 == 0:
                for sym in ['BTC/USDT', 'SOL/USDT', 'ETH/USDT']:
                    try:
                        ohlcv4 = ex.fetch_ohlcv(sym, '4h', limit=100)
                        df4 = pd.DataFrame(ohlcv4, columns=['timestamp','open','high','low','close','volume'])
                        df4['timestamp'] = pd.to_datetime(df4['timestamp'], unit='ms')
                        df4.set_index('timestamp', inplace=True)
                        data_4h_cache[sym] = df4
                        await asyncio.sleep(0.1)
                    except: pass
                # Detect regime from BTC 4h (most reliable)
                btc_4h = data_4h_cache.get('BTC/USDT')
                if btc_4h is not None:
                    regime, adx_val = detect_regime(btc_4h)
                    monitor_state['regime'] = regime
                    monitor_state['regime_adx'] = adx_val
                    if sc == 1 or sc % 60 == 0:
                        log.info(f"\U0001f3af Regime: {regime.upper()} (ADX:{adx_val:.1f})")
            
            regime = monitor_state.get('regime', 'unknown')

            for sym in watch:
                try:
                    ohlcv = ex.fetch_ohlcv(sym, '1h', limit=200)
                    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    a = analyze_coin(df, sym)
                    if a:
                        a['news'] = monitor_state['news_cache'].get(sym, [])
                        a['is_dynamic'] = sym not in BASE_WATCH
                        # NEWS SENTIMENT BOOST: recent news moves scores
                        if a['news']:
                            pos_count = sum(1 for n in a['news'] if n.get('sentiment') == 'positive')
                            neg_count = sum(1 for n in a['news'] if n.get('sentiment') == 'negative')
                            if pos_count > neg_count:
                                a['long_score'] += 15
                                a['long_signals'].append(f'📰 Noticias positivas ({pos_count})')
                            elif neg_count > pos_count:
                                a['short_score'] += 15
                                a['short_signals'].append(f'📰 Noticias negativas ({neg_count})')
                            # Update combined score
                            a['score'] = max(a['long_score'], a['short_score'])
                        results.append(a)
                        prices[sym] = a['price']
                    await asyncio.sleep(0.1)
                except Exception as e:
                    log.warning(f"⚠️ {sym}: {e}")

            results.sort(key=lambda x: -x['score'])
            monitor_state['coins'] = results
            monitor_state['last_scan'] = datetime.now(timezone.utc).isoformat()

            # === TRADING ===

            # 1. Check exits
            closed = trader.check_exits(prices)
            for t in closed:
                icon = '🟢' if t['pnl'] > 0 else '🔴'
                side_icon = '📈' if t['side'] == 'long' else '📉'
                await send_tg(f"{icon} *CLOSE {t['side'].upper()} {t['symbol']}* ({t['reason']})\n"
                    f"${t['entry_price']:.6f} → ${t['exit_price']:.6f}\n"
                    f"PnL: ${t['pnl']:+.4f} ({t['pnl_pct']:+.1f}%)\nBal: ${trader.balance:.2f}")
                monitor_state['alerts'].insert(0, {
                    'symbol': t['symbol'], 'score': 0, 'price': t['exit_price'],
                    'signals': [f"{icon} {side_icon} {t['side'].upper()} ({t['reason']}) PnL: ${t['pnl']:+.4f}"],
                    'time': datetime.now().strftime('%H:%M:%S')})

            # Re-check kill switch with real prices (equity-based DD)
            if trader.check_kill_switch(prices):
                if not hasattr(trader, '_kill_notified'):
                    log.warning(trader.kill_reason)
                    await send_tg(f"⛔ *BOT STOPPED*\n{trader.kill_reason}\nEquity: ${trader.get_equity(prices):.2f}")
                    trader._kill_notified = True
                continue

            # 2. BTC crash filter: block LONGs on alts if BTC tanking
            btc_data = next((c for c in results if c['symbol'] == 'BTC/USDT'), None)
            btc_crash = btc_data and btc_data.get('change_24h', 0) < BTC_CRASH_THRESHOLD
            if btc_crash:
                log.info("\u26a0\ufe0f BTC crash filter: blocking LONG entries (BTC 24h: {:.1f}%)".format(btc_data['change_24h']))

            # 3. Try to open positions — V10 regime-adapted entries
            base_min_score = mode_cfg['min_score']
            # Regime adaptation: separate thresholds for longs vs shorts
            # V11.1: Regime-adapted thresholds (data-driven from 17h autopsia)
            if 'ranging' in regime:
                long_min = max(base_min_score, 65)    # Very selective both directions
                short_min = max(base_min_score, 65)
                entry_min_dims = 4                     # Need ALL 4 dims
                regime_label = 'RNG'
            elif 'trending_up' in regime:
                long_min = min(base_min_score, 50)     # Easy longs (follow trend)
                short_min = max(base_min_score, 70)    # Hard shorts (against trend)
                entry_min_dims = MIN_DIMS
                regime_label = 'T-UP'
            elif 'trending_down' in regime:
                long_min = max(base_min_score, 72)     # V11.1: was 65 → 72 (10 LONGs lost at 65, ADX>30)
                short_min = min(base_min_score, 50)    # Easy shorts (follow trend)
                entry_min_dims = MIN_DIMS
                regime_label = 'T-DN'
            else:
                long_min = base_min_score
                short_min = base_min_score
                entry_min_dims = MIN_DIMS
                regime_label = '?'
            log.info(f"[V11.1] Regime:{regime_label} L≥{long_min} S≥{short_min} dims≥{entry_min_dims}")

            for coin in results:
                if not trader.can_open(coin['symbol']): continue
                if not coin.get('tradeable', True): continue
                if coin['symbol'] == 'BTC/USDT': continue  # Don't trade BTC directly

                ema = coin.get('ema_trend', 'neutral')
                ls = coin['long_score']; ss = coin['short_score']
                atr_pct = coin.get('atr_pct', 2.0)
                ld = coin.get('long_dims', 0); sd = coin.get('short_dims', 0)

                # V11.1: ATR toxicity gate — skip radioactive coins (>10% ATR)
                if atr_pct > 10.0:
                    log.info(f"[ATR] Skip {coin['symbol']} ATR:{atr_pct:.1f}% > 10% (toxic)")
                    continue

                # LONG: score + EMA ok + dims + no BTC crash
                ema_ok_long = ema == 'bullish' or ls >= EMA_OVERRIDE_SCORE
                if ls >= long_min and ema_ok_long and ld >= entry_min_dims and not btc_crash:
                    override = ' OVR' if ema != 'bullish' else ''
                    if trader.open_position(coin['symbol'], coin['price'], ls, mode_cfg, 'long', atr_pct=atr_pct, prices=prices):
                        await send_tg(f"LONG {coin['symbol']} ({mode_cfg['label']} {regime_label})\n"
                            f"Score: {ls} D:{ld}/4 ATR:{atr_pct:.1f}% | ${coin['price']:.6f}{override}\n"
                            f"Regime: {regime} | Bal: ${trader.balance:.2f}")
                        monitor_state['alerts'].insert(0, {
                            'symbol': coin['symbol'], 'score': ls, 'price': coin['price'],
                            'signals': [f"LONG @ ${coin['price']:.6f} (SC:{ls} D:{ld}/4 {regime_label}){override}"],
                            'time': datetime.now().strftime('%H:%M:%S')})
                        break

                # SHORT: score + EMA ok + dims
                ema_ok_short = ema == 'bearish' or ss >= EMA_OVERRIDE_SCORE
                if ss >= short_min and ema_ok_short and sd >= entry_min_dims:
                    override = ' OVR' if ema != 'bearish' else ''
                    if trader.open_position(coin['symbol'], coin['price'], ss, mode_cfg, 'short', atr_pct=atr_pct, prices=prices):
                        await send_tg(f"SHORT {coin['symbol']} ({mode_cfg['label']} {regime_label})\n"
                            f"Score: {ss} D:{sd}/4 ATR:{atr_pct:.1f}% | ${coin['price']:.6f}{override}\n"
                            f"Regime: {regime} | Bal: ${trader.balance:.2f}")
                        monitor_state['alerts'].insert(0, {
                            'symbol': coin['symbol'], 'score': ss, 'price': coin['price'],
                            'signals': [f"SHORT @ ${coin['price']:.6f} (SC:{ss} D:{sd}/4 {regime_label}){override}"],
                            'time': datetime.now().strftime('%H:%M:%S')})
                        break

            monitor_state['alerts'] = monitor_state['alerts'][:50]

            # Log
            for r in results[:5]:
                ls = r['long_score']; ss = r['short_score']
                pin = '📌' if r['symbol'] in trader.positions else '  '
                side = trader.positions.get(r['symbol'], {}).get('side', '')
                side_icon = '📈' if side == 'long' else ('📉' if side == 'short' else '')
                dyn = '🔥' if r.get('is_dynamic') else ''
                em = '↑' if r.get('ema_trend') == 'bullish' else '↓'
                log.info(f"{pin} {r['symbol']:<15s} L:{ls:>3d} S:{ss:>3d} RSI:{r['rsi_14']:>3.0f} {em} {side_icon}{dyn}")

            ts = trader.get_state()
            for sym, pos in ts['positions'].items():
                cur = prices.get(sym, pos['entry_price'])
                if pos['side'] == 'long':
                    pnl = (cur / pos['entry_price'] - 1) * 100
                else:
                    pnl = (pos['entry_price'] / cur - 1) * 100
                trail = '🛡️' if pos['trailing_active'] else ''
                icon = '📈' if pos['side'] == 'long' else '📉'
                log.info(f"📌 {icon}{sym} ${pos['entry_price']:.6f}→${cur:.6f} ({pnl:+.1f}%) {pos['hours_held']:.1f}h {trail}")
            log.info(f"\ud83d\udcb0 ${ts['balance']:.2f} PnL:${ts['total_pnl']:+.4f} T:{ts['total_trades']} WR:{ts['win_rate']}% {mode_cfg['label']} [{trader.mode.upper()}]")

            await asyncio.sleep(SCAN_INTERVAL)
        except Exception as e:
            log.error(f"Error: {e}")
            import traceback; traceback.print_exc()
            await asyncio.sleep(30)

# ═══════════════════════════════════════════════════════
# FASTAPI
# ═══════════════════════════════════════════════════════

app = FastAPI(title="CT4 Monitor v6")

_html_path = pathlib.Path(__file__).parent / 'dashboard.html'

@app.get("/api/monitor")
async def api_monitor():
    return JSONResponse(content={
        **monitor_state, 'trader': trader.get_state(),
        'mode_cfg': MODES[monitor_state.get('market_mode', 'normal')],
    })

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    # Hot-reload: read fresh on every request (no restart needed for UI changes)
    try:
        return _html_path.read_text(encoding='utf-8')
    except:
        return '<h1>dashboard.html missing</h1>'

# ═══════════════════════════════════════════════════════

async def main():
    log.info("=" * 60)
    log.info(f"\ud83d\udce1 CT4 MONITOR v8 \u2014 {TRADING_MODE.upper()} MODE")
    log.info(f"   {len(BASE_WATCH)} coins + discovery | EMA filter active")
    log.info(f"   Capital: ${CAPITAL} | Max positions: {MAX_POSITIONS}")
    log.info(f"   Kill switch: daily {DAILY_LOSS_LIMIT}% | DD {MAX_DRAWDOWN_LIMIT}%")
    log.info(f"   State: {STATE_FILE} | Audit: {AUDIT_LOG}")
    log.info("=" * 60)
    # Health: startup notification
    await send_tg(f"\ud83d\udfe2 *CT4 Bot Started*\nMode: {TRADING_MODE.upper()}\n"
        f"Capital: ${CAPITAL}\nKill: daily {DAILY_LOSS_LIMIT}% / DD {MAX_DRAWDOWN_LIMIT}%\n"
        f"Positions: {len(trader.positions)}")
    asyncio.create_task(scan_loop())
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down...")
        trader.save_state()
    except Exception as e:
        log.error(f"\ud83d\udca5 CRASH: {e}")
        trader.save_state()
        import traceback; traceback.print_exc()

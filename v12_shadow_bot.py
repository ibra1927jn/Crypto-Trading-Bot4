import asyncio
import ccxt
import ccxt.async_support as ccxt_async
import pandas as pd
import pandas_ta as ta
import json
import os
import csv
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CONFIG
# ==========================================
TG_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID')

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT', 'INJ/USDT',
           'AVAX/USDT', 'NEAR/USDT', 'PEPE/USDT', 'WIF/USDT', 'DOGE/USDT']

CAPITAL = 1000.0
MAX_POSITIONS = 5
STATE_FILE = "/opt/ct4/state/v12_paper_state.json"
LOG_FILE = "/opt/ct4/logs/v12_shadow.log"
TRADES_CSV = "/opt/ct4/logs/v12_trades.csv"
SCAN_INTERVAL = 60  # seconds

# --- Phase 0: Operational Hardening ---
SL_BAN_HOURS = 4
TIMEOUT_HOURS = 168
TIMEOUT_MIN_GAIN_PCT = 0.5
RISK_PER_TRADE_PCT = 0.02
MAX_POSITION_PCT = 0.25
MIN_VOLUME_24H = 1_000_000
KILL_SWITCH_DAILY_LOSS_PCT = 8.0
KILL_SWITCH_MAX_DD_PCT = 20.0

# --- Phase 1: Funding Rate Detector ---
FR_LONG_VETO = 0.0005
FR_SHORT_VETO = -0.0005
FR_HOT_THRESHOLD = 0.0003
FR_CACHE_TTL = 300

SPOT_TO_FUTURES = {
    'PEPE/USDT': '1000PEPE/USDT:USDT',
    '1000SATS/USDT': '1000SATS/USDT:USDT',
}

# --- Phase 3: Kelly + Correlation ---
KELLY_MIN_TRADES = 30                 # need 30+ trades for Kelly
KELLY_MIN_RISK = 0.01
KELLY_MAX_RISK = 0.04
MAX_PER_SECTOR = 2
TRADE_HISTORY_CAP = 50

# --- Phase 4: Dynamic Market Scanner ---
SCANNER_REFRESH_HOURS = 4
SCANNER_MIN_VOLUME = 5_000_000        # $5M daily volume minimum
SCANNER_MAX_COINS = 15                # top 15 coins
SCANNER_CORE_COINS = ['BTC/USDT', 'ETH/USDT']  # always included
SCANNER_BLACKLIST = ['USDC', 'BUSD', 'TUSD', 'FDUSD', 'DAI', 'WBTC',
                     'WETH', 'STETH', 'WBETH', 'BFUSD', 'AEUR', 'EUR',
                     'UST', 'USDP', 'GBP', 'BIFI', 'B']

SECTOR_KEYWORDS = {
    'L1': ['ETH', 'SOL', 'AVAX', 'NEAR', 'SUI', 'APT', 'SEI', 'TIA',
           'ATOM', 'DOT', 'ADA', 'MATIC', 'POL', 'FTM', 'ALGO',
           'HBAR', 'ICP', 'XLM', 'EOS', 'ONE', 'EGLD', 'KAVA'],
    'DEFI': ['LINK', 'UNI', 'AAVE', 'MKR', 'INJ', 'SNX', 'CRV', 'COMP',
             'SUSHI', 'YFI', 'BAL', 'DYDX', 'LDO', 'RPL', 'PENDLE',
             'JUP', 'RAY', 'JTO'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'WIF', 'FLOKI', 'BONK', 'MEME',
             'PEOPLE', 'BOME', 'TURBO', 'NEIRO', 'MOG', 'BABYDOGE'],
    'AI': ['FET', 'RNDR', 'AGIX', 'TAO', 'WLD', 'AKT', 'ARKM', 'OCEAN',
           'JASMY', 'PHALA', 'IO'],
    'GAMING': ['GALA', 'IMX', 'AXS', 'SAND', 'MANA', 'ENJ', 'ALICE',
               'YGG', 'PIXEL', 'PORTAL', 'SUPER', 'RONIN'],
}

def classify_sector(symbol):
    """Auto-classify a symbol into a sector."""
    base = symbol.split('/')[0]
    if base == 'BTC':
        return 'BTC'
    for sector, keywords in SECTOR_KEYWORDS.items():
        if base in keywords:
            return sector
    return 'OTHER'

# Fallback static sector map (replaced dynamically at runtime)
SECTOR_MAP = {s: classify_sector(s) for s in SYMBOLS}

# ==========================================
# LOGGING SETUP
# ==========================================
log = logging.getLogger("V12")
log.setLevel(logging.INFO)
log.propagate = False  # prevent double output
fmt = logging.Formatter("%(asctime)s [V12] %(message)s", datefmt="%H:%M:%S")

fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
fh.setFormatter(fmt)
log.addHandler(fh)

# Console handler only for local dev (nohup captures stdout → dups in log)
if not os.environ.get('NOHUP'):
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    log.addHandler(ch)

# ==========================================
# DYNAMIC MARKET SCANNER (Phase 4)
# ==========================================
class MarketScanner:
    """Scans all Binance USDT pairs and picks top coins by volume × volatility."""

    def __init__(self):
        self._last_scan = 0
        self._symbols = list(SYMBOLS)  # start with fallback
        self._sector_map = dict(SECTOR_MAP)
        self._prices = {}    # cached prices from last scan
        self._volumes = {}   # cached volumes from last scan
        self._ex = ccxt.binance({'enableRateLimit': True})

    @property
    def symbols(self):
        return self._symbols

    @property
    def sector_map(self):
        return self._sector_map

    @property
    def prices(self):
        return self._prices

    @property
    def volumes(self):
        return self._volumes

    def refresh(self):
        """Re-scan market every SCANNER_REFRESH_HOURS. Returns True if refreshed."""
        import time as _time
        now = _time.time()
        if now - self._last_scan < SCANNER_REFRESH_HOURS * 3600 and self._symbols:
            return False  # no refresh needed

        try:
            log.info("Market Scanner: fetching all tickers...")
            tickers = self._ex.fetch_tickers()

            # Cache ALL prices and volumes for use in main loop
            self._prices = {}
            self._volumes = {}
            for sym, t in tickers.items():
                if sym.endswith('/USDT') and ':' not in sym:
                    px = t.get('last', 0) or 0
                    vol = t.get('quoteVolume', 0) or 0
                    if px > 0:
                        self._prices[sym] = px
                    if vol > 0:
                        self._volumes[sym] = vol

            candidates = []
            for sym, t in tickers.items():
                # Only USDT spot pairs
                if not sym.endswith('/USDT') or ':' in sym:
                    continue
                base = sym.split('/')[0]

                # Blacklist filter
                if base in SCANNER_BLACKLIST:
                    continue
                # Skip leveraged tokens (UP/DOWN)
                if base.endswith('UP') or base.endswith('DOWN'):
                    continue
                if base.endswith('BULL') or base.endswith('BEAR'):
                    continue

                vol = t.get('quoteVolume', 0) or 0
                px = t.get('last', 0) or 0
                if vol < SCANNER_MIN_VOLUME or px <= 0:
                    continue

                # Price change as volatility proxy
                pct_change = abs(t.get('percentage', 0) or 0)

                candidates.append({
                    'symbol': sym,
                    'volume': vol,
                    'price': px,
                    'volatility': pct_change,
                    'sector': classify_sector(sym),
                })

            if len(candidates) < 5:
                log.warning(f"Scanner: only {len(candidates)} candidates, keeping old list")
                return False

            # Rank by composite score: volume_rank × 0.6 + volatility_rank × 0.4
            candidates.sort(key=lambda x: x['volume'], reverse=True)
            for i, c in enumerate(candidates):
                c['vol_rank'] = 1 - (i / len(candidates))  # 1.0 = highest vol
            candidates.sort(key=lambda x: x['volatility'], reverse=True)
            for i, c in enumerate(candidates):
                c['vol_score'] = c['vol_rank'] * 0.6 + (1 - i/len(candidates)) * 0.4

            candidates.sort(key=lambda x: x['vol_score'], reverse=True)

            # Always include core coins
            new_symbols = list(SCANNER_CORE_COINS)
            for c in candidates:
                if c['symbol'] not in new_symbols:
                    new_symbols.append(c['symbol'])
                if len(new_symbols) >= SCANNER_MAX_COINS:
                    break

            # Detect changes
            old_set = set(self._symbols)
            new_set = set(new_symbols)
            added = new_set - old_set
            removed = old_set - new_set

            self._symbols = new_symbols
            self._sector_map = {s: classify_sector(s) for s in new_symbols}
            self._last_scan = now

            # Log results
            sector_counts = {}
            for s in new_symbols:
                sec = classify_sector(s)
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
            sector_str = ' '.join(f"{k}:{v}" for k, v in sorted(sector_counts.items()))

            log.info(f"Market Scanner: {len(new_symbols)} coins selected [{sector_str}]")
            if added:
                vol_info = []
                for s in added:
                    c = next((x for x in candidates if x['symbol'] == s), None)
                    v = f"${c['volume']/1e6:.0f}M" if c else '?'
                    vol_info.append(f"+{s}({v})")
                log.info(f"  ADDED: {' '.join(vol_info)}")
            if removed:
                log.info(f"  REMOVED: {' '.join(f'-{s}' for s in removed)}")

            return True

        except Exception as e:
            log.error(f"Market Scanner error: {e}")
            return False


market_scanner = MarketScanner()

# ==========================================
# TELEGRAM
# ==========================================
async def send_tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={'chat_id': TG_CHAT, 'text': f"[V12] {msg}"},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass

# ==========================================
# TRADE CSV LOGGER
# ==========================================
def log_trade_csv(symbol, side, reason, entry_px, exit_px, amount, pnl,
                  pnl_pct, balance, entry_time):
    file_exists = os.path.exists(TRADES_CSV)
    try:
        with open(TRADES_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    'close_time', 'symbol', 'side', 'reason',
                    'entry_price', 'exit_price', 'amount',
                    'pnl', 'pnl_pct', 'balance', 'entry_time'
                ])
            writer.writerow([
                datetime.now(timezone.utc).isoformat(), symbol, side, reason,
                entry_px, exit_px, round(amount, 4),
                round(pnl, 4), round(pnl_pct, 2), round(balance, 2),
                entry_time
            ])
    except Exception as e:
        log.error(f"CSV write error: {e}")

# ==========================================
# FUNDING RATE CACHE (Phase 1)
# ==========================================
class FundingRateCache:
    """Bulk-fetches all Binance Futures funding rates with TTL caching."""

    def __init__(self):
        self._cache = {}
        self._last_fetch = 0
        self._ex = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
        })

    def refresh(self):
        """Fetch all funding rates in 1 API call. Returns True on success."""
        import time as _time
        now = _time.time()
        if now - self._last_fetch < FR_CACHE_TTL and self._cache:
            return True
        try:
            raw = self._ex.fetch_funding_rates()
            self._cache = {}
            for sym, data in raw.items():
                fr = data.get('fundingRate')
                if fr is not None:
                    self._cache[sym] = fr
            self._last_fetch = now
            log.info(f"FR Cache refreshed: {len(self._cache)} pairs")
            return True
        except Exception as e:
            log.error(f"FR fetch error: {e}")
            return False

    def get_rate(self, spot_symbol):
        """Get funding rate for a Spot symbol. Returns (rate, status_str)."""
        # Map to futures symbol
        if spot_symbol in SPOT_TO_FUTURES:
            fut_sym = SPOT_TO_FUTURES[spot_symbol]
        else:
            base = spot_symbol.split('/')[0]
            fut_sym = f"{base}/USDT:USDT"

        rate = self._cache.get(fut_sym)
        if rate is None:
            return None, "N/A"

        pct = rate * 100
        if rate >= FR_LONG_VETO:
            return rate, f"FR:{pct:+.3f}% VETO-L"
        elif rate <= FR_SHORT_VETO:
            return rate, f"FR:{pct:+.3f}% VETO-S"
        elif rate >= FR_HOT_THRESHOLD:
            return rate, f"FR:{pct:+.3f}% HOT"
        else:
            return rate, f"FR:{pct:+.3f}%"

    def get_top_radioactive(self, n=3):
        """Get top N most extreme funding rates across all USDT pairs."""
        items = [(s, r) for s, r in self._cache.items()
                 if s.endswith(':USDT')]
        return sorted(items, key=lambda x: abs(x[1]), reverse=True)[:n]


fr_cache = FundingRateCache()

# ==========================================
# KILL SWITCH
# ==========================================
def check_kill_switch(state):
    """Check daily loss and max drawdown. Returns (is_killed, reason)."""
    now_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Reset daily tracking at midnight UTC
    if state.get('daily_start_date', '') != now_date:
        state['daily_start_date'] = now_date
        state['daily_start_balance'] = state['balance']
        state['kill_switch'] = False
        log.info(f"New trading day: daily start ${state['balance']:.2f}")

    # Already killed today
    if state.get('kill_switch', False):
        return True, "Kill switch active (waiting for new day)"

    bal = state['balance']
    daily_start = state.get('daily_start_balance', CAPITAL)
    peak = state.get('peak_balance', CAPITAL)

    # Update peak (high water mark)
    if bal > peak:
        state['peak_balance'] = bal

    # Daily loss check
    if daily_start > 0:
        daily_loss_pct = ((daily_start - bal) / daily_start) * 100
        if daily_loss_pct >= KILL_SWITCH_DAILY_LOSS_PCT:
            state['kill_switch'] = True
            reason = (f"Daily loss {daily_loss_pct:.1f}% >= {KILL_SWITCH_DAILY_LOSS_PCT}% "
                      f"(${daily_start:.2f} -> ${bal:.2f})")
            log.critical(f"KILL SWITCH: {reason}")
            return True, reason

    # Max drawdown from peak
    if peak > 0:
        dd_pct = ((peak - bal) / peak) * 100
        if dd_pct >= KILL_SWITCH_MAX_DD_PCT:
            state['kill_switch'] = True
            reason = (f"Max DD {dd_pct:.1f}% >= {KILL_SWITCH_MAX_DD_PCT}% "
                      f"(peak ${peak:.2f} -> ${bal:.2f})")
            log.critical(f"KILL SWITCH: {reason}")
            return True, reason

    return False, "OK"

# ==========================================
# SL BAN MANAGEMENT
# ==========================================
def is_banned(state, symbol):
    """Check if a symbol is currently banned from SL."""
    bans = state.get('sl_bans', {})
    if symbol not in bans:
        return False
    ban_until = datetime.fromisoformat(bans[symbol])
    if datetime.now(timezone.utc) >= ban_until:
        del bans[symbol]  # ban expired
        return False
    return True

def add_sl_ban(state, symbol):
    """Ban a symbol for SL_BAN_HOURS after a stop loss."""
    if 'sl_bans' not in state:
        state['sl_bans'] = {}
    ban_until = datetime.now(timezone.utc) + timedelta(hours=SL_BAN_HOURS)
    state['sl_bans'][symbol] = ban_until.isoformat()
    log.info(f"SL BAN: {symbol} banned until {ban_until.strftime('%H:%M UTC')}")

# ==========================================
# POSITION TIMEOUT
# ==========================================
def check_timeout(pos, symbol, current_price):
    """Check if a position has exceeded timeout. Returns (should_close, reason)."""
    entry_time_str = pos.get('entry_time', '')
    if not entry_time_str:
        return False, ""

    entry_time = datetime.fromisoformat(entry_time_str)
    age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600

    if age_hours < TIMEOUT_HOURS:
        return False, ""

    # Calculate current PnL %
    entry_px = pos['entry_price']
    if pos['side'] == 'LONG':
        pnl_pct = ((current_price - entry_px) / entry_px) * 100
    else:
        pnl_pct = ((entry_px - current_price) / entry_px) * 100

    # Only timeout if position isn't winning meaningfully
    if pnl_pct < TIMEOUT_MIN_GAIN_PCT:
        return True, f"TIMEOUT ({age_hours:.1f}h, PnL:{pnl_pct:+.1f}%)"

    return False, ""

# ==========================================
# ADAPTIVE KELLY SIZING (Phase 3)
# ==========================================
def compute_kelly_risk(state):
    """
    Half-Kelly formula from trade history.
    Returns (risk_pct, description).
    """
    history = state.get('trade_history', [])
    if len(history) < KELLY_MIN_TRADES:
        return RISK_PER_TRADE_PCT, f"baseline (trades:{len(history)}<{KELLY_MIN_TRADES})"

    wins = [t['pnl_pct'] for t in history if t['pnl_pct'] > 0]
    losses = [t['pnl_pct'] for t in history if t['pnl_pct'] <= 0]

    if not wins or not losses:
        return RISK_PER_TRADE_PCT, "baseline (no mix)"

    win_rate = len(wins) / len(history)
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))

    if avg_loss == 0:
        return RISK_PER_TRADE_PCT, "baseline (no losses)"

    r_ratio = avg_win / avg_loss
    kelly = win_rate - ((1 - win_rate) / r_ratio)
    half_kelly = kelly / 2

    # Clamp
    risk = max(KELLY_MIN_RISK, min(KELLY_MAX_RISK, half_kelly))
    return risk, (f"Kelly:{half_kelly*100:.1f}% -> {risk*100:.1f}% "
                  f"(WR:{win_rate*100:.0f}% R:{r_ratio:.1f})")

# ==========================================
# SECTOR CORRELATION GUARD (Phase 3)
# ==========================================
def get_sector(symbol):
    return classify_sector(symbol)

def sector_slots_available(state, symbol):
    """Check if we can open a position in this symbol's sector."""
    sector = get_sector(symbol)
    count = sum(1 for s in state['positions'] if get_sector(s) == sector)
    return count < MAX_PER_SECTOR

# ==========================================
# DYNAMIC POSITION SIZING
# ==========================================
def calculate_position_size(equity, entry_price, sl_price, side, risk_pct=None):
    """
    Risk-based position sizing with adaptive Kelly.
    """
    if risk_pct is None:
        risk_pct = RISK_PER_TRADE_PCT

    if side == 'LONG':
        sl_distance_pct = (entry_price - sl_price) / entry_price
    else:
        sl_distance_pct = (sl_price - entry_price) / entry_price

    if sl_distance_pct <= 0:
        return 0, 0

    risk_amount = equity * risk_pct
    position_value = risk_amount / sl_distance_pct

    max_value = equity * MAX_POSITION_PCT
    position_value = min(position_value, max_value)

    if position_value < 5:
        return 0, 0

    qty = position_value / entry_price
    return position_value, qty

# ==========================================
# 15m SNIPER CONFIRMATION (Phase 2)
# ==========================================
async def sniper_15m_check(exchange, symbol, side, cur_px, tp_4h):
    """
    Multi-Timeframe sniper: 4H approved the trade, now 15m confirms timing.
    Returns (confirmed, sl_15m, reason).
    """
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
        df = pd.DataFrame(ohlcv, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume'])

        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema_21'] = ta.ema(df['close'], length=21)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        last = df.iloc[-2]  # last closed candle
        rsi = last['rsi']
        ema21 = last['ema_21']
        atr = last['atr']
        is_bullish_candle = last['close'] > last['open']
        is_bearish_candle = last['close'] < last['open']

        # 15m SL: swing low/high of last 5 candles + ATR padding
        recent = df.iloc[-7:-2]  # last 5 closed candles

        if side == 'LONG':
            # Confirmation: RSI not excessively overbought + bullish candle
            if rsi > 70:
                return False, 0, f"15m RSI high:{rsi:.0f}"
            if not is_bullish_candle:
                return False, 0, "15m candle bearish"

            # 15m SL below recent swing low
            sl_15m = recent['low'].min() - (atr * 0.5)
            sl_dist = ((cur_px - sl_15m) / cur_px) * 100
            if sl_dist > 5.0:  # sanity: 15m SL too wide
                return False, 0, f"15m SL too wide:{sl_dist:.1f}%"
            if sl_dist < 0.1:  # too tight
                return False, 0, f"15m SL too tight:{sl_dist:.2f}%"

            # R:R check with 15m SL
            reward = tp_4h - cur_px
            risk = cur_px - sl_15m
            rr = reward / risk if risk > 0 else 0
            if rr < 1.2:
                return False, 0, f"15m R/R low:{rr:.1f}"

            return True, sl_15m, f"15m OK RSI:{rsi:.0f} SL:{sl_dist:.1f}% R/R:{rr:.1f}"

        elif side == 'SHORT':
            if rsi < 30:
                return False, 0, f"15m RSI low:{rsi:.0f}"
            if not is_bearish_candle:
                return False, 0, "15m candle bullish"

            sl_15m = recent['high'].max() + (atr * 0.5)
            sl_dist = ((sl_15m - cur_px) / cur_px) * 100
            if sl_dist > 5.0:
                return False, 0, f"15m SL too wide:{sl_dist:.1f}%"
            if sl_dist < 0.1:
                return False, 0, f"15m SL too tight:{sl_dist:.2f}%"

            reward = cur_px - tp_4h
            risk = sl_15m - cur_px
            rr = reward / risk if risk > 0 else 0
            if rr < 1.2:
                return False, 0, f"15m R/R low:{rr:.1f}"

            return True, sl_15m, f"15m OK RSI:{rsi:.0f} SL:{sl_dist:.1f}% R/R:{rr:.1f}"

    except Exception as e:
        log.error(f"15m sniper error {symbol}: {e}")
        return False, 0, f"15m error"

# ==========================================
# BTC GRAVITY FILTER (4H)
# ==========================================
async def check_btc_gravity(exchange):
    try:
        ohlcv = await exchange.fetch_ohlcv('BTC/USDT', '4h', limit=60)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low',
                                           'close', 'volume'])
        df['ema_50'] = ta.ema(df['close'], length=50)
        df['rsi_14'] = ta.rsi(df['close'], length=14)
        last = df.iloc[-2]
        bullish = (last['close'] > last['ema_50']) and (last['rsi_14'] > 45)
        log.info(f"BTC Gravity: {'BULL' if bullish else 'BEAR'} "
                 f"(px:{last['close']:.0f} EMA50:{last['ema_50']:.0f} "
                 f"RSI:{last['rsi_14']:.1f})")
        return bullish
    except Exception as e:
        log.error(f"BTC Gravity error: {e}")
        return False

# ==========================================
# V12 COIN ANALYSIS (4H Structure)
# ==========================================
def analyze_coin_v12(df, side, btc_is_bullish, current_price):
    if side == 'LONG' and not btc_is_bullish:
        return False, 0, 0, 0, "BTC Bearish"

    df['ema_50'] = ta.ema(df['close'], length=50)
    df['ema_200'] = ta.ema(df['close'], length=200)
    adx_obj = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx'] = adx_obj.iloc[:, 0] if adx_obj is not None else 0
    df['rsi_14'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    last = df.iloc[-2]
    if last['adx'] < 20:
        return False, 0, 0, 0, f"Lateral ADX:{last['adx']:.0f}"

    if side == 'LONG':
        if last['ema_50'] <= last['ema_200']:
            return False, 0, 0, 0, "No macro bull"
        if last['rsi_14'] > 70:
            return False, 0, 0, 0, "RSI > 70"
    elif side == 'SHORT':
        if last['ema_50'] >= last['ema_200']:
            return False, 0, 0, 0, "No macro bear"
        if last['rsi_14'] < 30:
            return False, 0, 0, 0, "RSI < 30"

    atr_padding = last['atr'] * 1.2

    if side == 'LONG':
        sl = current_price - atr_padding
        risk = current_price - sl
        if risk <= 0:
            return False, 0, 0, 0, "Risk<=0"
        tp = current_price + (last['atr'] * 3.0)
        reward = tp - current_price
    elif side == 'SHORT':
        sl = current_price + atr_padding
        risk = sl - current_price
        if risk <= 0:
            return False, 0, 0, 0, "Risk<=0"
        tp = current_price - (last['atr'] * 3.0)
        reward = current_price - tp

    if risk <= 0: return False, 0, 0, 0, "Risk<=0"
    rr_ratio = reward / risk
    if rr_ratio < 1.2:
        return False, rr_ratio, sl, tp, f"R/R:{rr_ratio:.1f}"

    return True, rr_ratio, sl, tp, f"OK R/R:{rr_ratio:.1f}"

# ==========================================
# TRAILING STOP (R-based)
# ==========================================
def manage_trailing_stop_v12(pos, current_price):
    entry = pos['entry_price']
    initial_risk = abs(entry - pos['initial_sl'])
    if initial_risk <= 0:
        return pos['sl'], "Hold"

    current_profit = ((current_price - entry) if pos['side'] == 'LONG'
                      else (entry - current_price))
    current_r = current_profit / initial_risk

    if current_r >= 1.5 and pos.get('trail_stage', 0) < 2:
        new_sl = (entry + initial_risk if pos['side'] == 'LONG'
                  else entry - initial_risk)
        pos['trail_stage'] = 2
        return new_sl, f"Lock +1R (MFE:{current_r:+.1f}R)"
    elif current_r >= 0.8 and pos.get('trail_stage', 0) < 1:
        new_sl = (entry * 1.002 if pos['side'] == 'LONG'
                  else entry * 0.998)
        pos['trail_stage'] = 1
        return new_sl, f"Breakeven (MFE:{current_r:+.1f}R)"
    return pos['sl'], "Hold"

# ==========================================
# STATE PERSISTENCE
# ==========================================
DEFAULT_STATE = {
    'balance': CAPITAL,
    'positions': {},
    'total_trades': 0,
    'wins': 0,
    'sl_bans': {},
    'peak_balance': CAPITAL,
    'daily_start_balance': CAPITAL,
    'daily_start_date': '',
    'kill_switch': False,
    'trade_history': [],
}

state = dict(DEFAULT_STATE)

def load_state():
    global state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                loaded = json.load(f)
            # Merge with defaults (keeps new fields)
            for k, v in DEFAULT_STATE.items():
                if k not in loaded:
                    loaded[k] = v
            state = loaded
            log.info(f"State restored: ${state['balance']:.2f} | "
                     f"{len(state.get('positions', {}))} pos | "
                     f"{state.get('total_trades', 0)} trades | "
                     f"peak ${state.get('peak_balance', CAPITAL):.2f}")
        except Exception as e:
            log.error(f"State load error: {e}")
    else:
        log.info(f"Fresh start: ${CAPITAL}")

def save_state():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"State save error: {e}")

# ==========================================
# CLOSE POSITION HELPER
# ==========================================
async def close_position(sym, pos, cur_px, reason, state):
    """Close a position, update state, log trade."""
    pnl = ((cur_px - pos['entry_price']) * pos['qty']
           if pos['side'] == 'LONG'
           else (pos['entry_price'] - cur_px) * pos['qty'])
    pnl_pct = (pnl / pos['amount']) * 100 if pos['amount'] > 0 else 0
    state['balance'] += pos['amount'] + pnl
    state['total_trades'] = state.get('total_trades', 0) + 1
    if pnl > 0:
        state['wins'] = state.get('wins', 0) + 1

    # Trade history for Kelly (Phase 3)
    if 'trade_history' not in state:
        state['trade_history'] = []
    state['trade_history'].append({
        'pnl_pct': round(pnl_pct, 2),
        'side': pos['side'],
        'symbol': sym,
    })
    if len(state['trade_history']) > TRADE_HISTORY_CAP:
        state['trade_history'] = state['trade_history'][-TRADE_HISTORY_CAP:]

    tag = "WIN" if pnl > 0 else ("BE" if abs(pnl_pct) < 0.1 else "LOSS")
    log.info(f"[{tag}] CLOSED {sym} ({pos['side']}) {reason} | "
             f"PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%) | Bal: ${state['balance']:.2f}")
    await send_tg(f"{'WIN' if pnl > 0 else 'LOSS'} {sym} ({reason})\n"
                  f"PnL: ${pnl:.2f} ({pnl_pct:+.1f}%)\nBal: ${state['balance']:.2f}")

    log_trade_csv(sym, pos['side'], reason, pos['entry_price'],
                  cur_px, pos['amount'], pnl, pnl_pct,
                  state['balance'], pos.get('entry_time', ''))

    # Add SL ban if stopped out
    if reason == "SL":
        add_sl_ban(state, sym)

    return pnl

# ==========================================
# MAIN LOOP
# ==========================================
async def main_loop():
    load_state()
    ex = ccxt_async.binance()
    scan_count = 0

    log.info("=" * 55)
    log.info("CT4 V12.1 SHADOW BOT -- Phase 4 Dynamic Scanner")
    log.info(f"  Capital: ${CAPITAL} | Max pos: {MAX_POSITIONS}")
    log.info(f"  Risk/trade: {RISK_PER_TRADE_PCT*100:.0f}% | "
             f"Max pos size: {MAX_POSITION_PCT*100:.0f}%")
    log.info(f"  SL ban: {SL_BAN_HOURS}h | Timeout: {TIMEOUT_HOURS}h")
    log.info(f"  Kill switch: daily -{KILL_SWITCH_DAILY_LOSS_PCT}% | "
             f"DD -{KILL_SWITCH_MAX_DD_PCT}%")
    log.info(f"  FR Veto: L>+{FR_LONG_VETO*100:.2f}% S<{FR_SHORT_VETO*100:.2f}%")
    log.info(f"  Scanner: top {SCANNER_MAX_COINS} coins, refresh {SCANNER_REFRESH_HOURS}h")
    log.info("=" * 55)
    await send_tg("V12.1 Shadow Bot Started (Phase 4 Dynamic Scanner)")

    while True:
        try:
            scan_count += 1
            log.info(f"--- Scan #{scan_count} ---")

            # ── Kill Switch Check ──
            killed, kill_reason = check_kill_switch(state)
            if killed:
                log.info(f"KILL SWITCH ACTIVE: {kill_reason}")
                save_state()
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # ── Fetch prices + volumes (use scanner cache + async for positions) ──
            prices = dict(market_scanner.prices)   # start with scanner's cached data
            volumes = dict(market_scanner.volumes)
            # Also fetch fresh prices for any open positions (they need live data)
            for sym in state['positions']:
                try:
                    ticker = await ex.fetch_ticker(sym)
                    prices[sym] = ticker['last']
                    volumes[sym] = ticker.get('quoteVolume', 0) or volumes.get(sym, 0)
                except Exception:
                    pass

            # ── Check open positions ──
            closed_keys = []
            for sym, pos in state['positions'].items():
                cur_px = prices.get(sym)
                if not cur_px:
                    continue

                # Timeout check
                should_timeout, timeout_reason = check_timeout(pos, sym, cur_px)
                if should_timeout:
                    await close_position(sym, pos, cur_px, timeout_reason, state)
                    closed_keys.append(sym)
                    continue

                # Trailing stop update
                new_sl, msg = manage_trailing_stop_v12(pos, cur_px)
                if pos['sl'] != new_sl:
                    pos['sl'] = new_sl
                    log.info(f"TRAIL {sym} ({pos['side']}): {msg}")
                    await send_tg(f"TRAIL {sym}: {msg}")

                # SL/TP hit check
                hit_sl = False
                hit_tp = False
                if pos['side'] == 'LONG':
                    if cur_px <= pos['sl']:
                        hit_sl = True
                    elif cur_px >= pos['tp']:
                        hit_tp = True
                else:
                    if cur_px >= pos['sl']:
                        hit_sl = True
                    elif cur_px <= pos['tp']:
                        hit_tp = True

                if hit_sl or hit_tp:
                    reason = "TP" if hit_tp else "SL"
                    await close_position(sym, pos, cur_px, reason, state)
                    closed_keys.append(sym)

            for k in closed_keys:
                del state['positions'][k]
            save_state()

            # ── Market Scanner refresh (Phase 4) ──
            scanner_refreshed = market_scanner.refresh()

            # ── Funding Rate refresh ──
            fr_ok = fr_cache.refresh()
            if fr_ok:
                top_radio = fr_cache.get_top_radioactive(3)
                if top_radio:
                    parts = [f"{s.split(':')[0]}:{r*100:+.3f}%"
                             for s, r in top_radio]
                    log.info(f"  RADIOACTIVE: {' | '.join(parts)}")

            # ── Scan for new entries (use dynamic symbols) ──
            active_symbols = market_scanner.symbols
            active_sector_map = market_scanner.sector_map
            if len(state['positions']) < MAX_POSITIONS:
                btc_bull = await check_btc_gravity(ex)
                kelly_risk, kelly_desc = compute_kelly_risk(state)
                log.info(f"  Kelly: {kelly_risk*100:.1f}% ({kelly_desc})")

                for sym in active_symbols:
                    if sym in state['positions']:
                        continue
                    if len(state['positions']) >= MAX_POSITIONS:
                        break

                    # SL ban check
                    if is_banned(state, sym):
                        log.info(f"  {sym:12s} BANNED (SL cooldown)")
                        continue



                    # Sector guard (Phase 3)
                    if not sector_slots_available(state, sym):
                        sector = get_sector(sym)
                        log.info(f"  {sym:12s} SECTOR FULL ({sector} "
                                 f">={MAX_PER_SECTOR})")
                        continue

                    try:
                        ohlcv = await ex.fetch_ohlcv(sym, '4h', limit=300)
                        df = pd.DataFrame(ohlcv, columns=[
                            'timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        cur_px = prices.get(sym, df['close'].iloc[-1])

                        # Funding Rate check
                        fr_rate, fr_status = fr_cache.get_rate(sym)

                        # Analyze both sides
                        ok_l, rr_l, sl_l, tp_l, r_l = analyze_coin_v12(
                            df.copy(), 'LONG', btc_bull, cur_px)
                        ok_s, rr_s, sl_s, tp_s, r_s = analyze_coin_v12(
                            df.copy(), 'SHORT', btc_bull, cur_px)

                        log.info(f"  {sym:12s} px:{cur_px:<10.6g} "
                                 f"L:{r_l:18s} S:{r_s:18s} {fr_status}")

                        # FR veto overrides
                        if ok_l and fr_rate is not None and fr_rate >= FR_LONG_VETO:
                            log.info(f"  >> {sym} LONG vetoed by FR {fr_rate*100:+.3f}%")
                            ok_l = False
                        if ok_s and fr_rate is not None and fr_rate <= FR_SHORT_VETO:
                            log.info(f"  >> {sym} SHORT vetoed by FR {fr_rate*100:+.3f}%")
                            ok_s = False

                        # Try LONG entry (4H approved → 15m sniper)
                        if ok_l:
                            confirmed, sl_sniper, sniper_msg = await sniper_15m_check(
                                ex, sym, 'LONG', cur_px, tp_l)
                            if not confirmed:
                                log.info(f"  >> {sym} LONG 4H OK but {sniper_msg}")
                            else:
                                # Use 15m SL (tighter), keep 4H TP
                                final_sl = sl_sniper
                                amt, qty = calculate_position_size(
                                    state['balance'], cur_px, final_sl, 'LONG',
                                    risk_pct=kelly_risk)
                                if amt > 0:
                                    entry_time = datetime.now(timezone.utc).isoformat()
                                    state['positions'][sym] = {
                                        'side': 'LONG', 'entry_price': cur_px,
                                        'qty': qty, 'amount': amt,
                                        'sl': final_sl, 'initial_sl': final_sl,
                                        'tp': tp_l, 'trail_stage': 0,
                                        'entry_time': entry_time,
                                    }
                                    state['balance'] -= amt
                                    sl_dist = ((cur_px - final_sl) / cur_px) * 100
                                    sl_gap = cur_px - final_sl
                                    rr_final = (tp_l - cur_px) / sl_gap if sl_gap > 0.0001 else 0
                                    log.info(f">> SNIPER LONG {sym} @ {cur_px} | "
                                             f"R/R:{rr_final:.1f} | SL:{final_sl:.6g} "
                                             f"(-{sl_dist:.1f}%) | Amt:${amt:.2f} "
                                             f"({amt/state['balance']*100:.0f}%eq) "
                                             f"| {sniper_msg}")
                                    await send_tg(
                                        f"SNIPER LONG {sym} @ {cur_px}\n"
                                        f"R/R:{rr_final:.1f} SL:-{sl_dist:.1f}% "
                                        f"Amt:${amt:.2f}")
                                    save_state()
                                    continue

                        # Try SHORT entry (4H approved → 15m sniper)
                        if ok_s:
                            confirmed, sl_sniper, sniper_msg = await sniper_15m_check(
                                ex, sym, 'SHORT', cur_px, tp_s)
                            if not confirmed:
                                log.info(f"  >> {sym} SHORT 4H OK but {sniper_msg}")
                            else:
                                final_sl = sl_sniper
                                amt, qty = calculate_position_size(
                                    state['balance'], cur_px, final_sl, 'SHORT',
                                    risk_pct=kelly_risk)
                                if amt > 0:
                                    entry_time = datetime.now(timezone.utc).isoformat()
                                    state['positions'][sym] = {
                                        'side': 'SHORT', 'entry_price': cur_px,
                                        'qty': qty, 'amount': amt,
                                        'sl': final_sl, 'initial_sl': final_sl,
                                        'tp': tp_s, 'trail_stage': 0,
                                        'entry_time': entry_time,
                                    }
                                    state['balance'] -= amt
                                    sl_dist = ((final_sl - cur_px) / cur_px) * 100
                                    sl_gap = final_sl - cur_px
                                    rr_final = (cur_px - tp_s) / sl_gap if sl_gap > 0.0001 else 0
                                    log.info(f">> SNIPER SHORT {sym} @ {cur_px} | "
                                             f"R/R:{rr_final:.1f} | SL:{final_sl:.6g} "
                                             f"(+{sl_dist:.1f}%) | Amt:${amt:.2f} "
                                             f"({amt/state['balance']*100:.0f}%eq) "
                                             f"| {sniper_msg}")
                                    await send_tg(
                                        f"SNIPER SHORT {sym} @ {cur_px}\n"
                                        f"R/R:{rr_final:.1f} SL:+{sl_dist:.1f}% "
                                        f"Amt:${amt:.2f}")
                                    save_state()
                                    continue

                    except Exception as e:
                        log.error(f"  {sym} scan error: {e}")
            else:
                log.info(f"  Slots full ({len(state['positions'])}/{MAX_POSITIONS})")

            # ── Scan summary ──
            wr = ((state.get('wins', 0) / state['total_trades'] * 100)
                  if state.get('total_trades', 0) > 0 else 0)
            active_bans = sum(1 for s in state.get('sl_bans', {})
                              if is_banned(state, s))
            log.info(f"  Bal:${state['balance']:.2f} "
                     f"Pos:{len(state['positions'])}/{MAX_POSITIONS} "
                     f"T:{state.get('total_trades', 0)} WR:{wr:.0f}% "
                     f"Peak:${state.get('peak_balance', CAPITAL):.2f} "
                     f"Bans:{active_bans} Kill:{'NO' if not killed else 'YES'}")

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            log.error(f"Main loop error: {e}")
            await asyncio.sleep(SCAN_INTERVAL)


if __name__ == '__main__':
    asyncio.run(main_loop())

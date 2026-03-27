"""
📡 MONITOR ENGINE — Real-time Cheap Coin Opportunity Scanner
==============================================================
Escanea 20+ monedas baratas cada 60 segundos.
Para cada una calcula:
  1. Posición en rango diario (¿está cerca del mínimo?)
  2. RSI actual (¿está sobrevendida?)
  3. Volumen relativo (¿hay actividad inusual?)
  4. Tendencia corta (¿está subiendo?)
  5. Score total de oportunidad

Cuando una moneda tiene score alto → alerta vía Telegram.
"""
import asyncio, ccxt, pandas_ta as ta, pandas as pd, numpy as np
import aiohttp, time, logging, os, json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [MONITOR] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('monitor')

# ═══════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════

# Top 20 monedas baratas con más movimiento diario
WATCH_LIST = [
    'CHESS/USDT', 'COS/USDT', 'DEGO/USDT', 'BABY/USDT',
    'RESOLV/USDT', 'BANANAS31/USDT', 'MBOX/USDT', 'HUMA/USDT',
    'SIGN/USDT', 'PLUME/USDT', 'DOGE/USDT', 'XRP/USDT',
    'ADA/USDT', 'JASMY/USDT', 'GALA/USDT', 'CHZ/USDT',
    'FLOKI/USDT', 'PEPE/USDT', 'BONK/USDT', 'WIF/USDT',
]

SCAN_INTERVAL = 60  # Segundos entre escaneos
ALERT_COOLDOWN = 300  # Segundos antes de re-alertar la misma moneda
MIN_SCORE = 65  # Score mínimo para alertar (0-100)
CAPITAL = 30.0

# Telegram
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TG_CHAT = os.getenv('TELEGRAM_CHAT_ID', '')


# ═══════════════════════════════════════════════════════
# SENTIMENT ENGINE (Fear & Greed)
# ═══════════════════════════════════════════════════════

async def get_fear_greed():
    """Obtiene Fear & Greed Index."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.alternative.me/fng/?limit=1',
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                value = int(data['data'][0]['value'])
                label = data['data'][0]['value_classification']
                return value, label
    except Exception:
        return 50, 'Neutral'


# ═══════════════════════════════════════════════════════
# ANÁLISIS TÉCNICO
# ═══════════════════════════════════════════════════════

def analyze_coin(df, symbol):
    """Analiza una moneda y devuelve un diccionario con scores."""
    if df is None or len(df) < 50:
        return None
    
    close = df['close']
    price = close.iloc[-1]
    
    result = {
        'symbol': symbol,
        'price': price,
        'score': 0,
        'signals': [],
    }
    
    # 1. POSICIÓN EN RANGO 24H (0-100, bajo = oportunidad)
    high_24h = df['high'].tail(24).max() if len(df) >= 24 else df['high'].max()
    low_24h = df['low'].tail(24).min() if len(df) >= 24 else df['low'].min()
    range_24h = high_24h - low_24h
    
    if range_24h > 0:
        range_pos = (price - low_24h) / range_24h  # 0 = en mínimo, 1 = en máximo
    else:
        range_pos = 0.5
    
    result['range_pos'] = range_pos
    result['range_pct'] = (range_24h / low_24h * 100) if low_24h > 0 else 0
    
    # Score por posición en rango (20 puntos max)
    if range_pos < 0.15:
        result['score'] += 20
        result['signals'].append('📉 Cerca del mínimo 24h')
    elif range_pos < 0.30:
        result['score'] += 15
        result['signals'].append('📉 Zona baja del rango')
    elif range_pos < 0.45:
        result['score'] += 8
    
    # 2. RSI (sobrevendida = oportunidad)
    rsi = ta.rsi(close, length=14)
    rsi7 = ta.rsi(close, length=7)
    
    if rsi is not None and not rsi.empty:
        rsi_val = rsi.iloc[-1]
        rsi7_val = rsi7.iloc[-1] if rsi7 is not None else 50
        result['rsi_14'] = rsi_val
        result['rsi_7'] = rsi7_val
        
        # Score RSI (20 puntos max)
        if rsi_val < 25:
            result['score'] += 20
            result['signals'].append(f'🔴 RSI={rsi_val:.0f} MUY sobrevendida')
        elif rsi_val < 35:
            result['score'] += 15
            result['signals'].append(f'🟡 RSI={rsi_val:.0f} sobrevendida')
        elif rsi_val < 45:
            result['score'] += 8
    
    # 3. VOLUMEN (actividad inusual = algo pasa)
    vol_sma = df['volume'].rolling(20).mean()
    vol_ratio = df['volume'].iloc[-1] / vol_sma.iloc[-1] if vol_sma.iloc[-1] > 0 else 1
    result['vol_ratio'] = vol_ratio
    
    # Score volumen (15 puntos max)
    if vol_ratio > 3.0:
        result['score'] += 15
        result['signals'].append(f'🔊 Volumen 3x normal!')
    elif vol_ratio > 2.0:
        result['score'] += 10
        result['signals'].append(f'🔊 Volumen 2x normal')
    elif vol_ratio > 1.5:
        result['score'] += 5
    
    # 4. TENDENCIA CORTA (últimas 3-5 velas verdes = rebote)
    candle_colors = [1 if close.iloc[i] > df['open'].iloc[i] else 0 
                     for i in range(-5, 0)]
    green_streak = sum(candle_colors[-3:])  # Últimas 3
    result['green_streak'] = green_streak
    
    # Score tendencia (15 puntos max)
    if green_streak >= 3:
        result['score'] += 15
        result['signals'].append('🟢 3 velas verdes seguidas')
    elif green_streak >= 2:
        result['score'] += 10
        result['signals'].append('🟢 2 velas verdes seguidas')
    
    # 5. BOLLINGER BOUNCE (precio toca banda inferior)
    bb = ta.bbands(close, length=20, std=2)
    if bb is not None:
        bbl_cols = [c for c in bb.columns if c.startswith('BBL_')]
        bbu_cols = [c for c in bb.columns if c.startswith('BBU_')]
        if bbl_cols and bbu_cols:
            bb_low = bb[bbl_cols[0]].iloc[-1]
            bb_high = bb[bbu_cols[0]].iloc[-1]
            bb_range = bb_high - bb_low
            if bb_range > 0:
                bb_pos = (price - bb_low) / bb_range
                result['bb_pos'] = bb_pos
                
                # Score BB (15 puntos max)
                if bb_pos < 0.10:
                    result['score'] += 15
                    result['signals'].append('🎯 Tocando Bollinger inferior!')
                elif bb_pos < 0.25:
                    result['score'] += 10
                    result['signals'].append('🎯 Cerca de Bollinger inferior')
    
    # 6. MOMENTUM (últimas horas subiendo tras caída)
    roc_1 = (close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) > 1 else 0
    roc_3 = (close.iloc[-1] / close.iloc[-4] - 1) * 100 if len(close) > 3 else 0
    result['roc_1h'] = roc_1
    result['roc_3h'] = roc_3
    
    # Score momentum (15 puntos max)
    if roc_1 > 0 and roc_3 < -2:
        result['score'] += 15
        result['signals'].append(f'⬆️ Rebotando (+{roc_1:.1f}% tras -{abs(roc_3):.1f}%)')
    elif roc_1 > 0.5:
        result['score'] += 8
    
    # 7. POTENCIAL DE GANANCIA (cuánto puedo ganar con $30)
    units = CAPITAL / price if price > 0 else 0
    potential_1pct = units * price * 0.01
    potential_range = units * range_24h * 0.3  # Capturar 30% del rango
    result['units'] = units
    result['potential_1pct'] = potential_1pct
    result['potential_range'] = potential_range
    
    return result


# ═══════════════════════════════════════════════════════
# TELEGRAM ALERTS
# ═══════════════════════════════════════════════════════

async def send_alert(coin_data, fear_greed):
    """Envía alerta de oportunidad por Telegram."""
    if not TG_TOKEN or not TG_CHAT:
        return
    
    c = coin_data
    fg_val, fg_label = fear_greed
    
    msg = (
        f"🎯 *OPORTUNIDAD DETECTADA*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *{c['symbol']}* — ${c['price']:.6f}\n"
        f"⭐ Score: *{c['score']}/100*\n\n"
        f"📈 Señales:\n"
    )
    
    for signal in c['signals']:
        msg += f"  • {signal}\n"
    
    msg += (
        f"\n📊 RSI: {c.get('rsi_14', 50):.0f} | "
        f"Vol: {c.get('vol_ratio', 1):.1f}x | "
        f"Rango: {c.get('range_pct', 0):.1f}%\n"
        f"💰 Con $30: {c.get('units', 0):.0f} unidades\n"
        f"💵 Si sube 3%: ${c.get('potential_1pct', 0)*3:.2f}\n"
        f"🌍 Fear & Greed: {fg_val} ({fg_label})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={
                'chat_id': TG_CHAT,
                'text': msg,
                'parse_mode': 'Markdown',
            })
    except Exception as e:
        log.error(f"Telegram error: {e}")


# ═══════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════

async def main():
    log.info("="*60)
    log.info("📡 MONITOR ENGINE — Cheap Coin Opportunity Scanner")
    log.info(f"   Monitoreando {len(WATCH_LIST)} monedas")
    log.info(f"   Intervalo: {SCAN_INTERVAL}s | Min Score: {MIN_SCORE}")
    log.info("="*60)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    alert_history = {}  # {symbol: last_alert_time}
    scan_count = 0
    
    while True:
        try:
            scan_count += 1
            scan_time = datetime.now().strftime('%H:%M:%S')
            log.info(f"\n{'─'*50}")
            log.info(f"🔍 Scan #{scan_count} — {scan_time}")
            
            # Fear & Greed (cada 10 scans)
            if scan_count == 1 or scan_count % 10 == 0:
                fg = await get_fear_greed()
                log.info(f"🌍 Fear & Greed: {fg[0]} ({fg[1]})")
            
            # Escanear cada moneda
            results = []
            for symbol in WATCH_LIST:
                try:
                    ohlcv = ex.fetch_ohlcv(symbol, '1h', limit=100)
                    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    
                    analysis = analyze_coin(df, symbol)
                    if analysis:
                        results.append(analysis)
                    
                    await asyncio.sleep(0.1)  # Rate limit
                except Exception as e:
                    log.warning(f"   ⚠️ {symbol}: {e}")
            
            # Ordenar por score
            results.sort(key=lambda x: -x['score'])
            
            # Mostrar dashboard
            log.info(f"\n{'Symbol':<15s} | {'Price':>10s} | {'Score':>5s} | "
                     f"{'RSI':>4s} | {'RPos':>5s} | {'Vol':>4s} | {'$3%':>5s} | Señales")
            log.info(f"{'-'*15}-+-{'-'*10}-+-{'-'*5}-+-{'-'*4}-+-{'-'*5}-+-"
                     f"{'-'*4}-+-{'-'*5}-+-{'-'*20}")
            
            for r in results[:20]:
                rsi = r.get('rsi_14', 50)
                rpos = r.get('range_pos', 0.5)
                vol = r.get('vol_ratio', 1)
                pot3 = r.get('potential_1pct', 0) * 3
                signals_str = ' | '.join(r['signals'][:2]) if r['signals'] else ''
                
                icon = '🟢' if r['score'] >= MIN_SCORE else ('🟡' if r['score'] >= 50 else '⚪')
                
                log.info(f"{icon}{r['symbol']:<14s} | ${r['price']:>9.6f} | "
                         f"{r['score']:>4d}  | {rsi:>3.0f} | {rpos:>4.0%} | "
                         f"{vol:>3.1f}x | ${pot3:>4.2f} | {signals_str}")
            
            # Alertar si hay scores altos
            top = [r for r in results if r['score'] >= MIN_SCORE]
            if top:
                for coin in top[:3]:  # Max 3 alertas por scan
                    sym = coin['symbol']
                    now = time.time()
                    last_alert = alert_history.get(sym, 0)
                    
                    if now - last_alert > ALERT_COOLDOWN:
                        log.info(f"\n   🚨 ALERTA: {sym} — Score {coin['score']}")
                        for s in coin['signals']:
                            log.info(f"      {s}")
                        
                        await send_alert(coin, fg)
                        alert_history[sym] = now
            else:
                log.info(f"\n   ⏳ Ninguna moneda supera score {MIN_SCORE}. Esperando...")
            
            # Esperar
            log.info(f"\n   ⏱️ Próximo scan en {SCAN_INTERVAL}s...")
            await asyncio.sleep(SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            log.info("\n🛑 Monitor detenido.")
            break
        except Exception as e:
            log.error(f"Error en scan: {e}")
            await asyncio.sleep(30)

if __name__ == '__main__':
    asyncio.run(main())

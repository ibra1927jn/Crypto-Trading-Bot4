"""
CT4 — Auto-Reporte Diario
============================
Genera un resumen completo del bot y lo envía a Telegram.
Puede correrse manualmente o programarse.

Uso:
  python scripts/daily_report.py          # Reporte único
  python scripts/daily_report.py --loop   # Reporte cada 6h automático

Incluye:
  📊 Estado del mercado
  💼 PnL y equity
  ⚡ Leyes y condiciones
  📜 Historial de trades
  🏥 Salud del sistema
"""

import asyncio
import aiohttp
import sys
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# =============================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API_URL = os.environ.get("BOT_API", "http://localhost:8080/api/status")
REPORT_LOOP_HOURS = 6
# =============================================


def fmt(n, d=2):
    return f"{n:,.{d}f}" if n is not None else "--"


async def send_telegram(text: str):
    """Envía mensaje largo a Telegram (split si > 4000 chars)."""
    conn = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as s:
        # GET URLs have length limits — split into smaller chunks
        chunks = [text[i:i+800] for i in range(0, len(text), 800)]
        for chunk in chunks:
            encoded = quote(chunk)
            url = (f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                   f"?chat_id={CHAT_ID}&text={encoded}"
                   f"&disable_web_page_preview=true")
            try:
                async with s.get(url) as r:
                    if r.status != 200:
                        print(f"  ❌ Telegram error: {r.status}")
                    else:
                        print(f"  📱 Mensaje enviado OK")
            except Exception as e:
                print(f"  ❌ Error: {e}")


async def fetch_status():
    """Obtiene datos del API."""
    conn = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as s:
        try:
            async with s.get(API_URL) as r:
                if r.status == 200:
                    return await r.json()
                print(f"❌ API status: {r.status}")
        except Exception as e:
            print(f"❌ API error: {e}")
    return None


async def generate_report():
    """Genera y envía el reporte completo."""
    print(f"\n{'='*50}")
    print(f"📊 Generando reporte — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    data = await fetch_status()
    if not data:
        await send_telegram(
            "🔴 REPORTE CT4 — ERROR\n\n"
            "❌ No se pudo conectar al API del bot.\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        return

    mk = data.get("market", {})
    rk = data.get("risk", {})
    alpha = data.get("alpha", {})
    laws_data = data.get("laws", {})
    execution = data.get("execution", {})
    history = data.get("history", [])
    positions = data.get("positions", [])

    # Datos
    price = mk.get("price", 0)
    rsi = mk.get("rsi", 0)
    adx = mk.get("adx", 0)
    atr = mk.get("atr", 0)
    ema200 = mk.get("ema_200", 0)
    volume = mk.get("volume", 0)
    vol_sma = mk.get("vol_sma", 0)
    equity = rk.get("current_equity", 0)
    usdt = rk.get("usdt_free", 0)
    btc = rk.get("btc_total", 0)
    btc_val = rk.get("btc_value_usdt", 0)
    start_bal = rk.get("starting_balance", 0)
    dd = rk.get("drawdown_pct", 0) * 100
    kill = rk.get("kill_switch", False)
    signals = alpha.get("signals_emitted", 0)
    evals = alpha.get("evaluations", 0)
    errors = execution.get("consecutive_errors", 0)
    ws = mk.get("ws_connected", False)
    candles = mk.get("candles_count", 0)

    # Cálculos
    gap_ema = ((price - ema200) / ema200 * 100) if ema200 else 0
    vol_ratio = (volume / vol_sma) if vol_sma > 0 else 0
    pnl_usdt = equity - start_bal if start_bal > 0 else 0
    pnl_pct = (pnl_usdt / start_bal * 100) if start_bal > 0 else 0

    # Trades reales (no orphaned)
    real_trades = [t for t in history if t.get("status") != "ORPHANED"]
    wins = [t for t in real_trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in real_trades if (t.get("pnl") or 0) < 0]
    total_pnl = sum(t.get("pnl", 0) or 0 for t in real_trades)

    # Leyes
    law_list = laws_data.get("laws", [])
    active_count = sum(1 for l in law_list if l.get("active"))
    laws_txt = "\n".join(
        f"  {'✅' if l['active'] else '❌'} {l['name']}: {l.get('detail', '')}"
        for l in law_list
    )

    # Estado general
    if kill:
        status_emoji = "🚨"
        status_text = "KILL SWITCH ACTIVO"
    elif signals > 0 and len(positions) > 0:
        status_emoji = "🎯"
        status_text = "EN POSICIÓN"
    elif active_count == 4:
        status_emoji = "🔥"
        status_text = "DISPARO INMINENTE"
    elif active_count >= 3:
        status_emoji = "⚡"
        status_text = "CASI LISTO"
    else:
        status_emoji = "🔍"
        status_text = "ESPERANDO"

    # RSI zona
    if rsi <= 35:
        rsi_zone = "🔥 ZONA DE DISPARO"
    elif rsi <= 42:
        rsi_zone = f"⚠️ Cerca ({(rsi-35):.1f} pts)"
    elif rsi >= 65:
        rsi_zone = "📈 Sobrecomprado"
    else:
        rsi_zone = "😐 Neutral"

    # Construir reporte
    report = (
        f"{status_emoji} REPORTE CT4 — {status_text}\n"
        f"{'━' * 28}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        f"💰 MERCADO\n"
        f"  BTC/USDT: ${fmt(price)}\n"
        f"  EMA 200: ${fmt(ema200)} ({gap_ema:+.2f}%)\n"
        f"  RSI: {fmt(rsi,1)} — {rsi_zone}\n"
        f"  ADX: {fmt(adx,1)}\n"
        f"  ATR: ${fmt(atr)}\n"
        f"  Vol: {fmt(volume,2)} ({vol_ratio:.1f}x media)\n\n"

        f"💼 PORTFOLIO\n"
        f"  Equity: ${fmt(equity)}\n"
        f"  USDT: ${fmt(usdt)}\n"
        f"  BTC: {fmt(btc,6)} (${fmt(btc_val)})\n"
        f"  Balance inicio: ${fmt(start_bal)}\n"
        f"  PnL: ${fmt(pnl_usdt)} ({pnl_pct:+.2f}%)\n"
        f"  Drawdown: {fmt(dd,1)}%\n\n"

        f"⚡ LEYES ({active_count}/4)\n"
        f"{laws_txt}\n\n"

        f"📈 ACTIVIDAD\n"
        f"  Evaluaciones: {evals}\n"
        f"  Señales: {signals}\n"
        f"  Trades reales: {len(real_trades)}\n"
    )

    if len(real_trades) > 0:
        report += (
            f"  Wins: {len(wins)} | Losses: {len(losses)}\n"
            f"  PnL trades: ${fmt(total_pnl)}\n"
            f"  Win rate: {(len(wins)/len(real_trades)*100):.0f}%\n"
        )

    report += (
        f"\n🏥 SISTEMA\n"
        f"  WebSocket: {'✅ OK' if ws else '❌ Down'}\n"
        f"  Velas: {candles}\n"
        f"  Errores API: {errors}\n"
        f"  Kill Switch: {'🚨 ON' if kill else '✅ OFF'}\n"
    )

    # Posiciones activas
    if positions:
        report += f"\n📂 POSICIONES\n"
        for p in positions:
            report += f"  {p.get('side','')} {fmt(p.get('amount',0),5)} BTC @ ${fmt(p.get('entry_price',0))}\n"

    # Últimos trades
    if history:
        report += f"\n📜 HISTORIAL\n"
        for h in history[-5:]:  # Últimos 5
            pnl = h.get("pnl") or 0
            sign = "+" if pnl >= 0 else ""
            report += (f"  {h.get('side','')} {fmt(h.get('amount',0),5)} BTC "
                       f"@ ${fmt(h.get('entry_price',0))} "
                       f"{sign}${fmt(pnl)} [{h.get('status','')}]\n")

    report += f"\n{'━' * 28}\nCT4 Quant Terminal v1.0"

    # Enviar
    print(report)
    await send_telegram(report)
    print(f"\n✅ Reporte enviado a Telegram")


async def loop_mode():
    """Envía reportes cada N horas."""
    print(f"🔄 Modo loop — reporte cada {REPORT_LOOP_HOURS}h")
    print(f"   Próximo: {(datetime.now() + timedelta(hours=REPORT_LOOP_HOURS)).strftime('%H:%M')}")

    # Primer reporte inmediato
    await generate_report()

    while True:
        await asyncio.sleep(REPORT_LOOP_HOURS * 3600)
        await generate_report()


if __name__ == "__main__":
    if "--loop" in sys.argv:
        asyncio.run(loop_mode())
    else:
        asyncio.run(generate_report())

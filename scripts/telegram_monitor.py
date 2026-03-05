"""
CT4 — Monitor de Alertas Telegram
===================================
Script INDEPENDIENTE que vigila el bot a través del API
y envía alertas a Telegram cuando pasa algo importante.

Corre en PARALELO al bot — no lo toca ni lo modifica.

Alertas:
  🎯 Trade disparado (señal emitida)
  🚨 Kill Switch activado
  ⚡ 3/4 o 4/4 Leyes alineadas
  📊 Reporte cada hora
  💣 Flash crash detectado (ATR explosivo)
  📡 Bot offline

Uso:
  python scripts/telegram_monitor.py
"""

import asyncio
import aiohttp
import os
from datetime import datetime, timezone
from urllib.parse import quote

# =============================================
# CONFIGURACIÓN
# =============================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8786260046:AAHWr2sZB3MpHS2Y_OTNX0cBa-JkVt-dEO4")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "5822131920")
API_URL = os.environ.get("BOT_API", "http://localhost:8080/api/status")

POLL_SECONDS = 30          # Cada cuántos segundos chequea
REPORT_INTERVAL = 3600     # Reporte cada hora (segundos)
ATR_SPIKE_MULT = 3.0       # Alerta si ATR sube 3×


class TelegramMonitor:
    def __init__(self):
        self.last_signals = 0
        self.last_kill = False
        self.last_laws_count = -1
        self.last_report = 0
        self.last_atr = 0
        self.atr_baseline = 0
        self.was_offline = True
        self.poll_count = 0
        self.session = None

    async def get_session(self):
        if not self.session or self.session.closed:
            conn = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(connector=conn, timeout=timeout)
        return self.session

    async def send(self, text: str):
        """Envía mensaje a Telegram via GET (compatible con firewalls)."""
        encoded = quote(text)
        url = (f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
               f"?chat_id={CHAT_ID}&text={encoded}&parse_mode=HTML"
               f"&disable_web_page_preview=true")
        try:
            s = await self.get_session()
            async with s.get(url) as r:
                if r.status == 200:
                    print(f"  📱 Telegram OK")
                    return True
                else:
                    body = await r.text()
                    print(f"  ❌ Telegram {r.status}: {body[:100]}")
                    return False
        except Exception as e:
            print(f"  ❌ Telegram error: {e}")
            return False

    async def poll_api(self):
        """Consulta el API del bot."""
        try:
            s = await self.get_session()
            async with s.get(API_URL) as r:
                if r.status == 200:
                    return await r.json()
        except:
            pass
        return None

    def fmt(self, n, d=2):
        return f"{n:,.{d}f}" if n is not None else "--"

    async def check_and_alert(self, data: dict):
        """Evalúa condiciones y envía alertas."""
        now = datetime.now(timezone.utc).timestamp()
        mk = data.get("market", {})
        rk = data.get("risk", {})
        alpha = data.get("alpha", {})
        laws = data.get("laws", {})

        price = mk.get("price", 0)
        rsi = mk.get("rsi", 50)
        adx = mk.get("adx", 0)
        atr = mk.get("atr", 0)
        signals = alpha.get("signals_emitted", 0)
        evals = alpha.get("evaluations", 0)
        kill = rk.get("kill_switch", False)
        dd = rk.get("drawdown_pct", 0) * 100
        equity = rk.get("current_equity", 0)
        law_list = laws.get("laws", [])
        active_count = sum(1 for l in law_list if l.get("active"))

        # --- Bot vuelve online ---
        if self.was_offline:
            self.was_offline = False
            self.last_report = now  # evita doble msg
            await self.send(
                "🟢 CT4 Monitor Activo\n\n"
                f"💰 BTC: ${self.fmt(price)}\n"
                f"📊 RSI: {self.fmt(rsi,1)} | ADX: {self.fmt(adx,1)}\n"
                f"💼 Equity: ${self.fmt(equity)}\n"
                f"⚡ Leyes: {active_count}/4\n\n"
                "📡 Monitoreando cada 30s..."
            )

        # --- Nueva señal/trade ---
        if signals > self.last_signals:
            await self.send(
                "🎯🎯🎯 ¡SEÑAL EMITIDA! 🎯🎯🎯\n\n"
                f"💰 Precio: ${self.fmt(price)}\n"
                f"📊 RSI: {self.fmt(rsi,1)} | ADX: {self.fmt(adx,1)}\n"
                f"📈 Señal #{signals}\n\n"
                "🔍 Revisa el dashboard"
            )
            self.last_signals = signals

        # --- Kill Switch ---
        if kill and not self.last_kill:
            reason = rk.get("kill_reason", "Desconocido")
            await self.send(
                "🚨🚨🚨 KILL SWITCH ACTIVADO 🚨🚨🚨\n\n"
                f"⚠️ Razón: {reason}\n"
                f"📉 Drawdown: {self.fmt(dd,1)}%\n"
                f"💰 Equity: ${self.fmt(equity)}\n\n"
                "❌ Bot detenido"
            )
        self.last_kill = kill

        # --- Leyes cambian ---
        if active_count != self.last_laws_count and self.last_laws_count >= 0:
            laws_txt = "\n".join(
                f"  {'✅' if l['active'] else '❌'} {l['name']}: {l.get('detail','')}"
                for l in law_list
            )
            if active_count == 4:
                header = "🎯🎯 ¡4/4 LEYES! DISPARO INMINENTE!"
            elif active_count >= 3:
                header = f"⚡ {active_count}/4 Leyes — ¡Casi listo!"
            else:
                header = f"📋 {active_count}/4 Leyes"

            await self.send(
                f"{header}\n\n"
                f"{laws_txt}\n\n"
                f"💰 BTC: ${self.fmt(price)} | RSI: {self.fmt(rsi,1)}"
            )
        self.last_laws_count = active_count

        # --- Flash crash (ATR spike) ---
        if self.atr_baseline > 0 and atr > self.atr_baseline * ATR_SPIKE_MULT and atr != self.last_atr:
            await self.send(
                "💣 VOLATILIDAD EXTREMA\n\n"
                f"📊 ATR: ${self.fmt(atr)} (base: ${self.fmt(self.atr_baseline)})\n"
                f"📈 Spike: {(atr/self.atr_baseline):.1f}×\n"
                f"💰 BTC: ${self.fmt(price)}\n"
                f"📉 RSI: {self.fmt(rsi,1)}\n\n"
                "⚠️ Flash crash detectado"
            )
        self.last_atr = atr
        if self.atr_baseline == 0:
            self.atr_baseline = atr
        else:
            self.atr_baseline = self.atr_baseline * 0.95 + atr * 0.05

        # --- Reporte horario ---
        if now - self.last_report >= REPORT_INTERVAL:
            laws_mini = " | ".join(
                f"{'✅' if l['active'] else '❌'}{l['name'][:5]}"
                for l in law_list
            )
            ema200 = mk.get("ema_200", 0)
            gap = ((price - ema200) / ema200 * 100) if ema200 else 0

            await self.send(
                "📊 Reporte Horario CT4\n"
                "━━━━━━━━━━━━━━━\n"
                f"💰 BTC: ${self.fmt(price)}\n"
                f"📈 RSI: {self.fmt(rsi,1)} | ADX: {self.fmt(adx,1)}\n"
                f"📏 EMA200: {gap:+.2f}%\n"
                f"💼 Equity: ${self.fmt(equity)}\n"
                f"📉 DD: {self.fmt(dd,1)}%\n"
                f"🎯 Señales: {signals}/{evals}\n"
                f"⚡ {laws_mini}\n"
                f"🕐 {datetime.now().strftime('%H:%M')}"
            )
            self.last_report = now

    async def run(self):
        """Loop principal."""
        print("=" * 50)
        print("📱 CT4 Telegram Monitor")
        print(f"   API: {API_URL}")
        print(f"   Chat: {CHAT_ID}")
        print(f"   Poll: c/{POLL_SECONDS}s | Reporte: c/{REPORT_INTERVAL//60}min")
        print("=" * 50)

        while True:
            data = await self.poll_api()

            if data:
                self.poll_count += 1
                mk = data.get("market", {})
                laws = data.get("laws", {}).get("laws", [])
                ac = sum(1 for l in laws if l.get("active"))
                if self.poll_count % 10 == 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] #{self.poll_count} "
                          f"BTC=${mk.get('price',0):,.2f} RSI={mk.get('rsi',0):.1f} "
                          f"ADX={mk.get('adx',0):.1f} Laws={ac}/4")
                await self.check_and_alert(data)
            else:
                if not self.was_offline:
                    self.was_offline = True
                    await self.send(
                        "🔴 CT4 Bot OFFLINE\n\n"
                        "❌ No se puede conectar al API.\n"
                        "Verifica que el bot está corriendo."
                    )
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ API offline")

            await asyncio.sleep(POLL_SECONDS)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


if __name__ == "__main__":
    monitor = TelegramMonitor()
    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        print("\n📱 Monitor detenido.")

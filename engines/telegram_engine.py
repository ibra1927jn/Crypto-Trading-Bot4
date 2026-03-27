"""
Crypto-Trading-Bot4 — Telegram Engine
=======================================
Doble función:
  1. ALERTAS (salida): Notifica trades, PnL, estado del bot
  2. SEÑALES (entrada): Parsea mensajes de canales de señales cripto

Usa python-telegram-bot (async). Coste: $0.
Necesitas crear un bot en @BotFather y obtener el token.
"""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict
from utils.logger import setup_logger

logger = setup_logger("TELEGRAM")

# Intentar importar telegram (opcional)
try:
    from telegram import Bot
    from telegram.error import TelegramError
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False
    logger.warning("⚠️ python-telegram-bot no instalado. Telegram deshabilitado.")


# ═══════════════════════════════════════════════════════
# COIN KEYWORDS para detectar señales en mensajes
# ═══════════════════════════════════════════════════════

COIN_KEYWORDS = {
    'XRP': ['XRP', 'XRPUSDT', 'ripple'],
    'DOGE': ['DOGE', 'DOGEUSDT', 'dogecoin'],
    'AVAX': ['AVAX', 'AVAXUSDT', 'avalanche'],
    'SHIB': ['SHIB', 'SHIBUSDT', 'shiba'],
    'SOL': ['SOL', 'SOLUSDT', 'solana'],
}

BUY_KEYWORDS = [
    'buy', 'long', 'compra', 'bullish', '🟢', '🚀', '📈',
    'pump', 'breakout', 'entry', 'accumulate', 'oversold',
]

SELL_KEYWORDS = [
    'sell', 'short', 'venta', 'bearish', '🔴', '📉',
    'dump', 'breakdown', 'exit', 'overbought', 'take profit',
]


class TelegramEngine:
    """
    Motor de Telegram: alertas + parsing de señales.
    """

    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.enabled = bool(self.token and self.chat_id and HAS_TELEGRAM)
        self._bot: Optional[Bot] = None
        self._signal_buffer: List[dict] = []  # Señales parseadas pendientes

        if self.enabled:
            self._bot = Bot(token=self.token)
            logger.info(f"📲 Telegram Engine inicializado | Chat: {self.chat_id}")
        else:
            reasons = []
            if not self.token:
                reasons.append("sin TELEGRAM_BOT_TOKEN")
            if not self.chat_id:
                reasons.append("sin TELEGRAM_CHAT_ID")
            if not HAS_TELEGRAM:
                reasons.append("librería no instalada")
            logger.info(f"📲 Telegram Engine deshabilitado ({', '.join(reasons)})")

    # ═══════════════════════════════════════════════════════
    # ALERTAS (SALIDA) — Notificaciones al usuario
    # ═══════════════════════════════════════════════════════

    async def send_message(self, text: str, parse_mode: str = 'HTML'):
        """Envía un mensaje al chat configurado."""
        if not self.enabled:
            return

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
            )
        except TelegramError as e:
            logger.warning(f"⚠️ Error enviando Telegram: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Error Telegram inesperado: {e}")

    async def alert_trade_opened(self, symbol: str, side: str,
                                  amount: float, entry_price: float,
                                  sl_price: float, tp_price: float,
                                  score: float = 0):
        """Notifica cuando se abre una posición."""
        coin = symbol.split('/')[0]
        text = (
            f"🟢 <b>COMPRA {coin}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Precio: <code>${entry_price:.6f}</code>\n"
            f"📦 Cantidad: <code>{amount:.4f}</code>\n"
            f"🛡️ SL: <code>${sl_price:.6f}</code>\n"
            f"🎯 TP: <code>${tp_price:.6f}</code>\n"
            f"⭐ Score: <code>{score:.0f}/100</code>"
        )
        await self.send_message(text)

    async def alert_trade_closed(self, symbol: str, pnl: float,
                                  reason: str, entry_price: float,
                                  exit_price: float, duration_min: int = 0):
        """Notifica cuando se cierra una posición."""
        coin = symbol.split('/')[0]
        emoji = '🟢' if pnl > 0 else '🔴'
        pct = (exit_price / entry_price - 1) * 100 if entry_price else 0

        text = (
            f"{emoji} <b>VENTA {coin}</b> — {reason}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 PnL: <code>${pnl:+.2f} ({pct:+.1f}%)</code>\n"
            f"📊 {entry_price:.6f} → {exit_price:.6f}\n"
            f"⏱️ Duración: {duration_min}min"
        )
        await self.send_message(text)

    async def alert_daily_report(self, balance: float, daily_pnl: float,
                                  trades_today: int, wr: float,
                                  fear_greed: int = 0):
        """Envía reporte diario."""
        emoji = '🟢' if daily_pnl >= 0 else '🔴'
        fg_label = (
            'Extreme Fear' if fear_greed < 25 else
            'Fear' if fear_greed < 45 else
            'Neutral' if fear_greed < 55 else
            'Greed' if fear_greed < 75 else
            'Extreme Greed'
        )

        text = (
            f"📊 <b>REPORTE DIARIO</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 Balance: <code>${balance:.2f}</code>\n"
            f"{emoji} PnL hoy: <code>${daily_pnl:+.2f}</code>\n"
            f"📈 Trades: <code>{trades_today}</code> | WR: <code>{wr:.0f}%</code>\n"
            f"😱 Fear&Greed: <code>{fear_greed} ({fg_label})</code>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        await self.send_message(text)

    async def alert_kill_switch(self, reason: str, balance: float):
        """Alerta URGENTE cuando se activa el kill switch."""
        text = (
            f"🚨🚨🚨 <b>KILL SWITCH ACTIVADO</b> 🚨🚨🚨\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ Razón: {reason}\n"
            f"💰 Balance: ${balance:.2f}\n"
            f"🛑 Bot DETENIDO. Revisa manualmente."
        )
        await self.send_message(text)

    async def alert_startup(self, symbols: List[str], balance: float):
        """Notifica que el bot se ha iniciado."""
        coins = ', '.join(s.split('/')[0] for s in symbols)
        text = (
            f"🚀 <b>BOT INICIADO</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🪙 Monedas: <code>{coins}</code>\n"
            f"💰 Balance: <code>${balance:.2f}</code>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        await self.send_message(text)

    # ═══════════════════════════════════════════════════════
    # SEÑALES (ENTRADA) — Parsear mensajes de canales
    # ═══════════════════════════════════════════════════════

    def parse_signal(self, text: str) -> Optional[dict]:
        """
        Parsea un mensaje de texto buscando señales de trading.
        
        Returns:
            {'coin': 'XRP', 'direction': 'BUY', 'confidence': 0.7} or None
        """
        if not text:
            return None

        text_lower = text.lower()

        # Detectar moneda
        detected_coin = None
        for coin, keywords in COIN_KEYWORDS.items():
            if any(kw.lower() in text_lower for kw in keywords):
                detected_coin = coin
                break

        if not detected_coin:
            return None

        # Detectar dirección
        buy_count = sum(1 for kw in BUY_KEYWORDS if kw in text_lower)
        sell_count = sum(1 for kw in SELL_KEYWORDS if kw in text_lower)

        if buy_count == 0 and sell_count == 0:
            return None

        direction = 'BUY' if buy_count > sell_count else 'SELL'
        confidence = min(1.0, max(buy_count, sell_count) / 3)

        signal = {
            'coin': detected_coin,
            'symbol': f'{detected_coin}/USDT',
            'direction': direction,
            'confidence': confidence,
            'source': 'telegram',
            'raw': text[:200],
        }

        logger.info(
            f"📲 Señal detectada: {direction} {detected_coin} "
            f"(conf: {confidence:.0%})"
        )
        return signal

    def get_signal_boost(self, symbol: str) -> int:
        """
        Retorna score boost basado en señales de Telegram recientes.
        Llamado por el Alpha Engine.
        
        Returns: -10 a +10
        """
        relevant = [s for s in self._signal_buffer
                     if s['symbol'] == symbol]

        if not relevant:
            return 0

        buy_signals = sum(1 for s in relevant if s['direction'] == 'BUY')
        sell_signals = sum(1 for s in relevant if s['direction'] == 'SELL')

        if buy_signals > sell_signals:
            return min(10, buy_signals * 5)
        elif sell_signals > buy_signals:
            return max(-10, -sell_signals * 5)
        return 0

    def add_signal(self, signal: dict):
        """Añade una señal al buffer (máximo 20)."""
        self._signal_buffer.append(signal)
        if len(self._signal_buffer) > 20:
            self._signal_buffer = self._signal_buffer[-20:]

    def clear_old_signals(self, max_age_minutes: int = 30):
        """Limpia señales antiguas del buffer."""
        # Simple: just keep last 10
        self._signal_buffer = self._signal_buffer[-10:]

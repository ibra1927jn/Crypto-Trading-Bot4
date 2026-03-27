"""
Crypto-Trading-Bot4 — Sniper Rotativo
======================================
Vigila 5 monedas, pone TODO en la MEJOR señal, cierra, rota.
Solo 1 posición abierta a la vez. Máxima concentración.

Ciclo: Data → Score 5 monedas → Comprar la MEJOR → Monitorear → Cerrar → Repetir
"""

import asyncio
import sys
import uvicorn
from db.database import init_db, get_open_positions, close_position
from engines.execution_engine import ExecutionEngine
from engines.data_engine import DataEngine
from engines.risk_engine import RiskEngine
from engines.alpha_engine import AlphaEngine
from engines.news_engine import NewsEngine
from engines.telegram_engine import TelegramEngine
from api.server import app as web_app, set_bot_reference
from config.settings import (
    SYMBOLS, SYMBOL, EXCHANGE_ID, EXCHANGE_SANDBOX,
    ACTIVE_STRATEGY, TRAIL_PCT, SL_PCT, TP_PCT
)
import os
from utils.logger import setup_logger

logger = setup_logger("MAIN")

DASHBOARD_PORT = 8080


class TradingBot:
    """Sniper Rotativo: vigila 5 monedas, dispara en la mejor, rota."""

    def __init__(self):
        self.running = False
        self.execution_engine = ExecutionEngine()
        self.data_engine = DataEngine()
        self.risk_engine = RiskEngine()
        self.alpha_engine = AlphaEngine()
        self.news_engine = NewsEngine(
            cryptopanic_token=os.getenv('CRYPTOPANIC_TOKEN')
        )
        self.telegram = TelegramEngine()
        self.active_symbol = None  # Moneda en la que tenemos posición

    async def startup(self):
        """Secuencia de arranque."""
        logger.info("=" * 60)
        logger.info("🚀 SNIPER ROTATIVO — Iniciando...")
        logger.info(f"   Exchange: {EXCHANGE_ID} | Sandbox: {EXCHANGE_SANDBOX}")
        logger.info(f"   Monedas: {', '.join(SYMBOLS)}")
        logger.info(f"   Estrategia: RSI7<25 Ultra | SL:{SL_PCT}% | TP:+{TP_PCT}%")
        logger.info(f"   Modo: Secuencial (1 posición, toda el capital)")
        logger.info(f"   Dashboard: http://localhost:{DASHBOARD_PORT}")
        logger.info("=" * 60)

        await init_db()
        await self.execution_engine.connect()

        wake_up = await self.execution_engine.wake_up_sequence()
        logger.info(
            f"📊 Wake-up: USDT=${wake_up['usdt_free']:.2f} | "
            f"Órdenes={wake_up['open_orders']} | "
            f"Posiciones={wake_up['local_positions']}"
        )

        await self.risk_engine.initialize(
            wake_up['usdt_free'],
            exchange=self.execution_engine.exchange
        )
        await self.data_engine.warmup(self.execution_engine.exchange)
        self.data_engine.set_on_candle_close(self._on_new_candle)

        set_bot_reference(self)
        self.running = True
        logger.info("✅ Sniper Rotativo listo. Vigilando 5 monedas. 🎯")

        # Telegram: notificar inicio
        await self.telegram.alert_startup(SYMBOLS, wake_up['usdt_free'])

    async def shutdown(self):
        if not self.running:
            return
        logger.info("🛑 Iniciando shutdown limpio...")
        self.running = False
        await self.data_engine.stop_websocket()
        await self.execution_engine.disconnect()
        await self.news_engine.close()
        logger.info("👋 Bot apagado correctamente.")

    # ==========================================================
    # CICLO PRINCIPAL: SNIPER ROTATIVO
    # ==========================================================

    async def _on_new_candle(self):
        """
        Cada vela cerrada:
        1. Si tenemos posición → monitorear (SL/TP/trailing/exit)
        2. Si NO tenemos posición → buscar la MEJOR señal entre las 5 monedas
        """
        if not self.running:
            return

        try:
            # ── 0. RECONCILIACIÓN: ¿Se cerró alguna posición? ──
            await self._check_all_positions()

            # ── 1. LOG del estado de las 5 monedas ──
            snapshots = self.data_engine.get_all_snapshots()
            self._log_market_status(snapshots)

            # ── 2. ¿Tenemos posición abierta? ──
            has_position = self.active_symbol is not None

            if has_position:
                # ── MODO MONITOR: trailing stop + exit por RSI ──
                await self._monitor_position(snapshots)
            else:
                # ── MODO CAZA: buscar la mejor señal ──
                await self._hunt_best_signal(snapshots)

        except Exception as e:
            logger.error(f"❌ Error en ciclo: {e}", exc_info=True)

    def _log_market_status(self, snapshots: dict):
        """Log compacto del estado de las 5 monedas."""
        parts = []
        for sym, snap in snapshots.items():
            coin = sym.split('/')[0]
            rsi7 = snap.get('rsi_7', 0)
            emoji = '🟢' if rsi7 < 25 else ('🟡' if rsi7 < 35 else '⚪')
            parts.append(f"{emoji}{coin}:R7={rsi7:.0f}")
        logger.info(f"📊 {' | '.join(parts)}")

    # ==========================================================
    # MODO CAZA: Buscar la mejor señal
    # ==========================================================

    async def _hunt_best_signal(self, snapshots: dict):
        """Evalúa todas las monedas y compra la mejor."""
        dataframes = self.data_engine.get_all_dataframes()

        # Obtener scores externos (noticias + Fear&Greed)
        try:
            external_scores = await self.news_engine.get_all_scores(SYMBOLS)
        except Exception as e:
            logger.warning(f"⚠️ Error obteniendo datos externos: {e}")
            external_scores = None

        signal = self.alpha_engine.get_best_signal(
            snapshots=snapshots,
            dataframes=dataframes,
            has_position=False,
            external_scores=external_scores,
        )

        if signal['signal'] != 'BUY':
            return  # Sin señal digna

        target_symbol = signal['symbol']
        score = signal['score']

        # ── RISK CHECK ──
        balance_info = await self.execution_engine.get_balance()
        balance = balance_info['USDT_free']
        market = snapshots.get(target_symbol, {})

        validation = await self.risk_engine.validate_signal(
            signal='BUY',
            market_data=market,
            balance=balance,
            consecutive_errors=self.execution_engine.consecutive_errors
        )

        if not validation['approved']:
            logger.debug(f"🚫 Señal rechazada por Risk: {validation['reason']}")
            if self.risk_engine.kill_switch_active:
                await self.telegram.alert_kill_switch(
                    validation['reason'], balance
                )
                await self.execution_engine.emergency_shutdown()
                self.running = False
            return

        # ── EJECUTAR COMPRA ──
        # Temporalmente cambiar el SYMBOL activo para el execution engine
        result = await self.execution_engine.execute_market_order(
            side='BUY',
            amount=validation['position_size'],
            sl_price=validation['sl_price'],
            tp_price=validation['tp_price'],
            symbol=target_symbol,
        )

        if result:
            self.active_symbol = target_symbol
            logger.info(
                f"🟢 COMPRA {target_symbol}: {result['amount']} "
                f"@ ${result['entry_price']:.6f} | Score: {score:.0f} | "
                f"SL=${validation['sl_price']:.6f} | TP=${validation['tp_price']:.6f}"
            )

            # Telegram: notificar compra
            await self.telegram.alert_trade_opened(
                symbol=target_symbol, side='BUY',
                amount=result['amount'],
                entry_price=result['entry_price'],
                sl_price=validation['sl_price'],
                tp_price=validation['tp_price'],
                score=score,
            )

            # Actualizar balance
            new_bal = await self.execution_engine.get_balance()
            await self.risk_engine.update_balance(new_bal['USDT_free'])

    # ==========================================================
    # MODO MONITOR: Vigilar posición abierta
    # ==========================================================

    async def _monitor_position(self, snapshots: dict):
        """Monitorea la posición abierta: trailing, RSI exit."""
        symbol = self.active_symbol
        if not symbol:
            return

        market = snapshots.get(symbol, {})
        df = self.data_engine.get_dataframe(symbol)

        # ── Trailing Stop ──
        open_positions = await get_open_positions(symbol)
        buy_positions = [p for p in open_positions if p.get('side') == 'BUY']

        for pos in buy_positions:
            await self._update_trailing_stop(pos, market, symbol)

        # ── RSI Exit ──
        if df is not None and self.alpha_engine.should_exit(df) and buy_positions:
            pos = buy_positions[0]
            await self._close_position(pos, symbol, reason="RSI Exit")

    async def _close_position(self, pos: dict, symbol: str, reason: str = ""):
        """Cierra una posición y limpia el estado."""
        # Cancelar SL/TP existentes
        for order_key in ['sl_order_id', 'tp_order_id']:
            order_id = pos.get(order_key)
            if order_id:
                try:
                    await self.execution_engine._retry(
                        self.execution_engine.exchange.cancel_order,
                        order_id, symbol)
                except Exception:
                    pass

        # Vender a mercado
        try:
            amount = float(self.execution_engine.exchange.amount_to_precision(
                symbol, pos['amount']))
            order = await self.execution_engine._retry(
                self.execution_engine.exchange.create_order,
                symbol, 'market', 'sell', amount)
            sell_price = order.get('average') or order.get('price', 0)
            pnl = (sell_price - pos['entry_price']) * pos['amount']
            await close_position(pos['id'], pnl)

            emoji = '🟢' if pnl > 0 else '🔴'
            logger.info(
                f"{emoji} VENTA {symbol}: {pos['amount']} @ ${sell_price:.6f} | "
                f"PnL: ${pnl:+.2f} | Razón: {reason}"
            )

            # Telegram: notificar venta
            await self.telegram.alert_trade_closed(
                symbol=symbol, pnl=pnl, reason=reason,
                entry_price=pos['entry_price'], exit_price=sell_price,
            )
        except Exception as e:
            logger.error(f"❌ Error cerrando posición {symbol}: {e}")

        # Limpiar estado → listo para la siguiente caza
        self.active_symbol = None
        new_bal = await self.execution_engine.get_balance()
        await self.risk_engine.update_balance(new_bal['USDT_free'])

    # ==========================================================
    # TRAILING STOP
    # ==========================================================

    async def _update_trailing_stop(self, pos: dict, market: dict, symbol: str):
        """Trailing Stop basado en porcentaje."""
        entry = pos.get('entry_price', 0)
        current_sl = pos.get('sl_price', 0)
        sl_order_id = pos.get('sl_order_id')
        price = market.get('price', 0)

        if not entry or not price or not sl_order_id:
            return

        gain_pct = (price - entry) / entry * 100
        if gain_pct < TRAIL_PCT:
            return

        trail_distance = price * (TRAIL_PCT / 100)
        new_sl = price - trail_distance

        if new_sl <= current_sl:
            return

        sl_improvement = (new_sl - current_sl) / current_sl * 100
        if sl_improvement < 0.2:
            return

        try:
            new_sl = float(self.execution_engine.exchange.price_to_precision(
                symbol, new_sl
            ))

            await self.execution_engine._retry(
                self.execution_engine.exchange.cancel_order,
                sl_order_id, symbol
            )

            new_sl_order = await self.execution_engine._retry(
                self.execution_engine.exchange.create_order,
                symbol, 'stop_loss_limit', 'sell', pos['amount'],
                new_sl, {'stopPrice': new_sl}
            )
            new_sl_id = new_sl_order['id']

            from db.database import get_connection
            db = await get_connection()
            try:
                await db.execute(
                    "UPDATE positions SET sl_price = ?, sl_order_id = ? WHERE id = ?",
                    (new_sl, new_sl_id, pos['id'])
                )
                await db.commit()
            finally:
                await db.close()

            logger.info(
                f"📈 TRAILING {symbol}: ${current_sl:.6f} → ${new_sl:.6f} | "
                f"Gain: +{gain_pct:.1f}%"
            )

        except Exception as e:
            logger.warning(f"⚠️ Error trailing {symbol}: {e}")

    # ==========================================================
    # RECONCILIACIÓN
    # ==========================================================

    async def _check_all_positions(self):
        """Verifica si alguna posición fue cerrada por SL/TP del exchange."""
        if self.active_symbol:
            recon = await self.execution_engine.check_open_positions(
                symbol=self.active_symbol
            )
            if recon['positions_closed'] > 0:
                logger.info(
                    f"🔄 Recon {self.active_symbol}: {recon['positions_closed']} cerradas | "
                    f"PnL: ${recon['total_pnl']:.2f}"
                )
                self.active_symbol = None  # Liberado para la siguiente caza
                new_bal = await self.execution_engine.get_balance()
                await self.risk_engine.update_balance(new_bal['USDT_free'])

    # ==========================================================
    # RUN
    # ==========================================================

    async def run(self):
        """Loop principal: bot + dashboard."""
        await self.startup()

        try:
            config = uvicorn.Config(
                web_app, host="0.0.0.0", port=DASHBOARD_PORT,
                log_level="warning"
            )
            server = uvicorn.Server(config)

            ws_task = asyncio.create_task(self.data_engine.start_websocket())
            web_task = asyncio.create_task(server.serve())

            logger.info(
                f"📡 WebSocket multi-coin + Dashboard — "
                f"http://localhost:{DASHBOARD_PORT}"
            )

            while self.running:
                await asyncio.sleep(1)

            ws_task.cancel()
            server.should_exit = True
            try:
                await ws_task
            except asyncio.CancelledError:
                pass
            await web_task

        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()


async def main():
    bot = TradingBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Shutdown por Ctrl+C.")
    except Exception as e:
        logger.critical(f"💀 Error fatal: {e}", exc_info=True)
        sys.exit(1)

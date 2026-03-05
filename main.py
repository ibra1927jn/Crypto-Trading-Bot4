"""
Crypto-Trading-Bot4 — Orquestador Principal
============================================
Coordina los 4 motores + Dashboard web:
  Data (vela cierra) → Alpha (4 leyes) → Risk (ATR sizing) → Execution (OCO)
  + FastAPI en el mismo event loop para el Centro de Mando
"""

import asyncio
import sys
import uvicorn
from db.database import init_db, get_open_positions, close_position
from engines.execution_engine import ExecutionEngine
from engines.data_engine import DataEngine
from engines.risk_engine import RiskEngine
from engines.alpha_engine import AlphaEngine
from api.server import app as web_app, set_bot_reference
from config.settings import SYMBOL, EXCHANGE_ID, EXCHANGE_SANDBOX
from utils.logger import setup_logger

logger = setup_logger("MAIN")

DASHBOARD_PORT = 8080


class TradingBot:
    """Orquestador: coordina los 4 motores + dashboard."""

    def __init__(self):
        self.running = False
        self.execution_engine = ExecutionEngine()
        self.data_engine = DataEngine()
        self.risk_engine = RiskEngine()
        self.alpha_engine = AlphaEngine()

    async def startup(self):
        """Secuencia de arranque completa."""
        logger.info("=" * 60)
        logger.info("🚀 CRYPTO-TRADING-BOT4 — Iniciando...")
        logger.info(f"   Exchange: {EXCHANGE_ID} | Sandbox: {EXCHANGE_SANDBOX}")
        logger.info(f"   Símbolo: {SYMBOL}")
        logger.info(f"   Estrategia: Trend-Momentum Híbrido (EMA200+ADX+Vol+Cross)")
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

        # Pasar el exchange al Risk Engine para calcular Total Equity
        await self.risk_engine.initialize(
            wake_up['usdt_free'],
            exchange=self.execution_engine.exchange
        )
        await self.data_engine.warmup(self.execution_engine.exchange)
        self.data_engine.set_on_candle_close(self._on_new_candle)

        # Inyectar referencia al bot para la API
        set_bot_reference(self)

        self.running = True
        logger.info("✅ Todos los sistemas operativos. Francotirador en posición. 🎯")

    async def shutdown(self):
        """Apagado limpio."""
        if not self.running:
            return
        logger.info("🛑 Iniciando shutdown limpio...")
        self.running = False
        await self.data_engine.stop_websocket()
        await self.execution_engine.disconnect()
        logger.info("👋 Bot apagado correctamente.")

    async def _on_new_candle(self):
        """
        V2: Data → Trailing → Alpha (Momentum) → Risk → Execution
        """
        if not self.running:
            return

        try:
            # 0. RECONCILIACIÓN OCO: Detectar posiciones cerradas por Binance
            recon = await self.execution_engine.check_open_positions()
            if recon['positions_closed'] > 0:
                logger.info(
                    f"🔄 Recon: {recon['positions_closed']} posiciones cerradas | "
                    f"PnL: ${recon['total_pnl']:.2f}"
                )
                # Actualizar balance tras cierre
                new_bal = await self.execution_engine.get_balance()
                await self.risk_engine.update_balance(new_bal['USDT_free'])

            # 1. DATA: Snapshot del mercado
            market = self.data_engine.get_market_snapshot()
            df = self.data_engine.get_dataframe()

            logger.info(
                f"📈 Precio: ${market['price']:.2f} | "
                f"EMA200: {market.get('ema_200', 0):.2f} | "
                f"ADX: {market.get('adx', 0):.1f} | "
                f"ATR: {market.get('atr', 0):.2f}"
            )

            # 1.5 TRAILING STOP — Rate-limit safe
            open_positions = await get_open_positions(SYMBOL)
            buy_positions = [p for p in open_positions if p.get('side') == 'BUY']
            
            for pos in buy_positions:
                await self._update_trailing_stop(pos, market)

            # 2. ALPHA: Evaluar señales
            has_position = len(buy_positions) > 0
            signal = self.alpha_engine.get_signal(df, has_position)

            if signal == 'HOLD':
                return

            # ISS-06: Max 1 posición abierta por símbolo
            if signal == 'BUY' and has_position:
                logger.debug("🚫 BUY bloqueado: ya hay posición abierta")
                return

            # 3. RISK: Validar señal + calcular sizing
            balance_info = await self.execution_engine.get_balance()
            balance = balance_info['USDT_free']

            validation = await self.risk_engine.validate_signal(
                signal=signal,
                market_data=market,
                balance=balance,
                consecutive_errors=self.execution_engine.consecutive_errors
            )

            if not validation['approved']:
                logger.debug(f"🚫 Señal rechazada: {validation['reason']}")
                if self.risk_engine.kill_switch_active:
                    await self.execution_engine.emergency_shutdown()
                    self.running = False
                return

            # 4. EXECUTION: Disparar
            if signal == 'BUY':
                result = await self.execution_engine.execute_market_order(
                    side='BUY',
                    amount=validation['position_size'],
                    sl_price=validation['sl_price'],
                    tp_price=validation['tp_price'],
                )
                if result:
                    logger.info(
                        f"🟢 COMPRA ejecutada: {result['amount']} {SYMBOL} "
                        f"@ ${result['entry_price']:.2f} | "
                        f"SL=${validation['sl_price']:.2f} | "
                        f"TP=${validation['tp_price']:.2f}"
                    )

            elif signal == 'SELL' and has_position and len(buy_positions) > 0:
                pos = buy_positions[0]
                # BUG-01 FIX: Cancelar SL/TP existentes antes de vender
                if pos.get('sl_order_id'):
                    try:
                        await self.execution_engine._retry(
                            self.execution_engine.exchange.cancel_order,
                            pos['sl_order_id'], SYMBOL)
                        logger.info(f"🗑️ SL cancelado: {pos['sl_order_id']}")
                    except Exception:
                        pass  # Puede que ya se ejecutó
                if pos.get('tp_order_id'):
                    try:
                        await self.execution_engine._retry(
                            self.execution_engine.exchange.cancel_order,
                            pos['tp_order_id'], SYMBOL)
                        logger.info(f"🗑️ TP cancelado: {pos['tp_order_id']}")
                    except Exception:
                        pass
                # Vender directamente sin guardar nueva posición
                try:
                    amount = float(self.execution_engine.exchange.amount_to_precision(
                        SYMBOL, pos['amount']))
                    order = await self.execution_engine._retry(
                        self.execution_engine.exchange.create_order,
                        SYMBOL, 'market', 'sell', amount)
                    sell_price = order.get('average') or order.get('price', 0)
                    pnl = (sell_price - pos['entry_price']) * pos['amount']
                    await close_position(pos['id'], pnl)
                    logger.info(
                        f"🔴 VENTA ejecutada: {pos['amount']} {SYMBOL} "
                        f"@ ${sell_price:.2f} | PnL: ${pnl:.2f}"
                    )
                except Exception as e:
                    logger.error(f"❌ Error ejecutando SELL: {e}")

            # Actualizar balance en Risk Engine
            new_balance = await self.execution_engine.get_balance()
            await self.risk_engine.update_balance(new_balance['USDT_free'])

        except Exception as e:
            logger.error(f"❌ Error en ciclo de trading: {e}", exc_info=True)
    async def _update_trailing_stop(self, pos: dict, market: dict):
        """
        Trailing Stop — Rate-limit safe.
        
        Rules:
          1. Only activates when price is ≥0.5% above entry
          2. New SL = price - 1.0×ATR
          3. Only updates exchange if new SL is ≥0.2% higher than current SL
          4. Maximum 1 update per candle (runs once per 5min)
        """
        entry = pos.get('entry_price', 0)
        current_sl = pos.get('sl_price', 0)
        sl_order_id = pos.get('sl_order_id')
        price = market.get('price', 0)
        atr = market.get('atr', 0)
        
        if not entry or not price or not atr or not sl_order_id:
            return  # No data or no SL order to trail
        
        # Only trail if price is ≥0.5% above entry
        gain_pct = (price - entry) / entry * 100
        if gain_pct < 0.5:
            return
        
        # Calculate new SL: price - 1.0×ATR (tight trailing)
        new_sl = price - 1.0 * atr
        
        # Never move SL below current SL (only up)
        if new_sl <= current_sl:
            return
        
        # Only update if new SL is ≥0.2% higher than current (rate-limit protection)
        sl_improvement = (new_sl - current_sl) / current_sl * 100
        if sl_improvement < 0.2:
            return
        
        # ── EXECUTE: Cancel old SL → Place new SL ──
        try:
            new_sl = float(self.execution_engine.exchange.price_to_precision(
                SYMBOL, new_sl
            ))
            
            # Cancel old SL
            await self.execution_engine._retry(
                self.execution_engine.exchange.cancel_order,
                sl_order_id, SYMBOL
            )
            
            # Place new SL (BUG-02 FIX: stop_loss_limit for Spot)
            new_sl_order = await self.execution_engine._retry(
                self.execution_engine.exchange.create_order,
                SYMBOL, 'stop_loss_limit', 'sell', pos['amount'],
                new_sl, {'stopPrice': new_sl}
            )
            new_sl_id = new_sl_order['id']
            
            # Update SQLite
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
                f"📈 TRAILING SL #{pos['id']}: ${current_sl:.2f} → ${new_sl:.2f} "
                f"(+{sl_improvement:.1f}%) | Precio: ${price:.2f} | "
                f"Ganancia: +{gain_pct:.1f}%"
            )
            
        except Exception as e:
            logger.warning(f"⚠️ Error actualizando trailing SL: {e}")

    async def run(self):
        """Loop principal: bot + dashboard en el mismo event loop."""
        await self.startup()

        try:
            # Arrancar FastAPI en el mismo event loop (sin bloquear)
            config = uvicorn.Config(
                web_app, host="0.0.0.0", port=DASHBOARD_PORT,
                log_level="warning"  # Silenciar logs de uvicorn
            )
            server = uvicorn.Server(config)

            # Correr WebSocket + Dashboard en paralelo
            ws_task = asyncio.create_task(self.data_engine.start_websocket())
            web_task = asyncio.create_task(server.serve())

            logger.info(
                f"📡 WebSocket + Dashboard activos — "
                f"http://localhost:{DASHBOARD_PORT} | Ctrl+C para detener."
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

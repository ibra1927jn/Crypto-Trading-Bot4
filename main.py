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
from db.database import init_db, get_open_positions
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
        Ciclo completo ejecutado cuando se cierra una vela:
        Data → Alpha (4 leyes) → Risk (ATR sizing) → Execution (OCO)
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

            # 2. ALPHA: Evaluar las 4 leyes
            open_positions = await get_open_positions(SYMBOL)
            has_position = len(open_positions) > 0
            signal = self.alpha_engine.get_signal(df, has_position)

            if signal == 'HOLD':
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

            elif signal == 'SELL' and has_position:
                pos = open_positions[0]
                result = await self.execution_engine.execute_market_order(
                    side='SELL',
                    amount=pos['amount'],
                )
                if result:
                    logger.info(
                        f"🔴 VENTA ejecutada: {pos['amount']} {SYMBOL} "
                        f"@ ${result['entry_price']:.2f}"
                    )

            # Actualizar balance en Risk Engine
            new_balance = await self.execution_engine.get_balance()
            await self.risk_engine.update_balance(new_balance['USDT_free'])

        except Exception as e:
            logger.error(f"❌ Error en ciclo de trading: {e}", exc_info=True)

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

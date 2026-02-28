"""
Demon 3 Test: GASLIGHTING
=========================
Inyecta una posición FALSA en SQLite (5 BTC @ $50,000 que NUNCA existió)
y luego arranca el bot para ver si la Secuencia de Despertar detecta la mentira.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db, save_position, get_open_positions
from engines.execution_engine import ExecutionEngine
from utils.logger import setup_logger

logger = setup_logger("GASLIGHT")


async def run_gaslighting_test():
    logger.info("=" * 60)
    logger.info("👹 DEMON 3 TEST: GASLIGHTING")
    logger.info("=" * 60)

    # Fase 1: Inyectar posición FALSA
    logger.info("🕵️ Fase 1: Inyectando posición FALSA en SQLite...")
    await init_db()

    pos_id = await save_position(
        symbol='BTC/USDT',
        side='BUY',
        amount=5.0,          # 5 BTC que NO existen en Binance
        entry_price=50000.0,  # Precio inventado
        sl_price=None,        # Sin SL/TP (la trampa del gaslighting)
        tp_price=None,
        sl_order_id=None,     # Sin order IDs (bypass del viejo reconcile)
        tp_order_id=None,
    )
    logger.critical(f"💉 Posición FALSA #{pos_id} inyectada: 5 BTC @ $50,000")

    # Verificar que está en SQLite
    positions = await get_open_positions('BTC/USDT')
    logger.info(f"📂 Posiciones OPEN en SQLite: {len(positions)}")
    for p in positions:
        logger.info(f"  #{p['id']}: {p['amount']} BTC @ ${p['entry_price']} [{p['status']}]")

    # Fase 2: Arrancar el Execution Engine con wake-up
    logger.info("")
    logger.info("=" * 60)
    logger.info("🕵️ Fase 2: Arrancando bot — ¿detectará la mentira?")
    logger.info("=" * 60)

    exec_engine = ExecutionEngine()
    await exec_engine.connect()
    wake_up = await exec_engine.wake_up_sequence()

    # Fase 3: Verificar resultado
    logger.info("")
    logger.info("=" * 60)
    logger.info("🕵️ Fase 3: RESULTADO")
    logger.info("=" * 60)

    positions_after = await get_open_positions('BTC/USDT')
    logger.info(f"📂 Posiciones OPEN después del wake-up: {len(positions_after)}")

    if len(positions_after) == 0:
        logger.critical("🏆 GASLIGHTING TEST: ✅ PASADO — El bot detectó la mentira y cerró la posición falsa")
    else:
        for p in positions_after:
            logger.info(f"  #{p['id']}: {p['amount']} BTC [{p['status']}]")
        logger.critical("🔴 GASLIGHTING TEST: ❌ FALLIDO — El bot se tragó la mentira")

    await exec_engine.disconnect()


if __name__ == "__main__":
    asyncio.run(run_gaslighting_test())

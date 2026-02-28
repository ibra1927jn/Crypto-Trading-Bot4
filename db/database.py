"""
Crypto-Trading-Bot4 — Base de Datos Blindada (SQLite Async + WAL)
=================================================================
Usa Write-Ahead Logging para permitir lecturas/escrituras concurrentes
sin el temido "database is locked" que mata bots en producción.

Tablas:
    - positions: Track de posiciones abiertas/cerradas/huérfanas
    - orders: Registro de órdenes enviadas al exchange
    - daily_pnl: Control de drawdown diario para el Kill Switch
"""

import aiosqlite
import os
from datetime import datetime, timezone
from typing import Optional
from config.settings import DB_PATH
from utils.logger import setup_logger

logger = setup_logger("DB")


async def get_connection() -> aiosqlite.Connection:
    """
    Abre una conexión a SQLite con WAL mode activado.
    SIEMPRE usar esta función para obtener conexiones.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row  # Acceso por nombre de columna
    
    # ¡CRÍTICO! Habilita escritura asíncrona concurrente
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    
    return db


async def init_db():
    """Inicializa el esquema de la base de datos si no existe."""
    logger.info("Inicializando base de datos SQLite (Modo WAL)...")
    
    db = await get_connection()
    try:
        # === TABLA DE POSICIONES ===
        await db.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT NOT NULL,
                side            TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
                amount          REAL NOT NULL,
                entry_price     REAL NOT NULL,
                sl_price        REAL,
                tp_price        REAL,
                sl_order_id     TEXT,
                tp_order_id     TEXT,
                status          TEXT NOT NULL DEFAULT 'OPEN'
                                CHECK(status IN ('OPEN', 'CLOSED', 'ORPHANED')),
                pnl             REAL,
                opened_at       TEXT NOT NULL DEFAULT (datetime('now')),
                closed_at       TEXT
            )
        """)
        
        # === TABLA DE ÓRDENES ===
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id         INTEGER REFERENCES positions(id),
                exchange_order_id   TEXT NOT NULL,
                symbol              TEXT NOT NULL,
                side                TEXT NOT NULL,
                type                TEXT NOT NULL,
                amount              REAL NOT NULL,
                price               REAL,
                status              TEXT NOT NULL DEFAULT 'PENDING',
                created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at          TEXT
            )
        """)

        # === TABLA DE CONTROL DE RIESGO DIARIO ===
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date                TEXT PRIMARY KEY,
                starting_balance    REAL NOT NULL,
                current_balance     REAL NOT NULL,
                drawdown_pct        REAL NOT NULL DEFAULT 0.0
            )
        """)

        # Índices para consultas rápidas
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_status 
            ON positions(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_exchange_id 
            ON orders(exchange_order_id)
        """)
        
        await db.commit()
        logger.info("✅ Base de datos lista y blindada contra colisiones (WAL activo).")
    finally:
        await db.close()


# =============================================
# Funciones de acceso a datos (CRUD)
# =============================================

async def get_open_positions(symbol: Optional[str] = None) -> list:
    """Obtiene todas las posiciones con status OPEN."""
    db = await get_connection()
    try:
        if symbol:
            cursor = await db.execute(
                "SELECT * FROM positions WHERE status = 'OPEN' AND symbol = ?",
                (symbol,)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM positions WHERE status = 'OPEN'"
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def save_position(symbol: str, side: str, amount: float, 
                        entry_price: float, sl_price: float = None,
                        tp_price: float = None, sl_order_id: str = None,
                        tp_order_id: str = None) -> int:
    """Guarda una nueva posición abierta. Retorna el ID."""
    db = await get_connection()
    try:
        cursor = await db.execute(
            """INSERT INTO positions 
               (symbol, side, amount, entry_price, sl_price, tp_price, 
                sl_order_id, tp_order_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
            (symbol, side, amount, entry_price, sl_price, tp_price,
             sl_order_id, tp_order_id)
        )
        await db.commit()
        position_id = cursor.lastrowid
        logger.debug(f"Posición #{position_id} guardada: {side} {amount} {symbol} @ {entry_price}")
        return position_id
    finally:
        await db.close()


async def close_position(position_id: int, pnl: float = None):
    """Marca una posición como CLOSED con timestamp y PnL."""
    db = await get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """UPDATE positions 
               SET status = 'CLOSED', closed_at = ?, pnl = ?
               WHERE id = ?""",
            (now, pnl, position_id)
        )
        await db.commit()
        logger.debug(f"Posición #{position_id} cerrada. PnL: {pnl}")
    finally:
        await db.close()


async def mark_position_orphaned(position_id: int):
    """Marca una posición como ORPHANED (huérfana) para reconciliación."""
    db = await get_connection()
    try:
        await db.execute(
            "UPDATE positions SET status = 'ORPHANED' WHERE id = ?",
            (position_id,)
        )
        await db.commit()
        logger.warning(f"⚠️ Posición #{position_id} marcada como HUÉRFANA.")
    finally:
        await db.close()


async def save_order(position_id: int, exchange_order_id: str, symbol: str,
                     side: str, order_type: str, amount: float, 
                     price: float = None):
    """Registra una orden enviada al exchange."""
    db = await get_connection()
    try:
        await db.execute(
            """INSERT INTO orders 
               (position_id, exchange_order_id, symbol, side, type, amount, price)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (position_id, exchange_order_id, symbol, side, order_type, 
             amount, price)
        )
        await db.commit()
        logger.debug(f"Orden {exchange_order_id} registrada ({order_type} {side})")
    finally:
        await db.close()


async def get_daily_pnl(date_str: str) -> Optional[dict]:
    """Obtiene el registro de PnL del día."""
    db = await get_connection()
    try:
        cursor = await db.execute(
            "SELECT * FROM daily_pnl WHERE date = ?", (date_str,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def upsert_daily_pnl(date_str: str, starting_balance: float,
                           current_balance: float):
    """Crea o actualiza el registro de PnL diario."""
    drawdown_pct = 0.0
    if starting_balance > 0:
        drawdown_pct = (starting_balance - current_balance) / starting_balance

    db = await get_connection()
    try:
        await db.execute(
            """INSERT INTO daily_pnl (date, starting_balance, current_balance, drawdown_pct)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                   current_balance = excluded.current_balance,
                   drawdown_pct = excluded.drawdown_pct""",
            (date_str, starting_balance, current_balance, drawdown_pct)
        )
        await db.commit()
    finally:
        await db.close()


async def get_trade_history(limit: int = 20):
    """Obtiene historial de posiciones cerradas/huérfanas."""
    db = await get_connection()
    try:
        cursor = await db.execute("""
            SELECT * FROM positions
            WHERE status IN ('CLOSED', 'ORPHANED')
            ORDER BY closed_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()

"""
Crypto-Trading-Bot4 — Execution Engine (Los Puños)
===================================================
Se pelea con la API del exchange. Gestiona:
  - Conexión async a Binance Testnet via CCXT
  - Secuencia de Despertar (wake_up_sequence)
  - Reconciliación bidireccional exchange ↔ SQLite
  - Órdenes OCO (Hard SL/TP) en el servidor del exchange
  - Reintentos con backoff exponencial
  - Shutdown de emergencia (cancel all + close all)
"""

import asyncio
import ccxt.async_support as ccxt
from typing import Optional
from config.settings import (
    API_KEY, API_SECRET, SYMBOL, SYMBOLS, MAX_RETRIES, RETRY_BASE_DELAY,
    EXCHANGE_ID, EXCHANGE_SANDBOX
)
from db.database import (
    get_open_positions, save_position, close_position,
    mark_position_orphaned, save_order
)
from utils.logger import setup_logger

logger = setup_logger("EXEC")


class ExecutionEngine:
    """
    Motor de ejecución: interfaz directa con el exchange.
    
    Responsabilidades:
      1. Conectar y autenticar con Binance Testnet
      2. Wake-up: reconciliar estado real vs local al arrancar
      3. Ejecutar órdenes con Hard SL/TP (OCO)
      4. Reintentar operaciones fallidas con backoff exponencial
      5. Emergency shutdown: cancelar todo y cerrar posiciones
    """

    def __init__(self):
        self.exchange: Optional[ccxt.binance] = None
        self.markets_loaded = False
        self.consecutive_errors = 0

    # ==========================================================
    # CONEXIÓN
    # ==========================================================

    async def connect(self):
        """Crea la conexión async a Binance Testnet."""
        logger.info("Conectando a Binance Testnet...")

        exchange_class = getattr(ccxt, EXCHANGE_ID)
        self.exchange = exchange_class({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'sandbox': EXCHANGE_SANDBOX,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
            }
        })

        # Cargar mercados (necesario para precision de decimales)
        await self._retry(self.exchange.load_markets)
        self.markets_loaded = True

        logger.info(f"✅ Conectado a Binance Testnet. Mercados cargados: {len(self.exchange.markets)}")

    async def disconnect(self):
        """Cierra la conexión al exchange limpiamente."""
        if self.exchange:
            await self.exchange.close()
            logger.info("Conexión al exchange cerrada.")

    # ==========================================================
    # SECUENCIA DE DESPERTAR (Wake-up)
    # ==========================================================

    async def wake_up_sequence(self) -> dict:
        """
        Secuencia de despertar: reconcilia el estado real del exchange
        con la base de datos local (SQLite).

        Itera todos los SYMBOLS (multi-coin) para detectar:
          - Posiciones que el exchange cerró mientras el bot estaba offline
          - Posiciones huérfanas en el exchange que SQLite no conoce

        Returns:
            dict con balance, posiciones reales y resultado de reconciliación
        """
        logger.info("=" * 50)
        logger.info("🔄 SECUENCIA DE DESPERTAR — Iniciando...")
        logger.info(f"   Vigilando {len(SYMBOLS)} monedas: {', '.join(SYMBOLS)}")
        logger.info("=" * 50)

        # 1. Leer BALANCE real del exchange
        balance = await self._retry(self.exchange.fetch_balance)
        usdt_free = balance.get('USDT', {}).get('free', 0)
        usdt_total = balance.get('USDT', {}).get('total', 0)
        logger.info(f"💰 Balance USDT — Libre: {usdt_free:.2f} | Total: {usdt_total:.2f}")

        # 2. Leer ÓRDENES ABIERTAS para TODOS los símbolos
        all_open_orders = []
        all_local_positions = []
        for sym in SYMBOLS:
            try:
                orders = await self._retry(self.exchange.fetch_open_orders, sym)
                all_open_orders.extend(orders)
                positions = await get_open_positions(sym)
                all_local_positions.extend(positions)
            except Exception as e:
                logger.warning(f"⚠️ Error leyendo {sym} en wake-up: {e}")

        logger.info(f"📋 Órdenes abiertas (todos los pares): {len(all_open_orders)}")
        logger.info(f"📂 Posiciones OPEN en SQLite: {len(all_local_positions)}")

        # 3. RECONCILIACIÓN BIDIRECCIONAL (usando primer símbolo como referencia)
        await self._reconcile(all_local_positions, all_open_orders, balance)

        logger.info("=" * 50)
        logger.info("✅ SECUENCIA DE DESPERTAR — Completada")
        logger.info("=" * 50)

        return {
            'usdt_free': usdt_free,
            'usdt_total': usdt_total,
            'open_orders': len(all_open_orders),
            'local_positions': len(all_local_positions),
        }

    async def _reconcile(self, local_positions: list, 
                         open_orders: list, balance: dict):
        """
        Reconciliación bidireccional:
        
        Caso A: SQLite OPEN con SL/TP → pero exchange ya no tiene esas órdenes
                → El Hard SL/TP se ejecutó mientras offline → CLOSED
        
        Caso A2 (GASLIGHTING FIX): SQLite OPEN sin SL/TP IDs
                → Verificar si el exchange realmente tiene el activo
                → Si no tiene → la posición es mentira → CLOSED
        
        Caso B: Exchange tiene activos que SQLite no conoce → ORPHANED
        """
        exchange_order_ids = {o['id'] for o in open_orders}

        # --- CASO A: SQLite OPEN pero exchange ya cerró ---
        open_positions_remaining = []
        for pos in local_positions:
            # Usar el símbolo de cada posición, no el global
            pos_symbol = pos.get('symbol', SYMBOL)
            pos_base = pos_symbol.split('/')[0]
            pos_base_balance = balance.get(pos_base, {}).get('total', 0)

            sl_id = pos.get('sl_order_id')
            tp_id = pos.get('tp_order_id')

            if sl_id or tp_id:
                # Posición CON órdenes protectoras: verificar si siguen vivas
                has_sl = sl_id and sl_id in exchange_order_ids
                has_tp = tp_id and tp_id in exchange_order_ids

                if not has_sl and not has_tp:
                    logger.warning(
                        f"📌 Posición #{pos['id']} ({pos_symbol}): "
                        f"SL/TP ya no están en exchange → CLOSED"
                    )
                    pnl = await self._fetch_closed_pnl(pos)
                    await close_position(pos['id'], pnl)
                else:
                    open_positions_remaining.append(pos)
            else:
                # CASO A2 (GASLIGHTING): Posición SIN órdenes protectoras
                # ¿El exchange realmente tiene el activo correspondiente?
                if pos_base_balance < pos.get('amount', 0) * 0.5:
                    logger.warning(
                        f"🕵️ GASLIGHTING DETECTADO: Posición #{pos['id']} dice OPEN "
                        f"pero exchange solo tiene {pos_base_balance:.6f} "
                        f"{pos_base} (necesita {pos['amount']:.6f}) → CLOSED"
                    )
                    pnl = await self._fetch_closed_pnl(pos)
                    await close_position(pos['id'], pnl)
                else:
                    open_positions_remaining.append(pos)

        # --- CASO B: Exchange tiene algo que SQLite no conoce ---
        # Revisar cada símbolo monitoreado por si hay activos huérfanos
        for sym in SYMBOLS:
            sym_base = sym.split('/')[0]
            sym_base_balance = balance.get(sym_base, {}).get('total', 0)
            # Verificar si hay posiciones locales abiertas para este símbolo
            has_local = any(
                p.get('symbol', '').split('/')[0] == sym_base
                for p in open_positions_remaining
            )
            if sym_base_balance > 0 and not has_local:
                logger.warning(
                    f"⚠️ ALERTA: Exchange tiene {sym_base_balance} {sym_base} "
                    f"pero SQLite no tiene posiciones OPEN. ¡POSICIÓN HUÉRFANA!"
                )
                ticker = await self._retry(
                    self.exchange.fetch_ticker, sym
                )
                current_price = ticker['last']
                pos_id = await save_position(
                    symbol=sym,
                    side='BUY',
                    amount=sym_base_balance,
                    entry_price=current_price,
                )
                await mark_position_orphaned(pos_id)

    async def _fetch_closed_pnl(self, position: dict) -> Optional[float]:
        """Intenta calcular el PnL de una posición cerrada via historial de trades."""
        try:
            trades = await self._retry(
                self.exchange.fetch_my_trades, position['symbol'], limit=20
            )
            # Buscar trades recientes que podrían corresponder al cierre
            for trade in reversed(trades):
                if trade['side'] != position['side']:
                    # Es un trade de cierre (sell si pos era buy, o viceversa)
                    close_price = trade['price']
                    if position['side'] == 'BUY':
                        pnl = (close_price - position['entry_price']) * position['amount']
                    else:
                        pnl = (position['entry_price'] - close_price) * position['amount']
                    logger.info(
                        f"💵 PnL calculado para posición #{position['id']}: "
                        f"${pnl:.2f}"
                    )
                    return pnl
        except Exception as e:
            logger.debug(f"No se pudo calcular PnL: {e}")
        return None

    # ==========================================================
    # RECONCILIACIÓN EN VIVO (cada vela)
    # ==========================================================

    async def check_open_positions(self, symbol: str = None) -> dict:
        """
        Loop de reconciliación OCO que corre cada vela.
        
        Detecta cuando Binance auto-ejecuta un SL o TP y:
          1. Identifica qué orden se ejecutó (SL o TP)
          2. Cancela la orden contraria (si SL hit → cancelar TP)
          3. Calcula PnL real
          4. Cierra la posición en SQLite
          
        Returns:
            dict con resultado de la reconciliación
        """
        result = {
            'positions_checked': 0,
            'positions_closed': 0,
            'total_pnl': 0.0,
            'actions': [],
        }
        
        try:
            sym = symbol or SYMBOL
            positions = await get_open_positions(sym)
            if not positions:
                return result

            result['positions_checked'] = len(positions)
            
            # Obtener órdenes abiertas en el exchange
            open_orders = await self._retry(
                self.exchange.fetch_open_orders, sym
            )
            exchange_order_ids = {o['id'] for o in open_orders}

            for pos in positions:
                sl_id = pos.get('sl_order_id')
                tp_id = pos.get('tp_order_id')
                
                if not sl_id and not tp_id:
                    # Posición sin protección OCO, skip
                    continue
                
                # Verificar si las órdenes siguen vivas
                sl_alive = sl_id and sl_id in exchange_order_ids
                tp_alive = tp_id and tp_id in exchange_order_ids
                
                if sl_alive and tp_alive:
                    # Ambas órdenes siguen vivas → posición protegida, nada que hacer
                    continue
                
                if sl_alive or tp_alive:
                    # UNA se ejecutó, la OTRA sigue viva → ¡OCO disparó!
                    which_hit = "TP" if sl_alive else "SL"
                    which_cancel = sl_id if sl_alive else tp_id
                    
                    logger.info(
                        f"🎯 OCO DISPARÓ: Posición #{pos['id']} — "
                        f"{which_hit} ejecutado | Cancelando {'SL' if sl_alive else 'TP'}..."
                    )
                    
                    # Cancelar la orden que AÚN está viva
                    try:
                        await self._retry(
                            self.exchange.cancel_order,
                            which_cancel, sym
                        )
                        logger.info(
                            f"✅ Orden {'SL' if sl_alive else 'TP'} cancelada: {which_cancel}"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Error cancelando orden: {e}")
                    
                    # Calcular PnL
                    pnl = await self._fetch_closed_pnl(pos)
                    
                    # Cerrar posición en SQLite
                    await close_position(pos['id'], pnl)
                    
                    result['positions_closed'] += 1
                    result['total_pnl'] += pnl or 0
                    result['actions'].append({
                        'position_id': pos['id'],
                        'trigger': which_hit,
                        'pnl': pnl,
                    })
                    
                    logger.info(
                        f"📊 Posición #{pos['id']} CERRADA por {which_hit} | "
                        f"PnL: ${pnl or 0:.2f} | "
                        f"Entrada: ${pos['entry_price']:.2f}"
                    )
                
                elif not sl_alive and not tp_alive:
                    # AMBAS desaparecieron → probablemente se ejecutaron offline
                    logger.warning(
                        f"📌 Posición #{pos['id']}: Ambas SL/TP desaparecieron → CLOSED"
                    )
                    pnl = await self._fetch_closed_pnl(pos)
                    await close_position(pos['id'], pnl)
                    result['positions_closed'] += 1
                    result['total_pnl'] += pnl or 0
                    result['actions'].append({
                        'position_id': pos['id'],
                        'trigger': 'BOTH_GONE',
                        'pnl': pnl,
                    })

            if result['positions_closed'] > 0:
                logger.info(
                    f"🔄 Reconciliación: {result['positions_closed']} posiciones cerradas | "
                    f"PnL total: ${result['total_pnl']:.2f}"
                )

        except Exception as e:
            logger.error(f"Error en reconciliación OCO: {e}")

        return result

    # ==========================================================
    # EJECUCIÓN DE ÓRDENES
    # ==========================================================

    async def execute_market_order(self, side: str, amount: float,
                                   sl_price: float = None,
                                   tp_price: float = None,
                                   symbol: str = None) -> Optional[dict]:
        """
        Ejecuta orden de mercado + Hard SL/TP en el exchange.
        
        Flujo:
          1. Truncar decimales según reglas del exchange (precision)
          2. Enviar orden de mercado (BUY/SELL)
          3. Inmediatamente enviar órdenes OCO (SL + TP) al exchange
          4. Guardar todo en SQLite
        
        Args:
            side: 'BUY' o 'SELL'
            amount: Cantidad base (ej: 0.001 BTC)
            sl_price: Precio del Stop Loss (Hard, en el exchange)
            tp_price: Precio del Take Profit
        
        Returns:
            dict con info de la operación o None si falló
        """
        if not self.markets_loaded:
            logger.error("❌ Mercados no cargados. Llama a connect() primero.")
            return None

        # 1. TRUNCAR PRECISIÓN (evitar HTTP 400 de Binance)
        sym = symbol or SYMBOL
        amount = float(self.exchange.amount_to_precision(sym, amount))
        if sl_price:
            sl_price = float(self.exchange.price_to_precision(sym, sl_price))
        if tp_price:
            tp_price = float(self.exchange.price_to_precision(sym, tp_price))

        logger.info(
            f"📤 Enviando orden: {side} {amount} {sym} | "
            f"SL: {sl_price} | TP: {tp_price}"
        )

        try:
            # 2. ORDEN DE MERCADO PRINCIPAL
            order = await self._retry(
                self.exchange.create_order,
                sym, 'market', side.lower(), amount
            )
            entry_price = order.get('average') or order.get('price', 0)
            logger.info(
                f"✅ Orden ejecutada: {order['id']} | "
                f"Precio: {entry_price} | Status: {order['status']}"
            )
            self.consecutive_errors = 0  # Reset error counter on success

            # 2.5 RACE CONDITION FIX: Esperar a que la orden se llene
            # antes de colocar OCO. Si no, Binance rechazará el SL/TP
            # con "Insufficient Balance" porque el activo aún no llegó.
            if order.get('status') != 'closed':  # CCXT: 'closed' = filled
                order = await self._wait_for_fill(order['id'], symbol=sym)
                entry_price = order.get('average') or order.get('price', entry_price)
                logger.info(f"✅ Orden confirmada como FILLED. Precio final: {entry_price}")

            # Safety delay: dar tiempo al exchange para actualizar balance
            await asyncio.sleep(0.5)

            # 3. HARD STOP LOSS (orden en el servidor del exchange)
            sl_order_id = None
            tp_order_id = None
            close_side = 'sell' if side.upper() == 'BUY' else 'buy'

            if sl_price:
                sl_order_id = await self._place_stop_loss(
                    close_side, amount, sl_price, sym
                )

            if tp_price:
                tp_order_id = await self._place_take_profit(
                    close_side, amount, tp_price, sym
                )

            position_id = await save_position(
                symbol=sym,
                side=side.upper(),
                amount=amount,
                entry_price=entry_price,
                sl_price=sl_price,
                tp_price=tp_price,
                sl_order_id=sl_order_id,
                tp_order_id=tp_order_id,
            )

            # Registrar la orden principal
            await save_order(
                position_id=position_id,
                exchange_order_id=order['id'],
                symbol=sym,
                side=side.upper(),
                order_type='MARKET',
                amount=amount,
                price=entry_price,
            )

            return {
                'position_id': position_id,
                'order_id': order['id'],
                'entry_price': entry_price,
                'amount': amount,
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id,
            }

        except Exception as e:
            self.consecutive_errors += 1
            logger.error(
                f"❌ Error ejecutando orden ({self.consecutive_errors} "
                f"errores consecutivos): {e}"
            )
            return None

    async def _place_stop_loss(self, side: str, amount: float, 
                                price: float, symbol: str = None) -> Optional[str]:
        """Coloca Hard Stop Loss en el servidor del exchange."""
        sym = symbol or SYMBOL
        try:
            sl_order = await self._retry(
                self.exchange.create_order,
                sym, 'stop_loss_limit', side, amount,
                price,  # limit price
                {'stopPrice': price}
            )
            logger.info(f"🛡️ Hard SL colocado: {sl_order['id']} @ {price}")
            return sl_order['id']
        except Exception as e:
            logger.error(f"❌ Error colocando SL: {e}")
            return None

    async def _place_take_profit(self, side: str, amount: float, 
                                  price: float, symbol: str = None) -> Optional[str]:
        """Coloca Take Profit en el servidor del exchange."""
        sym = symbol or SYMBOL
        try:
            tp_order = await self._retry(
                self.exchange.create_order,
                sym, 'take_profit_limit', side, amount,
                price,  # limit price
                {'stopPrice': price}
            )
            logger.info(f"🎯 Hard TP colocado: {tp_order['id']} @ {price}")
            return tp_order['id']
        except Exception as e:
            logger.error(f"❌ Error colocando TP: {e}")
            return None

    # ==========================================================
    # WAIT FOR ORDER FILL (Race Condition Prevention)
    # ==========================================================

    async def _wait_for_fill(self, order_id: str, symbol: str = None, max_checks: int = 10) -> dict:
        """
        Espera a que una orden de mercado se llene (status=closed).
        
        Binance puede tardar milisegundos a segundos en confirmar el fill.
        Si colocamos OCO antes del fill, Binance rechaza con
        "Insufficient Balance".
        
        Args:
            order_id: ID de la orden a verificar
            max_checks: Máximo de veces a comprobar
        
        Returns:
            dict de la orden actualizada (con status='closed')
        """
        for i in range(max_checks):
            await asyncio.sleep(0.3 * (1.5 ** i))  # 0.3s, 0.45s, 0.67s...
            order = await self._retry(
                self.exchange.fetch_order, order_id, symbol or SYMBOL
            )
            status = order.get('status')
            logger.debug(f"⏳ Esperando fill... intento {i+1}/{max_checks} | status={status}")
            
            if status == 'closed':  # CCXT: 'closed' = filled
                return order
            elif status == 'canceled' or status == 'expired':
                raise Exception(f"Orden {order_id} fue {status} antes de llenarse")
        
        # Si llegamos aquí, la orden no se llenó a tiempo
        logger.warning(f"⚠️ Orden {order_id} aún no filled tras {max_checks} checks. Continuando...")
        return order

    # ==========================================================
    # EMERGENCY SHUTDOWN
    # ==========================================================

    async def emergency_shutdown(self):
        """
        BOTÓN NUCLEAR: Cancela todas las órdenes abiertas y cierra
        cualquier posición a mercado para TODOS los símbolos monitoreados.
        Se invoca cuando el Kill Switch del Risk Engine se activa.
        """
        logger.critical("🚨🚨🚨 EMERGENCY SHUTDOWN ACTIVADO 🚨🚨🚨")

        try:
            balance = await self._retry(self.exchange.fetch_balance)

            for sym in SYMBOLS:
                try:
                    # 1. Cancelar TODAS las órdenes abiertas del par
                    open_orders = await self._retry(
                        self.exchange.fetch_open_orders, sym
                    )
                    for order in open_orders:
                        try:
                            await self.exchange.cancel_order(order['id'], sym)
                            logger.warning(f"❌ Orden cancelada: {order['id']} ({sym})")
                        except Exception as e:
                            logger.error(f"Error cancelando orden {order['id']}: {e}")

                    # 2. Cerrar posiciones abiertas (vender todo el activo base)
                    symbol_base = sym.split('/')[0]
                    base_balance = balance.get(symbol_base, {}).get('free', 0)

                    if base_balance > 0:
                        amount = float(
                            self.exchange.amount_to_precision(sym, base_balance)
                        )
                        if amount > 0:
                            close_order = await self.exchange.create_order(
                                sym, 'market', 'sell', amount
                            )
                            logger.warning(
                                f"📉 Posición cerrada a mercado: {close_order['id']} "
                                f"| Vendido: {amount} {symbol_base} ({sym})"
                            )

                    # 3. Marcar posiciones locales como cerradas
                    local_open = await get_open_positions(sym)
                    for pos in local_open:
                        await close_position(pos['id'], pnl=None)

                except Exception as e:
                    logger.error(f"Error en emergency shutdown para {sym}: {e}")

            logger.critical("🏁 Emergency shutdown completado para todos los pares.")

        except Exception as e:
            logger.critical(f"💀 Error FATAL durante emergency shutdown: {e}")

    # ==========================================================
    # UTILIDADES
    # ==========================================================

    async def get_balance(self, symbol: str = None) -> dict:
        """Obtiene el balance actual del exchange para un símbolo dado."""
        balance = await self._retry(self.exchange.fetch_balance)
        sym = symbol or SYMBOL
        base = sym.split('/')[0]
        return {
            'USDT_free': balance.get('USDT', {}).get('free', 0),
            'USDT_total': balance.get('USDT', {}).get('total', 0),
            'base_free': balance.get(base, {}).get('free', 0),
            'base_total': balance.get(base, {}).get('total', 0),
            'base_symbol': base,
        }

    async def get_ticker(self) -> dict:
        """Obtiene el precio actual del par."""
        return await self._retry(self.exchange.fetch_ticker, SYMBOL)

    async def _retry(self, func, *args, **kwargs):
        """
        Wrapper de reintentos con backoff exponencial.
        
        Si una llamada a la API falla, reintenta con esperas
        crecientes: 1s, 2s, 4s, 8s, 16s antes de rendirse.
        """
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                result = await func(*args, **kwargs)
                if attempt > 0:
                    logger.info(
                        f"✅ Reintento exitoso (intento {attempt + 1}/{MAX_RETRIES})"
                    )
                return result
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable,
                    ccxt.RequestTimeout) as e:
                last_exception = e
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"⚠️ Error de red (intento {attempt + 1}/{MAX_RETRIES}): "
                    f"{type(e).__name__}: {e}. Reintentando en {delay}s..."
                )
                self.consecutive_errors += 1
                await asyncio.sleep(delay)
            except ccxt.ExchangeError as e:
                # Errores del exchange (fondos insuficientes, par inválido, etc.)
                logger.error(f"❌ Error del exchange: {e}")
                raise
            except Exception as e:
                logger.error(f"❌ Error inesperado: {type(e).__name__}: {e}")
                raise

        logger.critical(
            f"💀 Agotados {MAX_RETRIES} reintentos. Último error: {last_exception}"
        )
        raise last_exception

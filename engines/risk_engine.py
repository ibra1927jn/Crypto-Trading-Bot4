"""
Crypto-Trading-Bot4 — Risk Engine v2 (El Escudo)
=================================================
Protege el capital con:
  - Position Sizing porcentual (80% validado con datos REALES)
  - SL/TP basados en porcentaje (-4% / +8%)
  - Kill Switch global (drawdown diario + errores consecutivos)
  - Reset automático del kill switch al nuevo día
"""

import pandas as pd
from datetime import datetime, timezone
from config.settings import (
    POSITION_RISK_PCT, MAX_DAILY_DRAWDOWN, MAX_CONSECUTIVE_ERRORS,
    ADX_THRESHOLD
)
from db.database import get_daily_pnl, upsert_daily_pnl
from utils.logger import setup_logger

logger = setup_logger("RISK")


class RiskEngine:
    """
    Motor de riesgo: escudo dinámico del bot.
    
    Funciones:
      1. Kill Switch check (drawdown + errores)
      2. Calcular parámetros de trade (SL/TP/Size con ATR)
      3. Validar señales del Alpha Engine
    """

    def __init__(self):
        self.kill_switch_active = False
        self.kill_reason = ""
        self.starting_balance: float = 0.0
        self.current_balance: float = 0.0
        self.position_risk_pct = POSITION_RISK_PCT
        self._exchange = None  # Referencia al exchange para calcular equity

    # ==========================================================
    # INICIALIZACIÓN
    # ==========================================================

    async def initialize(self, balance: float, exchange=None):
        """Inicializa con el balance actual y carga PnL diario."""
        self._exchange = exchange
        self._current_day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        daily = await get_daily_pnl(self._current_day)

        if daily:
            self.starting_balance = daily['starting_balance']
            self.current_balance = balance
            logger.info(
                f"📊 PnL diario cargado: Inicio=${self.starting_balance:.2f} "
                f"| Actual=${balance:.2f}"
            )
        else:
            self.starting_balance = balance
            self.current_balance = balance
            await upsert_daily_pnl(self._current_day, balance, balance)
            logger.info(f"📊 Nuevo día de trading. Balance inicial: ${balance:.2f}")

        await self._check_drawdown()

    # ==========================================================
    # POSITION SIZING + SL/TP DINÁMICOS
    # ==========================================================

    def calculate_trade_parameters(self, balance: float,
                                    current_price: float,
                                    current_atr: float) -> dict:
        """
        Calcula el Sizing y los Hard SL/TP.
        
        v2: Porcentaje del capital (AllIn validated con datos REALES)
        SL/TP basados en porcentaje configurado en settings.
        
        Returns:
            dict con 'amount', 'sl_price', 'tp_price' o None si datos inválidos
        """
        from config.settings import SL_PCT, TP_PCT, TRAIL_PCT, ACTIVE_STRATEGY
        from config.settings import MOMBURST_SL_PCT, MOMBURST_TP_PCT

        if balance < 5 or current_price <= 0:
            logger.warning(f"⚠️ Balance ({balance}) o precio ({current_price}) insuficiente")
            return None

        # 1. SL/TP basados en porcentaje (del lab real)
        if ACTIVE_STRATEGY == 'MOMBURST':
            sl_pct = abs(MOMBURST_SL_PCT) / 100  # 2%
            tp_pct = abs(MOMBURST_TP_PCT) / 100  # 4%
        else:
            sl_pct = abs(SL_PCT) / 100  # 4%
            tp_pct = abs(TP_PCT) / 100  # 8%

        sl_price = current_price * (1 - sl_pct)
        tp_price = current_price * (1 + tp_pct)

        # 2. Position Sizing: % del balance (validado con datos reales)
        # POSITION_RISK_PCT = 0.80 → 80% del capital en cada trade
        capital_to_use = balance * self.position_risk_pct

        # Tamaño de la posición en unidades de la moneda
        amount = capital_to_use / current_price

        # 3. Límites de seguridad
        max_possible = (balance * 0.95) / current_price  # Max 95%
        final_amount = min(amount, max_possible)

        # Min notional check (Binance min ~$5 para altcoins)
        notional = final_amount * current_price
        if notional < 5:
            logger.warning(f"⚠️ Posición demasiado pequeña: ${notional:.2f} < $5 mínimo")
            return None

        logger.info(
            f"📐 Trade v2: Size={final_amount:.2f} | "
            f"SL=${sl_price:.6f} (-{sl_pct:.1%}) | "
            f"TP=${tp_price:.6f} (+{tp_pct:.1%}) | "
            f"Capital=${capital_to_use:.2f} ({self.position_risk_pct:.0%} de ${balance:.2f})"
        )

        return {
            'amount': final_amount,
            'sl_price': sl_price,
            'tp_price': tp_price,
        }

    # ==========================================================
    # VALIDACIÓN DE SEÑALES
    # ==========================================================

    async def validate_signal(self, signal: str, market_data: dict,
                              balance: float,
                              consecutive_errors: int) -> dict:
        """
        Evalúa si una señal del Alpha Engine debe ejecutarse.
        
        Checks:
          1. Kill Switch no activo
          2. Hay señal real
          3. No demasiados errores consecutivos
          4. Calcular sizing con ATR
        """
        result = {
            'approved': False,
            'reason': '',
            'position_size': 0.0,
            'sl_price': 0.0,
            'tp_price': 0.0,
        }

        # 1. KILL SWITCH
        self.current_balance = balance
        await self._check_drawdown()

        if await self._check_errors(consecutive_errors):
            result['reason'] = f"KILL SWITCH: {self.kill_reason}"
            logger.critical(f"🚨 {result['reason']}")
            return result

        if self.kill_switch_active:
            result['reason'] = f"KILL SWITCH activo: {self.kill_reason}"
            return result

        # 2. SEÑAL CHECK
        if signal == 'HOLD' or signal is None:
            result['reason'] = "Sin señal (HOLD)"
            return result

        # 3. Para SELL no necesitamos sizing (cerrar posición existente)
        if signal == 'SELL':
            result['approved'] = True
            result['reason'] = "✅ Señal SELL aprobada (cerrar posición)"
            return result

        # 4. Para BUY: calcular sizing con ATR
        atr = market_data.get('atr', 0)
        price = market_data.get('last_close', market_data.get('price', 0))

        trade_params = self.calculate_trade_parameters(balance, price, atr)
        if not trade_params:
            result['reason'] = "Parámetros de trade inválidos (ATR/balance)"
            return result

        result['approved'] = True
        result['position_size'] = trade_params['amount']
        result['sl_price'] = trade_params['sl_price']
        result['tp_price'] = trade_params['tp_price']
        result['reason'] = f"✅ Señal BUY aprobada"
        logger.info(result['reason'])

        return result

    # ==========================================================
    # KILL SWITCH
    # ==========================================================

    async def _check_drawdown(self):
        """
        Kill switch por drawdown diario.
        Se resetea automáticamente al empezar un nuevo día.
        Usa Total Equity (USDT + cripto*precio) en vez de solo USDT.
        """
        if self.starting_balance <= 0:
            return

        # FIX H1: Resetear kill switch al nuevo día
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if hasattr(self, '_current_day') and today != self._current_day:
            if self.kill_switch_active:
                logger.info(
                    f"🔄 Nuevo día ({today}): Reseteando Kill Switch. "
                    f"Ayer: {self._current_day}"
                )
            self.kill_switch_active = False
            self.kill_reason = ""
            self._current_day = today
            # Nuevo día = nuevo starting balance
            total_equity = await self._calculate_total_equity()
            self.starting_balance = total_equity
            await upsert_daily_pnl(today, total_equity, total_equity)
            logger.info(f"📊 Nuevo día. Balance inicial: ${total_equity:.2f}")
            return

        # Calcular equity total incluyendo posiciones en cripto
        total_equity = await self._calculate_total_equity()
        drawdown = (self.starting_balance - total_equity) / self.starting_balance

        await upsert_daily_pnl(today, self.starting_balance, total_equity)

        if drawdown >= MAX_DAILY_DRAWDOWN:
            self.kill_switch_active = True
            self.kill_reason = (
                f"Drawdown diario {drawdown:.1%} ≥ {MAX_DAILY_DRAWDOWN:.1%}. "
                f"Equity: ${total_equity:.2f} "
                f"(inicio: ${self.starting_balance:.2f})"
            )
            logger.critical(f"🚨 KILL SWITCH: {self.kill_reason}")

    async def _calculate_total_equity(self) -> float:
        """
        Total Equity = USDT total + (BTC total * precio spot actual).
        Si no tenemos exchange, usamos solo current_balance como fallback.
        """
        if not self._exchange:
            return self.current_balance

        try:
            from config.settings import SYMBOL
            balance = await self._exchange.fetch_balance()
            usdt_total = balance.get('USDT', {}).get('total', 0)
            symbol_base = SYMBOL.split('/')[0]
            btc_total = balance.get(symbol_base, {}).get('total', 0)

            if btc_total > 0:
                ticker = await self._exchange.fetch_ticker(SYMBOL)
                spot_price = ticker.get('last', 0)
                btc_value = btc_total * spot_price
            else:
                btc_value = 0

            total = usdt_total + btc_value
            logger.debug(
                f"💰 Equity: ${usdt_total:.2f} USDT + "
                f"{btc_total:.6f} BTC (${btc_value:.2f}) = ${total:.2f}"
            )
            return total
        except Exception as e:
            logger.debug(f"Error calculando equity: {e}")
            return self.current_balance

    async def _check_errors(self, consecutive_errors: int) -> bool:
        """Kill switch por errores API consecutivos."""
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self.kill_switch_active = True
            self.kill_reason = (
                f"{consecutive_errors} errores consecutivos de API "
                f"(max: {MAX_CONSECUTIVE_ERRORS})"
            )
            logger.critical(f"🚨 KILL SWITCH: {self.kill_reason}")
            return True
        return False

    async def update_balance(self, balance: float):
        """Actualiza balance y re-evalúa kill switch."""
        self.current_balance = balance
        await self._check_drawdown()

"""
Crypto-Trading-Bot4 — Risk Engine (El Escudo Dinámico)
======================================================
Protege el capital con:
  - Position Sizing milimétrico basado en ATR
  - Hard SL/TP dinámicos: 1.5x ATR (SL) / 3x ATR (TP) → R:R 1:2
  - Kill Switch global (drawdown diario + errores consecutivos)
  - Filtro ADX pre-validación

El SL estático de porcentaje ha muerto.
Usamos la volatilidad real (ATR) para poner el SL
donde el "ruido del mercado" no nos alcance.
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
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        daily = await get_daily_pnl(today)

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
            await upsert_daily_pnl(today, balance, balance)
            logger.info(f"📊 Nuevo día de trading. Balance inicial: ${balance:.2f}")

        await self._check_drawdown()

    # ==========================================================
    # POSITION SIZING + SL/TP DINÁMICOS
    # ==========================================================

    def calculate_trade_parameters(self, balance: float,
                                    current_price: float,
                                    current_atr: float) -> dict:
        """
        Calcula el Sizing y los Hard SL/TP basado en el ATR.
        
        SL: 1.5x ATR de distancia (oxígeno contra caza de stops)
        TP: 3.0x ATR de distancia (R:R asimétrico 1:2)
        Size: Capital at Risk / SL Distance (pérdida exacta del % configurado)
        
        Returns:
            dict con 'amount', 'sl_price', 'tp_price' o None si datos inválidos
        """
        if not current_atr or pd.isna(current_atr) or current_atr <= 0:
            logger.warning("⚠️ ATR inválido — no se puede calcular sizing")
            return None

        if balance < 10 or current_price <= 0:
            logger.warning(f"⚠️ Balance ({balance}) o precio ({current_price}) insuficiente")
            return None

        # 1. Distancias basadas en volatilidad real (ATR)
        sl_distance = current_atr * 1.5  # 1.5 ATRs de oxígeno
        tp_distance = current_atr * 3.0  # R:R asimétrico 1:2

        sl_price = current_price - sl_distance
        tp_price = current_price + tp_distance

        # 2. Position Sizing exacto (Kelly fraccional / Risk Parity)
        # Dinero a perder = Balance * Riesgo% (Ej: 1% de $10,000 = $100)
        capital_at_risk = balance * self.position_risk_pct

        # Tamaño = Dinero a arriesgar / Distancia del SL
        # Si el SL salta, perdemos EXACTAMENTE el % configurado
        amount = capital_at_risk / sl_distance

        # 3. Límite de seguridad: nunca comprar más de lo que tenemos
        max_possible = balance / current_price
        final_amount = min(amount, max_possible * 0.95)  # 5% libre para fees

        logger.info(
            f"📐 Trade Parameters: Size={final_amount:.6f} | "
            f"SL=${sl_price:.2f} (-{sl_distance:.2f}) | "
            f"TP=${tp_price:.2f} (+{tp_distance:.2f}) | "
            f"Riesgo=${capital_at_risk:.2f} ({self.position_risk_pct:.1%})"
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
        CORREGIDO: Usa Total Equity (USDT + BTC*precio) en vez de solo USDT.
        Comprar BTC no es perder dinero — es cambiar de moneda.
        """
        if self.starting_balance <= 0:
            return

        # Calcular equity total incluyendo posiciones en cripto
        total_equity = await self._calculate_total_equity()
        drawdown = (self.starting_balance - total_equity) / self.starting_balance

        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
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

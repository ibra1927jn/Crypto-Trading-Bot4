"""
Módulo de Estrategias de Trading
=================================
Implementa estrategias híbridas que se adaptan a las condiciones del mercado:

- ALTA VOLATILIDAD (Scalping): Usa indicadores técnicos para velocidad
- BAJA VOLATILIDAD (Swing): Consulta AI_Predictor antes de operar

Esta arquitectura modular permite añadir nuevas estrategias fácilmente.
"""

import logging
from enum import Enum
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class MarketCondition(Enum):
    """Condiciones del mercado"""

    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class Signal(Enum):
    """Señales de trading"""

    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


# Umbrales de confianza mínima por estrategia
SCALPING_MIN_CONFIDENCE = 0.55
SWING_MIN_CONFIDENCE = 0.65

# Pesos para señal combinada (swing)
AI_WEIGHT = 0.7
INDICATORS_WEIGHT = 0.3

# Umbral de señal combinada para decidir BUY/SELL
SIGNAL_THRESHOLD = 0.3

# Mapa de señal textual a valor numérico para combinación ponderada
SIGNAL_VALUES = {"BUY": 1, "NEUTRAL": 0, "SELL": -1}


class HybridStrategy:
    """
    Estrategia híbrida que combina:
    - Indicadores técnicos (para alta volatilidad/scalping)
    - Predicciones de IA (para baja volatilidad/swing)

    La estrategia se adapta automáticamente según las condiciones del mercado.
    """

    def __init__(
        self, data_manager, indicators,
        ai_predictor, config: dict[str, Any],
    ):
        """
        Inicializa la estrategia híbrida

        Args:
            data_manager: Instancia de DataManager
            indicators: Instancia de TechnicalIndicators
            ai_predictor: Instancia de AI_Predictor
            config: Configuración general
        """
        self.data_manager = data_manager
        self.indicators = indicators
        self.ai_predictor = ai_predictor
        self.config = config

        # Configuración de volatilidad
        self.volatility_threshold = config.get("VOLATILITY_THRESHOLD", 2.0)

        # Configuración de estrategias
        self.scalping_config = config.get("SCALPING_CONFIG", {})
        self.swing_config = config.get("SWING_CONFIG", {})

        # Estado actual
        self.current_condition = MarketCondition.UNKNOWN
        self.current_volatility = 0.0
        self.last_signal = Signal.NEUTRAL

        logger.info("🎯 HybridStrategy initialized")
        logger.info("   Volatility Threshold: %s", self.volatility_threshold)

    def analyze_market_condition(self) -> MarketCondition:
        """
        Analiza las condiciones actuales del mercado

        Returns:
            MarketCondition (HIGH_VOLATILITY o LOW_VOLATILITY)
        """
        try:
            # Calcular volatilidad actual
            volatility = self.data_manager.calculate_volatility()
            self.current_volatility = volatility

            if volatility > self.volatility_threshold:
                self.current_condition = MarketCondition.HIGH_VOLATILITY
                logger.info(
                    "📊 Market Condition: HIGH VOLATILITY (%.2f%%)",
                    volatility,
                )
            else:
                self.current_condition = MarketCondition.LOW_VOLATILITY
                logger.info(
                    "📊 Market Condition: LOW VOLATILITY (%.2f%%)",
                    volatility,
                )

            return self.current_condition

        except Exception:
            logger.exception("❌ Error analyzing market condition")
            return MarketCondition.UNKNOWN

    def get_signal(
        self, df: pd.DataFrame,
    ) -> tuple[Signal, float, dict[str, Any]]:
        """
        Genera señal de trading según la estrategia apropiada

        Args:
            df: DataFrame con datos e indicadores

        Returns:
            Tuple (signal, confidence, details) donde:
            - signal: BUY, SELL, o NEUTRAL
            - confidence: confianza de la señal (0-1)
            - details: diccionario con detalles adicionales
        """
        try:
            # Analizar condición del mercado
            condition = self.analyze_market_condition()

            details = {
                "market_condition": condition.value,
                "volatility": self.current_volatility,
                "strategy_used": None,
            }

            # Elegir estrategia según volatilidad
            if condition == MarketCondition.HIGH_VOLATILITY:
                signal, confidence, strategy_details = (
                    self._scalping_strategy(df)
                )
                details["strategy_used"] = "SCALPING"
                details.update(strategy_details)

            elif condition == MarketCondition.LOW_VOLATILITY:
                signal, confidence, strategy_details = (
                    self._swing_strategy(df)
                )
                details["strategy_used"] = "SWING"
                details.update(strategy_details)

            else:
                signal = Signal.NEUTRAL
                confidence = 0.0
                details["strategy_used"] = "NONE"

            self.last_signal = signal

            return signal, confidence, details

        except Exception as e:
            logger.exception("❌ Error getting signal")
            return Signal.NEUTRAL, 0.0, {"error": str(e)}

    def _scalping_strategy(
        self, df: pd.DataFrame
    ) -> tuple[Signal, float, dict[str, Any]]:
        """
        Estrategia de SCALPING para alta volatilidad

        Usa indicadores técnicos rápidos para aprovechar movimientos rápidos.
        No consulta IA para maximizar velocidad.

        Args:
            df: DataFrame con datos e indicadores

        Returns:
            Tuple (signal, confidence, details)
        """
        try:
            logger.debug("⚡ Using SCALPING strategy (High Volatility)")

            # Compute Bollinger once; reuse for combined signal + details
            bollinger_signal = self.indicators.get_bollinger_signal(df)

            # Obtener señales de indicadores
            combined_signal, confidence = (
                self.indicators.get_combined_signal(
                    df, bollinger_signal=bollinger_signal,
                )
            )

            # Convertir a enum Signal
            if combined_signal == "BUY":
                signal = Signal.BUY
            elif combined_signal == "SELL":
                signal = Signal.SELL
            else:
                signal = Signal.NEUTRAL

            # Detalles de la señal
            details = {
                "rsi": (
                    df["rsi"].iloc[-1]
                    if "rsi" in df.columns else None
                ),
                "macd_signal": (
                    self.indicators.get_macd_signal(df)
                ),
                "bollinger_signal": bollinger_signal,
                "price": (
                    df["close"].iloc[-1]
                    if "close" in df.columns else None
                ),
            }

            logger.info(
                "⚡ SCALPING Signal: %s (confidence: %.2f)",
                signal.value, confidence,
            )

            return signal, confidence, details

        except Exception as e:
            logger.exception("❌ Error in scalping strategy")
            return Signal.NEUTRAL, 0.0, {"error": str(e)}

    def _swing_strategy(
        self, df: pd.DataFrame,
    ) -> tuple[Signal, float, dict[str, Any]]:
        """
        Estrategia de SWING para baja volatilidad

        Combina indicadores técnicos con predicciones de IA.
        Consulta al AI_Predictor antes de tomar decisiones.

        Args:
            df: DataFrame con datos e indicadores

        Returns:
            Tuple (signal, confidence, details)
        """
        try:
            logger.debug("🎯 Using SWING strategy (Low Volatility)")

            # Obtener señal de indicadores técnicos
            indicators_signal, indicators_confidence = (
                self.indicators.get_combined_signal(df)
            )

            # Obtener predicción de IA (single inference; reuse for signal)
            ai_prediction, ai_confidence = self.ai_predictor.predict(df)
            ai_threshold = self.swing_config.get(
                "ai_confidence_threshold",
                SWING_MIN_CONFIDENCE,
            )
            ai_signal = self.ai_predictor.signal_from_prediction(
                ai_prediction, ai_confidence, ai_threshold,
            )

            # Combinar ambas señales
            # La IA tiene mayor peso en condiciones de baja volatilidad
            ai_weight = AI_WEIGHT
            indicators_weight = INDICATORS_WEIGHT

            # Convertir señales a valores numéricos
            indicators_value = SIGNAL_VALUES.get(indicators_signal, 0)
            ai_value = SIGNAL_VALUES.get(ai_signal, 0)

            # Calcular señal combinada
            combined_value = (
                ai_value * ai_weight * ai_confidence +
                indicators_value *
                indicators_weight *
                indicators_confidence
            )

            # Calcular confianza combinada
            combined_confidence = (
                ai_confidence * ai_weight +
                indicators_confidence * indicators_weight
            )

            # Determinar señal final
            if combined_value > SIGNAL_THRESHOLD:
                signal = Signal.BUY
            elif combined_value < -SIGNAL_THRESHOLD:
                signal = Signal.SELL
            else:
                signal = Signal.NEUTRAL

            # Detalles de la señal
            details = {
                "indicators_signal": indicators_signal,
                "indicators_confidence": indicators_confidence,
                "ai_signal": ai_signal,
                "ai_prediction": ai_prediction,
                "ai_confidence": ai_confidence,
                "combined_value": combined_value,
                "price": (
                    df["close"].iloc[-1]
                    if "close" in df.columns else None
                ),
                "rsi": (
                    df["rsi"].iloc[-1]
                    if "rsi" in df.columns else None
                ),
            }

            logger.info(
                "🎯 SWING Signal: %s (confidence: %.2f)",
                signal.value, combined_confidence,
            )
            logger.info(
                "   Indicators: %s (%.2f)",
                indicators_signal, indicators_confidence,
            )
            logger.info(
                "   AI: %s (pred: %.2f, conf: %.2f)",
                ai_signal, ai_prediction, ai_confidence,
            )

            return signal, combined_confidence, details

        except Exception as e:
            logger.exception("❌ Error in swing strategy")
            return Signal.NEUTRAL, 0.0, {"error": str(e)}

    def should_open_position(
        self,
        signal: Signal,
        confidence: float,
        current_positions: int,
        max_positions: int,
    ) -> bool:
        """
        Determina si se debe abrir una nueva posición

        Args:
            signal: Señal generada
            confidence: Confianza de la señal
            current_positions: Número de posiciones abiertas
            max_positions: Máximo de posiciones permitidas

        Returns:
            True si se debe abrir posición, False en caso contrario
        """
        try:
            # No abrir si la señal es neutral
            if signal == Signal.NEUTRAL:
                return False

            # No abrir si ya se alcanzó el máximo de posiciones
            if current_positions >= max_positions:
                logger.warning(
                    "⚠️  Max positions reached (%s/%s)",
                    current_positions, max_positions,
                )
                return False

            # Umbral mínimo de confianza según la estrategia
            if self.current_condition == MarketCondition.HIGH_VOLATILITY:
                # Scalping: umbral más bajo pero respuestas rápidas
                min_confidence = SCALPING_MIN_CONFIDENCE
            else:
                # Swing: umbral más alto para mayor seguridad
                min_confidence = SWING_MIN_CONFIDENCE

            if confidence < min_confidence:
                logger.debug(
                    "⚠️  Confidence too low (%.2f < %s)",
                    confidence, min_confidence,
                )
                return False

            logger.info(
                "✅ Should open %s position (confidence: %.2f)",
                signal.value, confidence,
            )
            return True

        except Exception:
            logger.exception("❌ Error determining position")
            return False

    def calculate_position_size(
        self, balance: float, position_size_percent: float, price: float
    ) -> float:
        """
        Calcula el tamaño de la posición

        Args:
            balance: Balance disponible
            position_size_percent: Porcentaje del balance a usar (0-1)
            price: Precio actual del activo

        Returns:
            Cantidad de activo a comprar/vender
        """
        try:
            if price <= 0:
                logger.warning(
                    "⚠️ Invalid price %.8f, "
                    "cannot calculate position size",
                    price,
                )
                return 0.0

            # Calcular monto en USDT
            amount_usdt = balance * position_size_percent

            # Calcular cantidad de activo
            quantity = amount_usdt / price

            logger.debug(
                "💰 Position size: %.8f ($%.2f @ $%.2f)",
                quantity, amount_usdt, price,
            )

            return quantity

        except Exception:
            logger.exception("❌ Error calculating position size")
            return 0.0

    def calculate_stop_loss_take_profit(
        self,
        entry_price: float,
        signal: Signal,
        stop_loss_percent: float,
        take_profit_percent: float,
    ) -> tuple[float, float]:
        """
        Calcula niveles de Stop Loss y Take Profit

        Args:
            entry_price: Precio de entrada
            signal: BUY o SELL
            stop_loss_percent: Porcentaje de stop loss
            take_profit_percent: Porcentaje de take profit

        Returns:
            Tuple (stop_loss, take_profit)
        """
        try:
            if signal == Signal.BUY:
                # Para posición larga
                stop_loss = entry_price * (
                    1 - stop_loss_percent / 100
                )
                take_profit = entry_price * (
                    1 + take_profit_percent / 100
                )
            elif signal == Signal.SELL:
                # Para posición corta
                stop_loss = entry_price * (
                    1 + stop_loss_percent / 100
                )
                take_profit = entry_price * (
                    1 - take_profit_percent / 100
                )
            else:
                stop_loss = entry_price
                take_profit = entry_price

            logger.debug("🎯 Entry: $%.2f", entry_price)
            logger.debug(
                "   SL: $%.2f (-%s%%)",
                stop_loss, stop_loss_percent,
            )
            logger.debug(
                "   TP: $%.2f (+%s%%)",
                take_profit, take_profit_percent,
            )

            return stop_loss, take_profit

        except Exception:
            logger.exception("❌ Error calculating SL/TP")
            return entry_price, entry_price

    def get_check_interval(self) -> int:
        """
        Retorna el intervalo de chequeo según la estrategia actual

        Returns:
            Intervalo en segundos
        """
        if self.current_condition == MarketCondition.HIGH_VOLATILITY:
            # Scalping: chequear más frecuentemente
            return self.scalping_config.get("check_interval", 5)
        # Swing: chequear menos frecuentemente
        return self.swing_config.get("check_interval", 60)

    def get_strategy_summary(self) -> dict[str, Any]:
        """
        Retorna un resumen del estado actual de la estrategia

        Returns:
            Diccionario con información de la estrategia
        """
        return {
            "current_condition": self.current_condition.value,
            "volatility_threshold": self.volatility_threshold,
            "current_volatility": self.data_manager.calculate_volatility(),
            "last_signal": self.last_signal.value,
            "check_interval": self.get_check_interval(),
            "strategy_active": "SCALPING"
            if self.current_condition == MarketCondition.HIGH_VOLATILITY
            else "SWING",
            "ai_enabled": (
                self.current_condition ==
                MarketCondition.LOW_VOLATILITY
            ),
        }

"""
Módulo de Estrategias de Trading
=================================
Implementa estrategias híbridas que se adaptan a las condiciones del mercado:

- ALTA VOLATILIDAD (Scalping): Usa indicadores técnicos para velocidad
- BAJA VOLATILIDAD (Swing): Consulta AI_Predictor antes de operar

Esta arquitectura modular permite añadir nuevas estrategias fácilmente.
"""

import pandas as pd
from typing import Dict, Any, Optional, Tuple
import logging
from enum import Enum

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


class HybridStrategy:
    """
    Estrategia híbrida que combina:
    - Indicadores técnicos (para alta volatilidad/scalping)
    - Predicciones de IA (para baja volatilidad/swing)

    La estrategia se adapta automáticamente según las condiciones del mercado.
    """

    def __init__(
        self,
        data_manager,
        indicators,
        ai_predictor,
        config: Dict[str, Any]
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
        self.volatility_threshold = config.get('VOLATILITY_THRESHOLD', 2.0)

        # Configuración de estrategias
        self.scalping_config = config.get('SCALPING_CONFIG', {})
        self.swing_config = config.get('SWING_CONFIG', {})

        # Estado actual
        self.current_condition = MarketCondition.UNKNOWN
        self.last_signal = Signal.NEUTRAL

        logger.info("🎯 HybridStrategy initialized")
        logger.info(f"   Volatility Threshold: {self.volatility_threshold}")

    def analyze_market_condition(self) -> MarketCondition:
        """
        Analiza las condiciones actuales del mercado

        Returns:
            MarketCondition (HIGH_VOLATILITY o LOW_VOLATILITY)
        """
        try:
            # Calcular volatilidad actual
            volatility = self.data_manager.calculate_volatility()

            if volatility > self.volatility_threshold:
                self.current_condition = MarketCondition.HIGH_VOLATILITY
                logger.info(f"📊 Market Condition: HIGH VOLATILITY ({volatility:.2f}%)")
            else:
                self.current_condition = MarketCondition.LOW_VOLATILITY
                logger.info(f"📊 Market Condition: LOW VOLATILITY ({volatility:.2f}%)")

            return self.current_condition

        except Exception as e:
            logger.error(f"❌ Error analyzing market condition: {e}")
            return MarketCondition.UNKNOWN

    def get_signal(self, df: pd.DataFrame) -> Tuple[Signal, float, Dict[str, Any]]:
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
                'market_condition': condition.value,
                'volatility': self.data_manager.calculate_volatility(),
                'strategy_used': None
            }

            # Elegir estrategia según volatilidad
            if condition == MarketCondition.HIGH_VOLATILITY:
                signal, confidence, strategy_details = self._scalping_strategy(df)
                details['strategy_used'] = 'SCALPING'
                details.update(strategy_details)

            elif condition == MarketCondition.LOW_VOLATILITY:
                signal, confidence, strategy_details = self._swing_strategy(df)
                details['strategy_used'] = 'SWING'
                details.update(strategy_details)

            else:
                signal = Signal.NEUTRAL
                confidence = 0.0
                details['strategy_used'] = 'NONE'

            self.last_signal = signal

            return signal, confidence, details

        except Exception as e:
            logger.error(f"❌ Error getting signal: {e}")
            return Signal.NEUTRAL, 0.0, {'error': str(e)}

    def _scalping_strategy(self, df: pd.DataFrame) -> Tuple[Signal, float, Dict[str, Any]]:
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

            # Obtener señales de indicadores
            combined_signal, confidence = self.indicators.get_combined_signal(df)

            # Convertir a enum Signal
            if combined_signal == 'BUY':
                signal = Signal.BUY
            elif combined_signal == 'SELL':
                signal = Signal.SELL
            else:
                signal = Signal.NEUTRAL

            # Detalles de la señal
            details = {
                'rsi': df['rsi'].iloc[-1] if 'rsi' in df.columns else None,
                'macd_signal': self.indicators.get_macd_signal(df),
                'bollinger_signal': self.indicators.get_bollinger_signal(df),
                'price': df['close'].iloc[-1] if 'close' in df.columns else None
            }

            logger.info(f"⚡ SCALPING Signal: {signal.value} (confidence: {confidence:.2f})")

            return signal, confidence, details

        except Exception as e:
            logger.error(f"❌ Error in scalping strategy: {e}")
            return Signal.NEUTRAL, 0.0, {'error': str(e)}

    def _swing_strategy(self, df: pd.DataFrame) -> Tuple[Signal, float, Dict[str, Any]]:
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
            indicators_signal, indicators_confidence = self.indicators.get_combined_signal(df)

            # Obtener predicción de IA
            ai_prediction, ai_confidence = self.ai_predictor.predict(df)
            ai_signal = self.ai_predictor.get_signal(
                df,
                threshold=self.swing_config.get('ai_confidence_threshold', 0.65)
            )

            # Combinar ambas señales
            # La IA tiene mayor peso en condiciones de baja volatilidad
            ai_weight = 0.7
            indicators_weight = 0.3

            # Convertir señales a valores numéricos
            signal_values = {'BUY': 1, 'NEUTRAL': 0, 'SELL': -1}

            indicators_value = signal_values.get(indicators_signal, 0)
            ai_value = signal_values.get(ai_signal, 0)

            # Calcular señal combinada
            combined_value = (ai_value * ai_weight * ai_confidence +
                            indicators_value * indicators_weight * indicators_confidence)

            # Calcular confianza combinada
            combined_confidence = (ai_confidence * ai_weight +
                                 indicators_confidence * indicators_weight)

            # Determinar señal final
            if combined_value > 0.3:
                signal = Signal.BUY
            elif combined_value < -0.3:
                signal = Signal.SELL
            else:
                signal = Signal.NEUTRAL

            # Detalles de la señal
            details = {
                'indicators_signal': indicators_signal,
                'indicators_confidence': indicators_confidence,
                'ai_signal': ai_signal,
                'ai_prediction': ai_prediction,
                'ai_confidence': ai_confidence,
                'combined_value': combined_value,
                'price': df['close'].iloc[-1] if 'close' in df.columns else None,
                'rsi': df['rsi'].iloc[-1] if 'rsi' in df.columns else None
            }

            logger.info(f"🎯 SWING Signal: {signal.value} (confidence: {combined_confidence:.2f})")
            logger.info(f"   Indicators: {indicators_signal} ({indicators_confidence:.2f})")
            logger.info(f"   AI: {ai_signal} (pred: {ai_prediction:.2f}, conf: {ai_confidence:.2f})")

            return signal, combined_confidence, details

        except Exception as e:
            logger.error(f"❌ Error in swing strategy: {e}")
            return Signal.NEUTRAL, 0.0, {'error': str(e)}

    def should_open_position(
        self,
        signal: Signal,
        confidence: float,
        current_positions: int,
        max_positions: int
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
                logger.warning(f"⚠️  Max positions reached ({current_positions}/{max_positions})")
                return False

            # Umbral mínimo de confianza según la estrategia
            if self.current_condition == MarketCondition.HIGH_VOLATILITY:
                # Scalping: umbral más bajo pero respuestas rápidas
                min_confidence = 0.55
            else:
                # Swing: umbral más alto para mayor seguridad
                min_confidence = 0.65

            if confidence < min_confidence:
                logger.debug(f"⚠️  Confidence too low ({confidence:.2f} < {min_confidence})")
                return False

            logger.info(f"✅ Should open {signal.value} position (confidence: {confidence:.2f})")
            return True

        except Exception as e:
            logger.error(f"❌ Error determining if should open position: {e}")
            return False

    def calculate_position_size(
        self,
        balance: float,
        position_size_percent: float,
        price: float
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
            # Calcular monto en USDT
            amount_usdt = balance * position_size_percent

            # Calcular cantidad de activo
            quantity = amount_usdt / price

            logger.debug(f"💰 Position size: {quantity:.8f} (${amount_usdt:.2f} @ ${price:.2f})")

            return quantity

        except Exception as e:
            logger.error(f"❌ Error calculating position size: {e}")
            return 0.0

    def calculate_stop_loss_take_profit(
        self,
        entry_price: float,
        signal: Signal,
        stop_loss_percent: float,
        take_profit_percent: float
    ) -> Tuple[float, float]:
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
                stop_loss = entry_price * (1 - stop_loss_percent / 100)
                take_profit = entry_price * (1 + take_profit_percent / 100)
            elif signal == Signal.SELL:
                # Para posición corta
                stop_loss = entry_price * (1 + stop_loss_percent / 100)
                take_profit = entry_price * (1 - take_profit_percent / 100)
            else:
                stop_loss = entry_price
                take_profit = entry_price

            logger.debug(f"🎯 Entry: ${entry_price:.2f}")
            logger.debug(f"   SL: ${stop_loss:.2f} (-{stop_loss_percent}%)")
            logger.debug(f"   TP: ${take_profit:.2f} (+{take_profit_percent}%)")

            return stop_loss, take_profit

        except Exception as e:
            logger.error(f"❌ Error calculating SL/TP: {e}")
            return entry_price, entry_price

    def get_check_interval(self) -> int:
        """
        Retorna el intervalo de chequeo según la estrategia actual

        Returns:
            Intervalo en segundos
        """
        if self.current_condition == MarketCondition.HIGH_VOLATILITY:
            # Scalping: chequear más frecuentemente
            return self.scalping_config.get('check_interval', 5)
        else:
            # Swing: chequear menos frecuentemente
            return self.swing_config.get('check_interval', 60)

    def get_strategy_summary(self) -> Dict[str, Any]:
        """
        Retorna un resumen del estado actual de la estrategia

        Returns:
            Diccionario con información de la estrategia
        """
        return {
            'current_condition': self.current_condition.value,
            'volatility_threshold': self.volatility_threshold,
            'current_volatility': self.data_manager.calculate_volatility(),
            'last_signal': self.last_signal.value,
            'check_interval': self.get_check_interval(),
            'strategy_active': 'SCALPING' if self.current_condition == MarketCondition.HIGH_VOLATILITY else 'SWING',
            'ai_enabled': self.current_condition == MarketCondition.LOW_VOLATILITY
        }

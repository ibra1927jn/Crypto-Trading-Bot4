"""
Módulo de Indicadores Técnicos
===============================
Este módulo calcula indicadores técnicos usando pandas-ta:
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- Bandas de Bollinger
- Y otros indicadores útiles para trading
"""

import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Dict, Any, Optional, Tuple
from colorlog import getLogger

logger = getLogger(__name__)


class TechnicalIndicators:
    """
    Clase para calcular y gestionar indicadores técnicos
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa el calculador de indicadores

        Args:
            config: Diccionario con configuración de indicadores
        """
        self.config = config
        logger.info("📊 TechnicalIndicators initialized")

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula todos los indicadores técnicos en un DataFrame

        Args:
            df: DataFrame con datos OHLCV

        Returns:
            DataFrame con indicadores añadidos
        """
        if df is None or len(df) == 0:
            logger.warning("⚠️  Empty DataFrame provided")
            return df

        try:
            # Hacer una copia para no modificar el original
            df_result = df.copy()

            # Calcular RSI
            df_result = self.add_rsi(df_result)

            # Calcular MACD
            df_result = self.add_macd(df_result)

            # Calcular Bandas de Bollinger
            df_result = self.add_bollinger_bands(df_result)

            # Calcular indicadores adicionales útiles
            df_result = self.add_ema(df_result)
            df_result = self.add_atr(df_result)

            logger.debug(f"✅ All indicators calculated - DataFrame shape: {df_result.shape}")

            return df_result

        except Exception as e:
            logger.error(f"❌ Error calculating indicators: {e}")
            return df

    def add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Añade el indicador RSI (Relative Strength Index)

        Args:
            df: DataFrame con datos OHLCV

        Returns:
            DataFrame con columna 'rsi' añadida
        """
        try:
            period = self.config['RSI']['period']

            # Calcular RSI usando pandas-ta
            df['rsi'] = ta.rsi(df['close'], length=period)

            logger.debug(f"✅ RSI calculated (period={period})")

            return df

        except Exception as e:
            logger.error(f"❌ Error calculating RSI: {e}")
            return df

    def add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Añade el indicador MACD (Moving Average Convergence Divergence)

        Args:
            df: DataFrame con datos OHLCV

        Returns:
            DataFrame con columnas 'macd', 'macd_signal', 'macd_histogram' añadidas
        """
        try:
            fast = self.config['MACD']['fast_period']
            slow = self.config['MACD']['slow_period']
            signal = self.config['MACD']['signal_period']

            # Calcular MACD usando pandas-ta
            macd_df = ta.macd(df['close'], fast=fast, slow=slow, signal=signal)

            if macd_df is not None:
                df['macd'] = macd_df[f'MACD_{fast}_{slow}_{signal}']
                df['macd_signal'] = macd_df[f'MACDs_{fast}_{slow}_{signal}']
                df['macd_histogram'] = macd_df[f'MACDh_{fast}_{slow}_{signal}']

            logger.debug(f"✅ MACD calculated (fast={fast}, slow={slow}, signal={signal})")

            return df

        except Exception as e:
            logger.error(f"❌ Error calculating MACD: {e}")
            return df

    def add_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Añade las Bandas de Bollinger

        Args:
            df: DataFrame con datos OHLCV

        Returns:
            DataFrame con columnas 'bb_upper', 'bb_middle', 'bb_lower' añadidas
        """
        try:
            period = self.config['BOLLINGER']['period']
            std_dev = self.config['BOLLINGER']['std_dev']

            # Calcular Bandas de Bollinger usando pandas-ta
            bbands = ta.bbands(df['close'], length=period, std=std_dev)

            if bbands is not None:
                df['bb_lower'] = bbands[f'BBL_{period}_{std_dev}.0']
                df['bb_middle'] = bbands[f'BBM_{period}_{std_dev}.0']
                df['bb_upper'] = bbands[f'BBU_{period}_{std_dev}.0']
                df['bb_bandwidth'] = bbands[f'BBB_{period}_{std_dev}.0']
                df['bb_percent'] = bbands[f'BBP_{period}_{std_dev}.0']

            logger.debug(f"✅ Bollinger Bands calculated (period={period}, std={std_dev})")

            return df

        except Exception as e:
            logger.error(f"❌ Error calculating Bollinger Bands: {e}")
            return df

    def add_ema(self, df: pd.DataFrame, periods: list = [9, 21, 50, 200]) -> pd.DataFrame:
        """
        Añade Medias Móviles Exponenciales (EMA)

        Args:
            df: DataFrame con datos OHLCV
            periods: Lista de períodos para calcular EMAs

        Returns:
            DataFrame con columnas 'ema_X' añadidas
        """
        try:
            for period in periods:
                df[f'ema_{period}'] = ta.ema(df['close'], length=period)

            logger.debug(f"✅ EMAs calculated for periods: {periods}")

            return df

        except Exception as e:
            logger.error(f"❌ Error calculating EMAs: {e}")
            return df

    def add_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Añade el ATR (Average True Range) para medir volatilidad

        Args:
            df: DataFrame con datos OHLCV
            period: Período para calcular ATR

        Returns:
            DataFrame con columna 'atr' añadida
        """
        try:
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=period)

            logger.debug(f"✅ ATR calculated (period={period})")

            return df

        except Exception as e:
            logger.error(f"❌ Error calculating ATR: {e}")
            return df

    def get_rsi_signal(self, df: pd.DataFrame) -> str:
        """
        Genera señal de trading basada en RSI

        Args:
            df: DataFrame con indicador RSI calculado

        Returns:
            'BUY', 'SELL', o 'NEUTRAL'
        """
        if 'rsi' not in df.columns or len(df) == 0:
            return 'NEUTRAL'

        try:
            current_rsi = df['rsi'].iloc[-1]

            if pd.isna(current_rsi):
                return 'NEUTRAL'

            oversold = self.config['RSI']['oversold']
            overbought = self.config['RSI']['overbought']

            if current_rsi < oversold:
                return 'BUY'
            elif current_rsi > overbought:
                return 'SELL'
            else:
                return 'NEUTRAL'

        except Exception as e:
            logger.error(f"❌ Error getting RSI signal: {e}")
            return 'NEUTRAL'

    def get_macd_signal(self, df: pd.DataFrame) -> str:
        """
        Genera señal de trading basada en MACD

        Args:
            df: DataFrame con indicador MACD calculado

        Returns:
            'BUY', 'SELL', o 'NEUTRAL'
        """
        if 'macd' not in df.columns or 'macd_signal' not in df.columns or len(df) < 2:
            return 'NEUTRAL'

        try:
            current_macd = df['macd'].iloc[-1]
            current_signal = df['macd_signal'].iloc[-1]
            prev_macd = df['macd'].iloc[-2]
            prev_signal = df['macd_signal'].iloc[-2]

            if pd.isna(current_macd) or pd.isna(current_signal):
                return 'NEUTRAL'

            # Cruce alcista (MACD cruza por encima de la señal)
            if prev_macd <= prev_signal and current_macd > current_signal:
                return 'BUY'

            # Cruce bajista (MACD cruza por debajo de la señal)
            elif prev_macd >= prev_signal and current_macd < current_signal:
                return 'SELL'

            else:
                return 'NEUTRAL'

        except Exception as e:
            logger.error(f"❌ Error getting MACD signal: {e}")
            return 'NEUTRAL'

    def get_bollinger_signal(self, df: pd.DataFrame) -> str:
        """
        Genera señal de trading basada en Bandas de Bollinger

        Args:
            df: DataFrame con Bandas de Bollinger calculadas

        Returns:
            'BUY', 'SELL', o 'NEUTRAL'
        """
        if 'bb_lower' not in df.columns or 'bb_upper' not in df.columns or len(df) == 0:
            return 'NEUTRAL'

        try:
            current_price = df['close'].iloc[-1]
            bb_lower = df['bb_lower'].iloc[-1]
            bb_upper = df['bb_upper'].iloc[-1]

            if pd.isna(bb_lower) or pd.isna(bb_upper):
                return 'NEUTRAL'

            # Precio toca banda inferior (sobreventa)
            if current_price <= bb_lower:
                return 'BUY'

            # Precio toca banda superior (sobrecompra)
            elif current_price >= bb_upper:
                return 'SELL'

            else:
                return 'NEUTRAL'

        except Exception as e:
            logger.error(f"❌ Error getting Bollinger signal: {e}")
            return 'NEUTRAL'

    def get_combined_signal(self, df: pd.DataFrame) -> Tuple[str, float]:
        """
        Combina múltiples señales para generar una señal final

        Args:
            df: DataFrame con todos los indicadores calculados

        Returns:
            Tuple (señal, confianza) donde señal es 'BUY', 'SELL', 'NEUTRAL'
            y confianza es un valor entre 0 y 1
        """
        try:
            signals = {
                'rsi': self.get_rsi_signal(df),
                'macd': self.get_macd_signal(df),
                'bollinger': self.get_bollinger_signal(df)
            }

            # Contar votos
            buy_votes = sum(1 for signal in signals.values() if signal == 'BUY')
            sell_votes = sum(1 for signal in signals.values() if signal == 'SELL')
            total_signals = len(signals)

            # Determinar señal final
            if buy_votes > sell_votes and buy_votes >= 2:
                confidence = buy_votes / total_signals
                return 'BUY', confidence

            elif sell_votes > buy_votes and sell_votes >= 2:
                confidence = sell_votes / total_signals
                return 'SELL', confidence

            else:
                return 'NEUTRAL', 0.0

        except Exception as e:
            logger.error(f"❌ Error getting combined signal: {e}")
            return 'NEUTRAL', 0.0

    def get_indicators_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Genera un resumen de los indicadores actuales

        Args:
            df: DataFrame con indicadores calculados

        Returns:
            Diccionario con valores de indicadores
        """
        if df is None or len(df) == 0:
            return {}

        try:
            summary = {}

            # RSI
            if 'rsi' in df.columns:
                summary['rsi'] = float(df['rsi'].iloc[-1]) if not pd.isna(df['rsi'].iloc[-1]) else None

            # MACD
            if 'macd' in df.columns:
                summary['macd'] = float(df['macd'].iloc[-1]) if not pd.isna(df['macd'].iloc[-1]) else None
                summary['macd_signal'] = float(df['macd_signal'].iloc[-1]) if not pd.isna(df['macd_signal'].iloc[-1]) else None
                summary['macd_histogram'] = float(df['macd_histogram'].iloc[-1]) if not pd.isna(df['macd_histogram'].iloc[-1]) else None

            # Bollinger Bands
            if 'bb_upper' in df.columns:
                summary['bb_upper'] = float(df['bb_upper'].iloc[-1]) if not pd.isna(df['bb_upper'].iloc[-1]) else None
                summary['bb_middle'] = float(df['bb_middle'].iloc[-1]) if not pd.isna(df['bb_middle'].iloc[-1]) else None
                summary['bb_lower'] = float(df['bb_lower'].iloc[-1]) if not pd.isna(df['bb_lower'].iloc[-1]) else None

            # Señales
            summary['rsi_signal'] = self.get_rsi_signal(df)
            summary['macd_signal'] = self.get_macd_signal(df)
            summary['bollinger_signal'] = self.get_bollinger_signal(df)

            # Señal combinada
            combined_signal, confidence = self.get_combined_signal(df)
            summary['combined_signal'] = combined_signal
            summary['signal_confidence'] = confidence

            return summary

        except Exception as e:
            logger.error(f"❌ Error getting indicators summary: {e}")
            return {}

"""
Crypto-Trading-Bot4 — Alpha Engine (El Francotirador)
=====================================================
Estrategia: Trend-Momentum Híbrido Institucional.

Solo dispara si las 4 leyes fundamentales se cumplen
en el MISMO instante:
  1. LA MAREA:    Precio > EMA 200 (tendencia macro alcista)
  2. LA FUERZA:   ADX > 25 (hay tendencia, no rango lateral)
  3. LAS BALLENAS: Volumen > SMA 20 (dinero institucional)
  4. EL GATILLO:  EMA 9 cruza EMA 21 hacia arriba (crossover dorado)

Regla Anti-Repainting: SIEMPRE evalúa sobre velas CERRADAS
(iloc[-2]), nunca sobre la vela viva (iloc[-1]).
"""

import pandas as pd
from utils.logger import setup_logger

logger = setup_logger("ALPHA")


class AlphaEngine:
    """
    Motor de señales: cerebro cuantitativo del bot.
    
    Señales:
      - 'BUY':  Las 4 leyes confluyen → disparar
      - 'SELL': Señal de salida (cruce bajista)
      - 'HOLD': No se cumplen todas → francotirador en espera
    """

    def __init__(self):
        self.evaluations = 0
        self.signals_emitted = 0

    def get_signal(self, df: pd.DataFrame, has_open_position: bool) -> str:
        """
        Evalúa el mercado y emite una señal.
        
        REGLA ANTI-REPAINTING: Evaluamos sobre la vela CERRADA (iloc[-2]).
        La vela [-1] aún se está moviendo y puede dar señales falsas.
        
        Args:
            df: DataFrame con datos OHLCV + indicadores calculados
            has_open_position: True si hay posición abierta
        
        Returns:
            'BUY', 'SELL', o 'HOLD'
        """
        # Validación básica
        if df is None or len(df) < 200 or 'EMA_200' not in df.columns:
            return 'HOLD'

        self.evaluations += 1

        # Velas cerradas (anti-repainting)
        closed = df.iloc[-2]   # Última vela cerrada
        prev = df.iloc[-3]     # Vela anterior a la cerrada

        # Verificar que los indicadores estén calculados (no NaN)
        if pd.isna(closed.get('EMA_200')) or pd.isna(closed.get('ADX_14')):
            return 'HOLD'

        # ==================================================
        # SEÑAL DE SALIDA (si tenemos posición abierta)
        # ==================================================
        if has_open_position:
            return self._check_exit(closed, prev)

        # ==================================================
        # SEÑAL DE ENTRADA (Las 4 Leyes del Francotirador)
        # ==================================================

        # REGLA 1: LA MAREA (Prohibido comprar bajo la EMA 200)
        macro_bullish = closed['close'] > closed['EMA_200']

        # REGLA 2: LA FUERZA (ADX > 20 → bajado de 25 para capturar inicio de tendencia)
        adx_val = closed.get('ADX_14', 0)
        if pd.isna(adx_val):
            adx_val = 0
        strong_trend = adx_val > 20

        # REGLA 3: LAS BALLENAS (Volumen > media de 20 periodos)
        high_volume = closed['volume'] > closed.get('VOL_SMA_20', 0)

        # REGLA 4: EL GATILLO — RSI PULLBACK (Comprar la Sangre)
        # Esperamos que el RSI caiga a sobreventa (<35) y luego rebote
        # Entramos CERCA DEL SUELO del retroceso, no en el techo
        rsi_prev = prev.get('RSI_14', 50)
        rsi_now = closed.get('RSI_14', 50)
        if pd.isna(rsi_prev):
            rsi_prev = 50
        if pd.isna(rsi_now):
            rsi_now = 50
        rsi_oversold = rsi_prev < 35
        rsi_bouncing = rsi_now > rsi_prev
        rsi_pullback = rsi_oversold and rsi_bouncing

        # Log de status de las leyes (cada 10 evaluaciones)
        if self.evaluations % 10 == 0:
            logger.info(
                f"📊 Eval #{self.evaluations} | "
                f"Marea={'✅' if macro_bullish else '❌'} | "
                f"Fuerza={'✅' if strong_trend else '❌'}(ADX={adx_val:.1f}) | "
                f"Ballenas={'✅' if high_volume else '❌'} | "
                f"Pullback={'✅' if rsi_pullback else '❌'}(RSI={rsi_now:.1f})"
            )

        # EL DISPARO LETAL: Solo si las 4 leyes confluyen
        if macro_bullish and strong_trend and high_volume and rsi_pullback:
            self.signals_emitted += 1
            logger.info(
                f"🎯 SANTO GRIAL #{self.signals_emitted}: BUY (Pullback) | "
                f"Precio: ${closed['close']:.2f} | "
                f"RSI: {rsi_now:.1f} (prev: {rsi_prev:.1f}) | "
                f"ADX: {adx_val:.1f}"
            )
            return 'BUY'

        return 'HOLD'

    def _check_exit(self, closed, prev) -> str:
        """
        Verifica señales de salida para posiciones abiertas.
        
        Señal de SELL: Cruce bajista (EMA 9 cruza EMA 21 hacia abajo)
        o el precio pierde la EMA 200.
        """
        # Cruce bajista: EMA 9 cruza EMA 21 hacia abajo
        crossover_down = (
            prev.get('EMA_9', 0) >= prev.get('EMA_21', 0) and
            closed.get('EMA_9', 0) < closed.get('EMA_21', 0)
        )

        # Pérdida de macro tendencia
        lost_macro = closed['close'] < closed['EMA_200']

        if crossover_down:
            self.signals_emitted += 1
            logger.info(
                f"🔴 SEÑAL DE SALIDA #{self.signals_emitted}: Cruce bajista EMA9/21 | "
                f"Precio: ${closed['close']:.2f}"
            )
            return 'SELL'

        if lost_macro:
            self.signals_emitted += 1
            logger.info(
                f"🔴 SEÑAL DE SALIDA #{self.signals_emitted}: Precio bajo EMA200 | "
                f"Precio: ${closed['close']:.2f} < EMA200: ${closed['EMA_200']:.2f}"
            )
            return 'SELL'

        return 'HOLD'

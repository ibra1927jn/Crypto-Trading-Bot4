"""
Crypto-Trading-Bot4 — Alpha Engine v3 (Sniper Rotativo)
=======================================================
Evalúa TODAS las monedas y devuelve la MEJOR señal.
Score basado en RSI7, volumen, MACD, y posición en Bollinger.
"""

import pandas as pd
from config.settings import (
    RSI_EXTREME_THRESHOLD, RSI_EXIT_THRESHOLD,
    ACTIVE_STRATEGY
)
from utils.logger import setup_logger

logger = setup_logger("ALPHA")


class AlphaEngine:
    """
    Sniper Rotativo: evalúa N monedas y devuelve la mejor oportunidad.
    """

    def __init__(self):
        logger.info(
            f"🎯 Sniper Rotativo inicializado | "
            f"RSI7 < {RSI_EXTREME_THRESHOLD} | EXIT RSI > {RSI_EXIT_THRESHOLD}"
        )

    def _safe(self, row, col, default=0.0) -> float:
        if row is None:
            return default
        val = row.get(col) if isinstance(row, dict) else (
            row[col] if col in row.index else None
        )
        return float(val) if val is not None and not pd.isna(val) else default

    # ==========================================================
    # SCORING: Evalúa una señal de compra (0-100)
    # ==========================================================

    def _score_buy_signal(self, snapshot: dict, df: pd.DataFrame) -> float:
        """
        Calcula un score de 0-100 para una señal de compra.
        Más alto = mejor oportunidad. 0 = no comprar.
        """
        if df is None or len(df) < 60:
            return 0.0

        last = df.iloc[-2]   # Última vela CERRADA
        prev = df.iloc[-3]   # Anterior

        rsi7 = self._safe(last, 'RSI_7', 50)
        rsi7_prev = self._safe(prev, 'RSI_7', 50)
        rsi14 = self._safe(last, 'RSI_14', 50)
        vol_ratio = self._safe(last, 'VOL_RATIO', 1.0)
        macd = self._safe(last, 'MACD', 0)
        macd_s = self._safe(last, 'MACD_S', 0)
        stoch_k = self._safe(last, 'STOCH_K', 50)
        bb_lo = self._safe(last, 'BB_LO', 0)
        bb_mid = self._safe(last, 'BB_MID', 0)
        price = snapshot.get('price', 0)

        ema50 = self._safe(last, 'EMA_50', 0)
        ema200 = self._safe(last, 'EMA_200', 0)

        score = 0.0

        # ── CONDICIÓN BASE: RSI7 debe estar bajo y SUBIENDO ──
        if rsi7 >= RSI_EXTREME_THRESHOLD or rsi7 <= rsi7_prev:
            return 0.0  # No hay señal

        # ── FILTRO DE TENDENCIA: no comprar en caida libre ──
        # Si EMA200 existe y EMA50 esta por debajo, el mercado es bajista
        if ema50 > 0 and ema200 > 0 and ema50 < ema200 * 0.98:
            return 0.0  # Tendencia bajista confirmada, no comprar

        # ── PUNTOS POR RSI7 (más bajo = mejor) ──
        # RSI7 = 5 → 40 pts, RSI7 = 15 → 20 pts, RSI7 = 24 → 2 pts
        rsi_score = max(0, (RSI_EXTREME_THRESHOLD - rsi7) * 2)
        score += min(rsi_score, 40)

        # ── PUNTOS POR VOLUMEN (confirmación) ──
        if vol_ratio > 2.0:
            score += 20  # Volumen 2x = confirmación fuerte
        elif vol_ratio > 1.5:
            score += 15
        elif vol_ratio > 1.2:
            score += 10
        elif vol_ratio > 1.0:
            score += 5

        # ── PUNTOS POR MACD (momentum) ──
        if macd > macd_s:
            score += 10  # MACD cruzando al alza
        elif macd > macd_s * 0.95:
            score += 5   # Cerca de cruzar

        # ── PUNTOS POR POSICIÓN EN BOLLINGER ──
        if bb_lo > 0 and price > 0:
            if price <= bb_lo * 1.01:
                score += 15  # En banda inferior = sobreventa extrema
            elif price < bb_mid:
                score += 5   # Bajo la media

        # ── PUNTOS POR STOCHASTIC ──
        if stoch_k < 20:
            score += 10  # Stochastic también sobrevendido
        elif stoch_k < 30:
            score += 5

        # ── PUNTOS POR RSI14 BAJO (confirmación adicional) ──
        if rsi14 < 30:
            score += 5
        elif rsi14 < 40:
            score += 2

        return score

    # ==========================================================
    # SEÑAL DE SALIDA
    # ==========================================================

    def should_exit(self, df: pd.DataFrame) -> bool:
        """¿Debería cerrar la posición actual?"""
        if df is None or len(df) < 3:
            return False

        last = df.iloc[-2]
        rsi7 = self._safe(last, 'RSI_7', 50)

        # Salir si RSI7 > umbral de salida
        if rsi7 > RSI_EXIT_THRESHOLD:
            return True

        # Salir si MACD cruza a la baja (momentum se acaba)
        macd = self._safe(last, 'MACD', 0)
        macd_s = self._safe(last, 'MACD_S', 0)
        prev = df.iloc[-3]
        macd_prev = self._safe(prev, 'MACD', 0)
        macd_s_prev = self._safe(prev, 'MACD_S', 0)

        if macd_prev > macd_s_prev and macd < macd_s:
            return True  # MACD death cross

        return False

    # ==========================================================
    # SNIPER ROTATIVO: Buscar la MEJOR señal entre N monedas
    # ==========================================================

    def get_best_signal(
        self,
        snapshots: dict,
        dataframes: dict,
        has_position: bool,
        external_scores: dict = None,
    ) -> dict:
        """
        Evalúa todas las monedas y devuelve la mejor señal.
        
        Score total = Técnico (0-100) + Externo (-20 to +20)

        Args:
            external_scores: {symbol: {'total_boost': 10, ...}} from NewsEngine

        Returns:
            {
                'signal': 'BUY' | 'HOLD',
                'symbol': 'XRP/USDT',
                'score': 72.5,
                'all_scores': {'XRP/USDT': 72.5, 'DOGE/USDT': 45, ...}
            }
        """
        # Si ya tenemos posición, no buscar nuevas señales
        if has_position:
            return {'signal': 'HOLD', 'symbol': None, 'score': 0, 'all_scores': {}}

        scores = {}
        for symbol in snapshots:
            snap = snapshots[symbol]
            df = dataframes.get(symbol)
            
            # Score técnico (0-100)
            technical = self._score_buy_signal(snap, df)
            
            # Score externo (-20 to +20)
            ext_boost = 0
            if external_scores and symbol in external_scores:
                ext_boost = external_scores[symbol].get('total_boost', 0)
            
            # Score total
            total = max(0, technical + ext_boost)
            scores[symbol] = total
            
            if technical > 0:
                logger.debug(
                    f"  {symbol}: Tech={technical:.0f} + Ext={ext_boost:+d} = {total:.0f}"
                )

        # Encontrar la mejor
        best_symbol = max(scores, key=scores.get) if scores else None
        best_score = scores.get(best_symbol, 0) if best_symbol else 0

        # Umbral mínimo: score > 20 para comprar
        MIN_SCORE = 20
        if best_score >= MIN_SCORE:
            logger.info(
                f"🎯 Señal encontrada: {best_symbol} (score: {best_score:.0f}) | "
                f"Scores: {', '.join(f'{s}={sc:.0f}' for s, sc in sorted(scores.items(), key=lambda x: -x[1]))}"
            )
            return {
                'signal': 'BUY',
                'symbol': best_symbol,
                'score': best_score,
                'all_scores': scores,
            }

        return {'signal': 'HOLD', 'symbol': None, 'score': 0, 'all_scores': scores}

    # ==========================================================
    # COMPATIBILIDAD (para código legacy)
    # ==========================================================

    def get_signal(self, df: pd.DataFrame, has_position: bool = False) -> str:
        """Compatibilidad con código antiguo (single-coin)."""
        if df is None or len(df) < 60:
            return 'HOLD'

        last = df.iloc[-2]
        prev = df.iloc[-3]

        rsi7 = self._safe(last, 'RSI_7', 50)
        rsi7_prev = self._safe(prev, 'RSI_7', 50)

        if has_position:
            if rsi7 > RSI_EXIT_THRESHOLD:
                return 'SELL'
            return 'HOLD'

        if rsi7 < RSI_EXTREME_THRESHOLD and rsi7 > rsi7_prev:
            return 'BUY'

        return 'HOLD'

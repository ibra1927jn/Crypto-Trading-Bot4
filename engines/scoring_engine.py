"""
Crypto-Trading-Bot4 — Scoring Engine (Puntuacion basada en reglas)
==================================================================
Evalua datos de mercado y devuelve un score de confianza 0-100
para entrada de trade. No usa ML — scoring ponderado por reglas.

Senales evaluadas:
  - RSI oversold/overbought (peso: 25%)
  - Volume spike vs media (peso: 20%)
  - Price momentum (EMA crossover) (peso: 20%)
  - MACD crossover (peso: 15%)
  - Bollinger Band position (peso: 10%)
  - ADX trend strength (peso: 10%)

Uso:
  from engines.scoring_engine import ScoringEngine
  scorer = ScoringEngine()
  result = scorer.score(market_data)
  # result = {'score': 72, 'verdict': 'STRONG', 'signals': {...}}
"""

import pandas as pd
from typing import Dict, Optional, Any
from utils.logger import setup_logger

logger = setup_logger("SCORING")

# Pesos de cada senal (suman 100)
WEIGHTS = {
    'rsi':        25,
    'volume':     20,
    'momentum':   20,
    'macd':       15,
    'bollinger':  10,
    'adx':        10,
}


def _safe_val(data: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Extrae valor numerico de forma segura."""
    val = data.get(key, default)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return float(val)


class ScoringEngine:
    """
    Motor de scoring basado en reglas ponderadas.
    Recibe datos de mercado (OHLCV + indicadores) y devuelve
    un score de confianza 0-100 para entrada long.
    """

    def __init__(self, weights: Optional[Dict[str, int]] = None):
        self.weights = weights or WEIGHTS.copy()
        total = sum(self.weights.values())
        if total != 100:
            # Normalizar pesos a 100
            for k in self.weights:
                self.weights[k] = int(self.weights[k] / total * 100)
        logger.info(f"ScoringEngine inicializado | Pesos: {self.weights}")

    # ─── SENALES INDIVIDUALES (cada una devuelve 0.0 - 1.0) ───

    def _score_rsi(self, data: dict) -> float:
        """
        RSI oversold = alta confianza para long.
        RSI7 < 20 = 1.0, RSI7 = 30 = 0.5, RSI7 > 50 = 0.0
        Bonus si RSI7 esta subiendo (rebote confirmado).
        """
        rsi7 = _safe_val(data, 'rsi_7', 50)
        rsi7_prev = _safe_val(data, 'rsi_7_prev', 50)
        rsi14 = _safe_val(data, 'rsi_14', 50)

        if rsi7 >= 50:
            return 0.0

        # Score base: cuanto mas bajo RSI7, mejor
        base = max(0.0, (50 - rsi7) / 50)

        # Bonus por rebote (RSI subiendo desde oversold)
        bounce_bonus = 0.0
        if rsi7 < 35 and rsi7 > rsi7_prev:
            bounce_bonus = 0.2

        # Bonus si RSI14 tambien esta bajo (confluencia)
        rsi14_bonus = 0.0
        if rsi14 < 40:
            rsi14_bonus = 0.1

        return min(1.0, base + bounce_bonus + rsi14_bonus)

    def _score_volume(self, data: dict) -> float:
        """
        Volume spike = confirmacion de movimiento.
        vol_ratio > 3.0 = 1.0, > 2.0 = 0.7, > 1.5 = 0.4, <= 1.0 = 0.0
        """
        vol_ratio = _safe_val(data, 'volume_ratio', 1.0)

        if vol_ratio <= 1.0:
            return 0.0
        elif vol_ratio <= 1.5:
            return 0.2 + (vol_ratio - 1.0) * 0.4
        elif vol_ratio <= 2.0:
            return 0.4 + (vol_ratio - 1.5) * 0.6
        elif vol_ratio <= 3.0:
            return 0.7 + (vol_ratio - 2.0) * 0.3
        else:
            return 1.0

    def _score_momentum(self, data: dict) -> float:
        """
        Price momentum basado en EMAs.
        Precio > EMA9 > EMA21 = tendencia alcista fuerte.
        Precio cruzando EMA9 desde abajo = entrada ideal.
        """
        price = _safe_val(data, 'close', 0)
        ema9 = _safe_val(data, 'ema_9', 0)
        ema21 = _safe_val(data, 'ema_21', 0)
        ema50 = _safe_val(data, 'ema_50', 0)

        if price == 0 or ema9 == 0:
            return 0.0

        score = 0.0

        # Precio sobre EMA9 (momentum inmediato)
        if price > ema9:
            score += 0.3

        # EMA9 sobre EMA21 (tendencia corta)
        if ema9 > 0 and ema21 > 0 and ema9 > ema21:
            score += 0.3

        # Distancia del precio al EMA50 (no muy lejos = mejor entrada)
        if ema50 > 0:
            dist_pct = (price - ema50) / ema50 * 100
            if -5 < dist_pct < 2:
                # Cerca del EMA50 desde abajo = zona ideal
                score += 0.4
            elif 2 <= dist_pct < 5:
                score += 0.2

        return min(1.0, score)

    def _score_macd(self, data: dict) -> float:
        """
        MACD crossover alcista = senal de compra.
        MACD > Signal = 0.5 base.
        Histograma creciendo = +0.3 bonus.
        Cruce reciente (histograma era negativo) = +0.2 bonus.
        """
        macd = _safe_val(data, 'macd', 0)
        macd_signal = _safe_val(data, 'macd_signal', 0)
        macd_hist = _safe_val(data, 'macd_hist', 0)
        macd_hist_prev = _safe_val(data, 'macd_hist_prev', 0)

        score = 0.0

        # MACD sobre Signal (bullish)
        if macd > macd_signal:
            score += 0.5

        # Histograma creciendo
        if macd_hist > macd_hist_prev:
            score += 0.3

        # Cruce reciente (histograma cambio de signo)
        if macd_hist > 0 and macd_hist_prev <= 0:
            score += 0.2

        return min(1.0, score)

    def _score_bollinger(self, data: dict) -> float:
        """
        Precio cerca de banda inferior = posible rebote.
        Precio en BB lower = 1.0, en BB mid = 0.3, en BB upper = 0.0
        """
        price = _safe_val(data, 'close', 0)
        bb_lower = _safe_val(data, 'bb_lower', 0)
        bb_mid = _safe_val(data, 'bb_mid', 0)
        bb_upper = _safe_val(data, 'bb_upper', 0)

        if bb_upper <= bb_lower or price == 0:
            return 0.0

        # Posicion normalizada dentro de las bandas (0 = lower, 1 = upper)
        bb_pos = (price - bb_lower) / (bb_upper - bb_lower)
        bb_pos = max(0.0, min(1.0, bb_pos))

        # Invertir: mas cerca de lower = mejor para long
        if bb_pos <= 0.15:
            return 1.0
        elif bb_pos <= 0.30:
            return 0.7
        elif bb_pos <= 0.50:
            return 0.3
        else:
            return 0.0

    def _score_adx(self, data: dict) -> float:
        """
        ADX mide fuerza de tendencia (no direccion).
        ADX > 25 con precio subiendo = tendencia fuerte (bueno para momentum).
        ADX < 15 = mercado lateral (malo para cualquier estrategia).
        """
        adx = _safe_val(data, 'adx', 0)
        price = _safe_val(data, 'close', 0)
        ema9 = _safe_val(data, 'ema_9', 0)

        if adx < 15:
            return 0.0
        elif adx < 20:
            return 0.2
        elif adx < 25:
            # Tendencia moderada — bonus si precio sobre EMA
            base = 0.4
            if price > ema9 > 0:
                base += 0.2
            return base
        elif adx < 40:
            # Tendencia fuerte
            base = 0.7
            if price > ema9 > 0:
                base += 0.3
            return min(1.0, base)
        else:
            # ADX muy alto puede indicar agotamiento
            return 0.5

    # ─── SCORING PRINCIPAL ───

    def score(self, data: dict) -> dict:
        """
        Calcula score de confianza 0-100 para entrada long.

        Args:
            data: dict con claves de mercado:
                - close: precio actual
                - rsi_7, rsi_7_prev: RSI 7 actual y anterior
                - rsi_14: RSI 14
                - volume_ratio: volumen / SMA20 volumen
                - ema_9, ema_21, ema_50: EMAs
                - macd, macd_signal, macd_hist, macd_hist_prev: MACD
                - bb_lower, bb_mid, bb_upper: Bollinger Bands
                - adx: ADX

        Returns:
            dict con:
                score: int 0-100
                verdict: SKIP / WEAK / MODERATE / STRONG / EXCELLENT
                signals: dict con score individual de cada senal
                recommendation: texto legible
        """
        # Filtro de tendencia: si EMA50 < EMA200, mercado bajista → score 0
        ema50 = _safe_val(data, 'ema_50', 0)
        ema200 = _safe_val(data, 'ema_200', 0)
        if ema50 > 0 and ema200 > 0 and ema50 < ema200 * 0.98:
            return {
                'score': 0, 'verdict': 'SKIP',
                'recommendation': 'Tendencia bajista (EMA50 < EMA200). No entrar.',
                'signals': {k: 0.0 for k in self.weights},
                'weights': self.weights,
            }

        signals = {
            'rsi':       self._score_rsi(data),
            'volume':    self._score_volume(data),
            'momentum':  self._score_momentum(data),
            'macd':      self._score_macd(data),
            'bollinger': self._score_bollinger(data),
            'adx':       self._score_adx(data),
        }

        # Score ponderado
        weighted_score = sum(
            signals[k] * self.weights[k] for k in signals
        )
        score = int(round(weighted_score))
        score = max(0, min(100, score))

        # Veredicto
        if score >= 80:
            verdict = "EXCELLENT"
            recommendation = "Senal muy fuerte. Entrada con posicion completa."
        elif score >= 60:
            verdict = "STRONG"
            recommendation = "Buena senal. Entrada con 75% de posicion."
        elif score >= 40:
            verdict = "MODERATE"
            recommendation = "Senal moderada. Entrada con 50% o esperar confirmacion."
        elif score >= 20:
            verdict = "WEAK"
            recommendation = "Senal debil. Solo entrar con size reducido."
        else:
            verdict = "SKIP"
            recommendation = "Sin senal clara. No entrar."

        result = {
            'score': score,
            'verdict': verdict,
            'recommendation': recommendation,
            'signals': {k: round(v, 3) for k, v in signals.items()},
            'weights': self.weights,
        }

        logger.info(
            f"Score: {score}/100 ({verdict}) | "
            f"RSI:{signals['rsi']:.2f} VOL:{signals['volume']:.2f} "
            f"MOM:{signals['momentum']:.2f} MACD:{signals['macd']:.2f}"
        )

        return result

    @staticmethod
    def from_dataframe_row(row: pd.Series, prev_row: Optional[pd.Series] = None) -> dict:
        """
        Convierte un row de DataFrame (formato Data Engine) al dict
        que espera score(). Facilita integracion con el pipeline existente.
        """
        def _get(r, col, default=0.0):
            if r is None:
                return default
            val = r.get(col) if isinstance(r, dict) else (
                r[col] if col in r.index else None)
            return float(val) if val is not None and not pd.isna(val) else default

        # Extraer histograma MACD
        macd_val = _get(row, 'MACD', 0)
        macd_s = _get(row, 'MACD_S', 0)
        macd_hist = macd_val - macd_s

        prev_macd = _get(prev_row, 'MACD', 0)
        prev_macd_s = _get(prev_row, 'MACD_S', 0)
        prev_hist = prev_macd - prev_macd_s

        return {
            'close':          _get(row, 'close'),
            'rsi_7':          _get(row, 'RSI_7', 50),
            'rsi_7_prev':     _get(prev_row, 'RSI_7', 50),
            'rsi_14':         _get(row, 'RSI_14', 50),
            'volume_ratio':   _get(row, 'VOL_RATIO', 1.0),
            'ema_9':          _get(row, 'EMA_9', 0),
            'ema_21':         _get(row, 'EMA_21', 0),
            'ema_50':         _get(row, 'EMA_50', 0),
            'ema_200':        _get(row, 'EMA_200', 0),
            'macd':           macd_val,
            'macd_signal':    macd_s,
            'macd_hist':      macd_hist,
            'macd_hist_prev': prev_hist,
            'bb_lower':       _get(row, 'BB_LO', 0),
            'bb_mid':         _get(row, 'BB_MID', 0),
            'bb_upper':       _get(row, 'BB_HI', 0),
            'adx':            _get(row, 'ADX_14', 0),
        }


# ── CLI para testing rapido ──
if __name__ == "__main__":
    # Demo con datos sinteticos
    demo_data = {
        'close': 100.0,
        'rsi_7': 22,
        'rsi_7_prev': 18,
        'rsi_14': 35,
        'volume_ratio': 2.3,
        'ema_9': 99.5,
        'ema_21': 98.0,
        'ema_50': 97.0,
        'macd': 0.5,
        'macd_signal': 0.3,
        'macd_hist': 0.2,
        'macd_hist_prev': -0.1,
        'bb_lower': 95.0,
        'bb_mid': 100.0,
        'bb_upper': 105.0,
        'adx': 28,
    }

    scorer = ScoringEngine()
    result = scorer.score(demo_data)

    print(f"\nScore: {result['score']}/100")
    print(f"Verdict: {result['verdict']}")
    print(f"Recommendation: {result['recommendation']}")
    print(f"\nSignals:")
    for sig, val in result['signals'].items():
        print(f"  {sig:12s}: {val:.3f} (peso: {result['weights'][sig]}%)")

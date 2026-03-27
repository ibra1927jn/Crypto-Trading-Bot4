"""
similarity.py — Scoring AI v2: Weighted Similarity Engine
============================================================
Compares trade context vectors using weighted cosine similarity.
Supports 20-dimensional vectors with configurable feature weights.

Key improvements over v1:
  - Feature weighting (not all dimensions are equally important)
  - Works with pre-normalized vectors (0-1 range)
  - Composite score: 70% cosine + 30% inverse euclidean

No ML frameworks needed — only NumPy.
"""

import numpy as np
from typing import Optional

# ── Feature Weights (higher = more influence on similarity) ───────────────────
# These weights determine how much each dimension matters when comparing trades.
# Total doesn't need to sum to 1 — they're normalized internally.
FEATURE_WEIGHTS = {
    "adx":             1.5,   # Trend strength is very important
    "rsi":             2.0,   # RSI is the #1 predictor
    "atr_pct":         1.5,   # Volatility context matters
    "ema50_dist":      1.2,   # Distance from moving averages
    "ema200_dist":     1.0,   # Long-term trend context
    "btc_corr":        1.8,   # BTC correlation is critical
    "volume_ratio":    1.3,   # Volume confirms moves
    "side_int":        2.5,   # LONG vs SHORT is fundamental
    "hold_hours":      0.5,   # Less important for similarity
    "funding_rate":    1.8,   # Funding = crowd positioning
    "oi_change_pct":   1.5,   # Open interest signals
    "hour_of_day":     0.8,   # Time patterns exist but are subtle
    "day_of_week":     0.5,   # Less impactful
    "fear_greed":      2.0,   # Market sentiment is critical
    "market_regime":   2.5,   # Bull/bear/lateral is fundamental
    "bb_position":     1.2,   # Bollinger position
    "macd_hist_norm":  1.0,   # Momentum direction
    "consec_candles":  1.0,   # Streak context
    "btc_dominance":   1.0,   # Alt season indicator
    "news_sentiment":  1.5,   # News sentiment
}

# Ordered weight array (must match VECTOR_COLS order from collector.py)
WEIGHT_ARRAY = np.array([
    FEATURE_WEIGHTS["adx"],
    FEATURE_WEIGHTS["rsi"],
    FEATURE_WEIGHTS["atr_pct"],
    FEATURE_WEIGHTS["ema50_dist"],
    FEATURE_WEIGHTS["ema200_dist"],
    FEATURE_WEIGHTS["btc_corr"],
    FEATURE_WEIGHTS["volume_ratio"],
    FEATURE_WEIGHTS["side_int"],
    FEATURE_WEIGHTS["hold_hours"],
    FEATURE_WEIGHTS["funding_rate"],
    FEATURE_WEIGHTS["oi_change_pct"],
    FEATURE_WEIGHTS["hour_of_day"],
    FEATURE_WEIGHTS["day_of_week"],
    FEATURE_WEIGHTS["fear_greed"],
    FEATURE_WEIGHTS["btc_dominance"],
    FEATURE_WEIGHTS["market_regime"],
    FEATURE_WEIGHTS["bb_position"],
    FEATURE_WEIGHTS["macd_hist_norm"],
    FEATURE_WEIGHTS["consec_candles"],
    FEATURE_WEIGHTS["news_sentiment"],
], dtype=float)


# ── Core math ──────────────────────────────────────────────────────────────────
def weighted_cosine_similarity(a: list[float], b: list[float],
                                weights: np.ndarray = WEIGHT_ARRAY) -> float:
    """
    Weighted cosine similarity.
    Each dimension is multiplied by its weight before computing cosine.
    Returns -1 to +1 (1 = identical direction).
    """
    va = np.array(a, dtype=float) * weights
    vb = np.array(b, dtype=float) * weights
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def weighted_euclidean_dist(a: list[float], b: list[float],
                            weights: np.ndarray = WEIGHT_ARRAY) -> float:
    """Weighted Euclidean distance. 0 = identical."""
    diff = (np.array(a, dtype=float) - np.array(b, dtype=float)) * weights
    return float(np.linalg.norm(diff))


def composite_similarity(a: list[float], b: list[float],
                          weights: np.ndarray = WEIGHT_ARRAY) -> float:
    """
    Composite score: 70% weighted cosine + 30% inverse euclidean distance.
    Returns 0 to 1 (1 = perfectly similar).
    """
    cos_sim = weighted_cosine_similarity(a, b, weights)
    cos_01 = (cos_sim + 1) / 2  # Map [-1, 1] → [0, 1]

    euc_dist = weighted_euclidean_dist(a, b, weights)
    euc_sim = 1.0 / (1.0 + euc_dist)  # Inverse: high dist → low sim

    return 0.7 * cos_01 + 0.3 * euc_sim


def normalize_vector(v: list[float]) -> list[float]:
    """L2 normalize a vector."""
    arr = np.array(v, dtype=float)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return v
    return (arr / norm).tolist()


# ── Batch search ───────────────────────────────────────────────────────────────
def top_similar(
    query_vector: list[float],
    db_records: list[dict],
    n: int = 10,
    outcome_filter: Optional[int] = None,
    use_normalized: bool = True,
) -> list[dict]:
    """
    Find top-N most similar trade records using composite similarity.

    Args:
        query_vector:   The candidate trade's context vector (normalized or raw).
        db_records:     List of trade records from vector_db.json.
        n:              How many results to return.
        outcome_filter: 0=losses only, 1=wins only, None=all.
        use_normalized: If True, use pre-normalized vectors (recommended).
    """
    results = []
    vec_key = "norm_vector" if use_normalized else "vector"

    for rec in db_records:
        if outcome_filter is not None and rec.get("outcome") != outcome_filter:
            continue
        v = rec.get(vec_key, rec.get("vector", []))
        if len(v) != len(query_vector):
            continue

        sim = composite_similarity(query_vector, v)

        results.append({
            "symbol":     rec.get("symbol", "?"),
            "side":       rec.get("side", "?"),
            "strategy":   rec.get("strategy", "?"),
            "outcome":    rec.get("outcome", 0),
            "pnl_pct":    rec.get("pnl_pct", 0),
            "close_time": rec.get("close_time", ""),
            "reason":     rec.get("reason", ""),
            "similarity": round(sim, 4),
        })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:n]


# ── Quick test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 20-dim test vectors (normalized 0-1 range)
    a = [0.31, 0.62, 0.08, 0.54, 0.53, 0.90, 0.22, 1.00, 0.12,
         0.50, 0.50, 0.52, 0.50, 0.40, 0.55, 1.00, 0.50, 0.30, 0.60, 0.00]

    b = [0.30, 0.60, 0.09, 0.54, 0.51, 0.85, 0.20, 1.00, 0.10,
         0.50, 0.50, 0.48, 0.50, 0.38, 0.55, 1.00, 0.48, 0.28, 0.55, 0.00]

    c = [0.15, 0.28, 0.33, 0.58, 0.56, 0.10, 0.06, 0.00, 0.01,
         0.50, 0.50, 0.30, 0.17, 0.80, 0.60, 0.00, 0.10, -0.50, -0.40, -0.50]

    print(f"Composite a↔b: {composite_similarity(a, b):.4f}  (should be HIGH, ~0.95+)")
    print(f"Composite a↔c: {composite_similarity(a, c):.4f}  (should be LOW, ~0.40)")
    print(f"W-Cosine  a↔b: {weighted_cosine_similarity(a, b):.4f}")
    print(f"W-Cosine  a↔c: {weighted_cosine_similarity(a, c):.4f}")
    print(f"W-Euclid  a↔b: {weighted_euclidean_dist(a, b):.4f}")
    print(f"W-Euclid  a↔c: {weighted_euclidean_dist(a, c):.4f}")

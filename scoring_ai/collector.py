"""
collector.py — Scoring AI v2: 20-Dimension Vector Builder
==========================================================
Reads trade CSVs and builds enriched context vectors.

Vector dimensions (20):
  [0]  adx            - Trend strength (ADX 14)
  [1]  rsi            - RSI 14
  [2]  atr_pct        - Volatility: ATR/price
  [3]  ema50_dist     - Distance to EMA50 (%)
  [4]  ema200_dist    - Distance to EMA200 (%)
  [5]  btc_corr       - BTC correlation (RSI proxy 0-1)
  [6]  volume_ratio   - Vol vs 20-period MA
  [7]  side_int       - +1=LONG, -1=SHORT
  [8]  hold_hours     - Position duration
  [9]  funding_rate   - Funding rate (0 if unavailable)
  [10] oi_change_pct  - Open interest change % (0 if unavailable)
  [11] hour_of_day    - 0-23 normalized to 0-1
  [12] day_of_week    - 0-6 normalized to 0-1
  [13] fear_greed     - Fear & Greed index 0-100 normalized to 0-1
  [14] btc_dominance  - BTC.D % normalized to 0-1
  [15] market_regime  - -1=bear, 0=lateral, +1=bull
  [16] bb_position    - Bollinger Band position 0-1
  [17] macd_hist_norm - MACD histogram normalized
  [18] consec_candles - Green/red streak (-5 to +5) normalized
  [19] news_sentiment - News sentiment -1 to +1 (Phase 3)

Usage:
    python collector.py
    python collector.py --csv path/to/trades.csv
"""

import os
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_CSV = "/opt/ct4/logs/v12_trades.csv"
LOCAL_CSV   = os.path.join(os.path.dirname(__file__), "..", "v12_trades.csv")
TRAINING_CSV = os.path.join(os.path.dirname(__file__), "training_data.csv")
OUTPUT_DB   = os.path.join(os.path.dirname(__file__), "vector_db.json")

VECTOR_COLS = [
    "adx", "rsi", "atr_pct", "ema50_dist", "ema200_dist",
    "btc_corr", "volume_ratio", "side_int", "hold_hours",
    "funding_rate", "oi_change_pct", "hour_of_day", "day_of_week",
    "fear_greed", "btc_dominance", "market_regime", "bb_position",
    "macd_hist_norm", "consec_candles", "news_sentiment",
]

# ── Normalization ranges for Z-score style (min, max) ─────────────────────────
NORM_RANGES = {
    "adx":            (0, 80),
    "rsi":            (0, 100),
    "atr_pct":        (0, 0.15),
    "ema50_dist":     (-20, 20),
    "ema200_dist":    (-40, 40),
    "btc_corr":       (0, 1),
    "volume_ratio":   (0, 5),
    "side_int":       (-1, 1),
    "hold_hours":     (0, 200),
    "funding_rate":   (-0.1, 0.1),
    "oi_change_pct":  (-50, 50),
    "hour_of_day":    (0, 23),
    "day_of_week":    (0, 6),
    "fear_greed":     (0, 100),
    "btc_dominance":  (40, 70),
    "market_regime":  (-1, 1),
    "bb_position":    (-0.5, 1.5),
    "macd_hist_norm": (-1, 1),
    "consec_candles": (-5, 5),
    "news_sentiment": (-1, 1),
}


def normalize_value(col_name: str, raw: float) -> float:
    """Min-max normalize a value to [0, 1] range."""
    lo, hi = NORM_RANGES.get(col_name, (0, 1))
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (raw - lo) / (hi - lo)))


# ── Loader ─────────────────────────────────────────────────────────────────────
def load_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        print(f"[collector] ⚠️  CSV not found: {path}")
        return pd.DataFrame()
    df = pd.read_csv(path)
    print(f"[collector] Loaded {len(df)} trades from {path}")
    return df


# ── Market Regime Detector ─────────────────────────────────────────────────────
def detect_regime(adx: float, rsi: float, ema50_dist: float) -> float:
    """
    Simple market regime detection:
      Bull  (+1): RSI > 55 AND price above EMA50
      Bear  (-1): RSI < 45 AND price below EMA50
      Lateral (0): everything else
    """
    if rsi > 55 and ema50_dist > 0 and adx > 20:
        return 1.0
    elif rsi < 45 and ema50_dist < 0 and adx > 20:
        return -1.0
    return 0.0


# ── Vector builder ─────────────────────────────────────────────────────────────
def build_vector(row: pd.Series) -> dict | None:
    """
    Build 20-dimension context vector from a trade row.
    Falls back to sensible defaults for missing columns.
    """
    try:
        # === Original 9 dimensions ===
        side_int = 1 if str(row.get("side", "LONG")).upper() == "LONG" else -1

        entry_time = pd.to_datetime(row.get("entry_time", ""), utc=True, errors="coerce")
        close_time = pd.to_datetime(row.get("close_time", ""), utc=True, errors="coerce")
        hold_hours = float((close_time - entry_time).total_seconds() / 3600) if (
            pd.notna(entry_time) and pd.notna(close_time)) else 0.0

        adx            = float(row.get("adx", 25) or 25)
        rsi            = float(row.get("rsi", 50) or 50)
        atr_pct        = float(row.get("atr_pct", 0.02) or 0.02)
        ema50_dist     = float(row.get("ema50_dist_pct", 0) or 0)
        ema200_dist    = float(row.get("ema200_dist_pct", 0) or 0)
        btc_corr       = float(row.get("btc_corr_4c", 0.5) or 0.5)
        volume_ratio   = float(row.get("volume_ratio", 1) or 1)

        # === New 11 dimensions (v2) ===
        funding_rate   = float(row.get("funding_rate", 0) or 0)
        oi_change_pct  = float(row.get("oi_change_pct", 0) or 0)

        # Time features
        if pd.notna(entry_time):
            hour_of_day = entry_time.hour
            day_of_week = entry_time.dayofweek
        else:
            hour_of_day = 12
            day_of_week = 3

        fear_greed     = float(row.get("fear_greed", 50) or 50)
        btc_dominance  = float(row.get("btc_dominance", 55) or 55)
        market_regime  = detect_regime(adx, rsi, ema50_dist)
        bb_position    = float(row.get("bb_position", 0.5) or 0.5)
        macd_hist_norm = float(row.get("macd_hist_norm", 0) or 0)
        consec_candles = float(row.get("consec_candles", 0) or 0)
        news_sentiment = float(row.get("news_sentiment", 0) or 0)

        # Outcome
        pnl_pct = float(row.get("pnl_pct", 0) or 0)
        outcome = 1 if pnl_pct > 0 else 0

        # Raw vector (for storage)
        raw_vector = [
            adx, rsi, atr_pct, ema50_dist, ema200_dist,
            btc_corr, volume_ratio, side_int, hold_hours,
            funding_rate, oi_change_pct, hour_of_day, day_of_week,
            fear_greed, btc_dominance, market_regime, bb_position,
            macd_hist_norm, consec_candles, news_sentiment,
        ]

        # Normalized vector (for similarity comparison)
        norm_vector = [
            normalize_value(col, val)
            for col, val in zip(VECTOR_COLS, raw_vector)
        ]

        return {
            "symbol":      str(row.get("symbol", "UNKNOWN")),
            "side":        str(row.get("side", "LONG")),
            "strategy":    str(row.get("strategy", "V15")),
            "outcome":     outcome,
            "pnl_pct":     round(pnl_pct, 4),
            "close_time":  str(row.get("close_time", "")),
            "reason":      str(row.get("reason", "")),
            "vector":      [round(v, 5) for v in raw_vector],
            "norm_vector": [round(v, 5) for v in norm_vector],
        }
    except Exception as e:
        print(f"[collector] ⚠️  Skipping row — {e}")
        return None


# ── Stats ──────────────────────────────────────────────────────────────────────
def compute_stats(records: list) -> dict:
    """Compute per-dimension statistics for calibration."""
    if not records:
        return {}
    vectors = np.array([r["vector"] for r in records])
    stats = {}
    for i, col in enumerate(VECTOR_COLS):
        col_data = vectors[:, i]
        stats[col] = {
            "mean": round(float(np.mean(col_data)), 4),
            "std":  round(float(np.std(col_data)), 4),
            "min":  round(float(np.min(col_data)), 4),
            "max":  round(float(np.max(col_data)), 4),
            "p25":  round(float(np.percentile(col_data, 25)), 4),
            "p75":  round(float(np.percentile(col_data, 75)), 4),
        }
    return stats


# ── Main ───────────────────────────────────────────────────────────────────────
def run(csv_path: str):
    df = load_csv(csv_path)
    if df.empty:
        print("[collector] No data to process.")
        return

    records = []
    for _, row in df.iterrows():
        v = build_vector(row)
        if v:
            records.append(v)

    losers  = [r for r in records if r["outcome"] == 0]
    winners = [r for r in records if r["outcome"] == 1]
    stats   = compute_stats(records)

    # Per-strategy breakdown
    by_strategy = {}
    for r in records:
        s = r["strategy"]
        by_strategy.setdefault(s, {"total": 0, "wins": 0})
        by_strategy[s]["total"] += 1
        if r["outcome"] == 1:
            by_strategy[s]["wins"] += 1

    db = {
        "version":      "2.0",
        "generated_at": datetime.utcnow().isoformat(),
        "total_trades": len(records),
        "winners":      len(winners),
        "losers":       len(losers),
        "win_rate":     round(len(winners) / len(records) * 100, 1) if records else 0,
        "vector_dims":  len(VECTOR_COLS),
        "vector_cols":  VECTOR_COLS,
        "norm_ranges":  NORM_RANGES,
        "dim_stats":    stats,
        "by_strategy":  by_strategy,
        "records":      records,
    }

    with open(OUTPUT_DB, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    print(f"\n[collector] ✅  Vector DB v2 saved → {OUTPUT_DB}")
    print(f"            Dimensions: {len(VECTOR_COLS)}")
    print(f"            Trades: {len(records)} | W: {len(winners)} | L: {len(losers)}")
    print(f"            Win Rate: {db['win_rate']}%")
    if by_strategy:
        print(f"            Strategies:")
        for s, v in by_strategy.items():
            wr = round(v["wins"] / max(1, v["total"]) * 100, 1)
            print(f"              {s}: {v['total']} trades, {wr}% WR")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=None, help="Path to trades CSV")
    args = parser.parse_args()

    csv_path = args.csv or (
        TRAINING_CSV if os.path.exists(TRAINING_CSV)
        else DEFAULT_CSV if os.path.exists(DEFAULT_CSV)
        else LOCAL_CSV
    )
    run(csv_path)

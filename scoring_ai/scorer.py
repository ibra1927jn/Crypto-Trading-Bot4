"""
scorer.py — Scoring AI v2: 20-Dimension Risk Scorer
=====================================================
Evaluates a trade signal against the enriched vector database.
Returns a RISK SCORE from 0 to 100.

  0-29   → 🟢 SAFE    (proceed with full position)
  30-49  → 🟡 CAUTION  (reduce position by 25%)
  50-69  → 🟠 RISKY    (reduce position by 50%)
  70-100 → 🔴 VETO     (skip this trade)

Usage:
    python scorer.py --adx 22 --rsi 65 --atr_pct 0.013 --side LONG --fear_greed 25
    python scorer.py --preset demo
"""

import os
import json
import argparse
from similarity import top_similar, composite_similarity
from collector import VECTOR_COLS, NORM_RANGES, normalize_value

DB_PATH = os.path.join(os.path.dirname(__file__), "vector_db.json")


def load_db() -> dict:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Vector DB not found at {DB_PATH}. Run collector.py first.")
    with open(DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_query_vector(
    adx=25, rsi=50, atr_pct=0.02, ema50_dist=0, ema200_dist=0,
    btc_corr=0.5, volume_ratio=1, side="LONG", hold_hours=0,
    funding_rate=0, oi_change_pct=0, hour_of_day=12, day_of_week=3,
    fear_greed=50, btc_dominance=55, market_regime=0, bb_position=0.5,
    macd_hist_norm=0, consec_candles=0, news_sentiment=0,
) -> list[float]:
    """Build a normalized 20-dim query vector from trade parameters."""
    raw = [
        adx, rsi, atr_pct, ema50_dist, ema200_dist,
        btc_corr, volume_ratio,
        1 if str(side).upper() == "LONG" else -1,
        hold_hours, funding_rate, oi_change_pct,
        hour_of_day, day_of_week, fear_greed, btc_dominance,
        market_regime, bb_position, macd_hist_norm,
        consec_candles, news_sentiment,
    ]
    return [normalize_value(col, val) for col, val in zip(VECTOR_COLS, raw)]


def score_trade(
    adx=25, rsi=50, atr_pct=0.02, ema50_dist=0, ema200_dist=0,
    btc_corr=0.5, volume_ratio=1, side="LONG", hold_hours=0,
    funding_rate=0, oi_change_pct=0, hour_of_day=12, day_of_week=3,
    fear_greed=50, btc_dominance=55, market_regime=0, bb_position=0.5,
    macd_hist_norm=0, consec_candles=0, news_sentiment=0,
    top_n=15, similarity_threshold=0.75, verbose=True,
) -> dict:
    """
    Score a candidate trade signal.

    Returns dict with:
        risk_score       : int 0-100
        verdict          : SAFE / CAUTION / RISKY / VETO
        size_multiplier  : 1.0 / 0.75 / 0.5 / 0.0
        similar_losses   : count of matching losing trades
        similar_winners  : count of matching winning trades
        recommendation   : human-readable action
    """
    db = load_db()
    records = db.get("records", [])

    query = build_query_vector(
        adx=adx, rsi=rsi, atr_pct=atr_pct, ema50_dist=ema50_dist,
        ema200_dist=ema200_dist, btc_corr=btc_corr, volume_ratio=volume_ratio,
        side=side, hold_hours=hold_hours, funding_rate=funding_rate,
        oi_change_pct=oi_change_pct, hour_of_day=hour_of_day,
        day_of_week=day_of_week, fear_greed=fear_greed,
        btc_dominance=btc_dominance, market_regime=market_regime,
        bb_position=bb_position, macd_hist_norm=macd_hist_norm,
        consec_candles=consec_candles, news_sentiment=news_sentiment,
    )

    # Find similar trades
    similar_losses  = top_similar(query, records, n=top_n, outcome_filter=0, use_normalized=True)
    similar_winners = top_similar(query, records, n=top_n, outcome_filter=1, use_normalized=True)

    loss_hits = [r for r in similar_losses  if r["similarity"] >= similarity_threshold]
    win_hits  = [r for r in similar_winners if r["similarity"] >= similarity_threshold]

    total_hits = len(loss_hits) + len(win_hits)

    if total_hits == 0:
        # No strong matches — use weak signals
        all_near = similar_losses[:5] + similar_winners[:5]
        if not all_near:
            risk_score = 5
        else:
            loss_count = sum(1 for r in all_near if r.get("outcome") == 0)
            risk_score = int(loss_count / len(all_near) * 50)
        avg_loss_sim = 0.0
    else:
        loss_ratio = len(loss_hits) / total_hits
        avg_loss_sim = (sum(r["similarity"] for r in loss_hits) / len(loss_hits)
                        if loss_hits else 0.0)
        avg_win_sim  = (sum(r["similarity"] for r in win_hits) / len(win_hits)
                        if win_hits else 0.0)

        # Risk formula v2:
        # 60% loss ratio weight + 25% avg loss similarity + 15% confidence penalty
        confidence_penalty = max(0, (avg_loss_sim - avg_win_sim) * 100)
        risk_score = int(
            loss_ratio * 60 +
            avg_loss_sim * 25 +
            min(confidence_penalty, 15)
        )

    risk_score = max(0, min(100, risk_score))

    # Verdict
    if risk_score >= 70:
        verdict = "VETO 🔴"
        recommendation = (f"SKIP. Context matches {len(loss_hits)} past losing trades.")
        size_multiplier = 0.0
    elif risk_score >= 50:
        verdict = "RISKY 🟠"
        recommendation = (f"Reduce 50%. {len(loss_hits)} similar losses detected.")
        size_multiplier = 0.5
    elif risk_score >= 30:
        verdict = "CAUTION 🟡"
        recommendation = (f"Reduce 25%. {len(loss_hits)} weak loss matches.")
        size_multiplier = 0.75
    else:
        verdict = "SAFE 🟢"
        recommendation = "Context looks clean. Proceed with full position."
        size_multiplier = 1.0

    result = {
        "risk_score":          risk_score,
        "verdict":             verdict,
        "recommendation":      recommendation,
        "size_multiplier":     size_multiplier,
        "similar_losses":      len(loss_hits),
        "similar_winners":     len(win_hits),
        "avg_loss_similarity": round(avg_loss_sim, 4),
        "total_db_trades":     db.get("total_trades", 0),
        "db_version":          db.get("version", "1.0"),
        "top_loss_matches":    loss_hits[:5],
        "top_win_matches":     win_hits[:3],
    }

    if verbose:
        _print_result(result)

    return result


def _print_result(result: dict):
    print("\n" + "=" * 60)
    print("  🤖  SCORING AI v2 — Trade Risk Assessment")
    print("=" * 60)
    print(f"  Risk Score  : {result['risk_score']}/100")
    print(f"  Verdict     : {result['verdict']}")
    print(f"  DB Version  : {result['db_version']} ({result['total_db_trades']} trades)")
    print(f"  Sim. Losses : {result['similar_losses']}")
    print(f"  Sim. Winners: {result['similar_winners']}")
    print(f"  Avg Loss Sim: {result['avg_loss_similarity']:.2%}")
    print(f"  Size Factor : {result['size_multiplier']:.0%}")
    print(f"\n  💬 {result['recommendation']}")
    if result["top_loss_matches"]:
        print("\n  📋 Top Similar Losses:")
        for m in result["top_loss_matches"][:3]:
            print(f"     [{m['close_time'][:10]}] {m['symbol']} {m['side']} "
                  f"[{m.get('strategy','?')}] "
                  f"PnL:{m['pnl_pct']:+.2f}% | Sim:{m['similarity']:.2%}")
    if result["top_win_matches"]:
        print("\n  ✅ Top Similar Wins:")
        for m in result["top_win_matches"][:3]:
            print(f"     [{m['close_time'][:10]}] {m['symbol']} {m['side']} "
                  f"[{m.get('strategy','?')}] "
                  f"PnL:{m['pnl_pct']:+.2f}% | Sim:{m['similarity']:.2%}")
    print("=" * 60 + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score a trade (0=safe, 100=veto)")
    parser.add_argument("--adx",             type=float, default=25.0)
    parser.add_argument("--rsi",             type=float, default=50.0)
    parser.add_argument("--atr_pct",         type=float, default=0.02)
    parser.add_argument("--ema50_dist",      type=float, default=0.0)
    parser.add_argument("--ema200_dist",     type=float, default=0.0)
    parser.add_argument("--btc_corr",        type=float, default=0.5)
    parser.add_argument("--volume_ratio",    type=float, default=1.0)
    parser.add_argument("--side",            type=str,   default="LONG")
    parser.add_argument("--hold_hours",      type=float, default=0.0)
    parser.add_argument("--funding_rate",    type=float, default=0.0)
    parser.add_argument("--oi_change_pct",   type=float, default=0.0)
    parser.add_argument("--hour_of_day",     type=float, default=12.0)
    parser.add_argument("--day_of_week",     type=float, default=3.0)
    parser.add_argument("--fear_greed",      type=float, default=50.0)
    parser.add_argument("--btc_dominance",   type=float, default=55.0)
    parser.add_argument("--market_regime",   type=float, default=0.0)
    parser.add_argument("--bb_position",     type=float, default=0.5)
    parser.add_argument("--macd_hist_norm",  type=float, default=0.0)
    parser.add_argument("--consec_candles",  type=float, default=0.0)
    parser.add_argument("--news_sentiment",  type=float, default=0.0)
    parser.add_argument("--top_n",           type=int,   default=15)
    parser.add_argument("--threshold",       type=float, default=0.75)
    parser.add_argument("--preset",          type=str,   default=None)
    args = parser.parse_args()

    if args.preset == "demo":
        print("[scorer] Running DEMO — bullish BTC context, oversold RSI...")
        score_trade(adx=28, rsi=30, atr_pct=0.015, ema50_dist=0.5,
                    ema200_dist=2.0, btc_corr=0.9, volume_ratio=1.3,
                    side="LONG", fear_greed=25, market_regime=1,
                    bb_position=0.1, consec_candles=-3)
    elif args.preset == "risky":
        print("[scorer] Running RISKY — overbought in fear...")
        score_trade(adx=15, rsi=75, atr_pct=0.05, ema50_dist=-3.0,
                    ema200_dist=-8.0, btc_corr=0.2, volume_ratio=0.4,
                    side="LONG", fear_greed=15, market_regime=-1,
                    bb_position=0.9, consec_candles=-4, news_sentiment=-0.5)
    else:
        score_trade(
            adx=args.adx, rsi=args.rsi, atr_pct=args.atr_pct,
            ema50_dist=args.ema50_dist, ema200_dist=args.ema200_dist,
            btc_corr=args.btc_corr, volume_ratio=args.volume_ratio,
            side=args.side, hold_hours=args.hold_hours,
            funding_rate=args.funding_rate, oi_change_pct=args.oi_change_pct,
            hour_of_day=args.hour_of_day, day_of_week=args.day_of_week,
            fear_greed=args.fear_greed, btc_dominance=args.btc_dominance,
            market_regime=args.market_regime, bb_position=args.bb_position,
            macd_hist_norm=args.macd_hist_norm, consec_candles=args.consec_candles,
            news_sentiment=args.news_sentiment,
            top_n=args.top_n, similarity_threshold=args.threshold,
        )

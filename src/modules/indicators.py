"""Indicadores técnicos: RSI, MACD, Bollinger y señales combinadas."""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

COMBINED_SIGNAL_CONFIDENCE = 0.7
MACD_CROSSOVER_CONFIDENCE = 0.8
BOLLINGER_BREAK_CONFIDENCE = 0.9
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


class TechnicalIndicators:
    """Compute RSI, MACD, Bollinger Bands, and ATR from an OHLCV DataFrame."""

    def __init__(self, config: dict[str, Any] | None) -> None:
        """Read indicator periods/thresholds from ``config`` (or use defaults)."""
        self.config = config or {}
        self.rsi_period = self.config.get("RSI", {}).get("period", 14)
        self.macd_fast = self.config.get("MACD", {}).get("fast_period", 12)
        self.macd_slow = self.config.get("MACD", {}).get("slow_period", 26)
        self.macd_signal = self.config.get("MACD", {}).get("signal_period", 9)
        self.bollinger_period = self.config.get(
            "BOLLINGER", {},
        ).get("period", 20)
        self.bollinger_std = self.config.get(
            "BOLLINGER", {},
        ).get("std_dev", 2.0)

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        try:
            df["rsi"] = ta.rsi(df["close"], length=self.rsi_period)
            macd = ta.macd(
                df["close"],
                fast=self.macd_fast,
                slow=self.macd_slow,
                signal=self.macd_signal,
            )
            if macd is not None:
                df = df.join(macd)
            bb = ta.bbands(
                df["close"],
                length=self.bollinger_period,
                std=self.bollinger_std,
            )
            if bb is not None:
                df = df.join(bb)
        except Exception:
            logger.exception("❌ Error calculando indicadores")
        return df

    def get_macd_signal(self, df: pd.DataFrame) -> tuple[str, float]:
        if df is None or df.empty:
            return "NEUTRAL", 0.0
        try:
            macd_col = next(c for c in df.columns if c.startswith("MACD_"))
            signal_col = next(c for c in df.columns if c.startswith("MACDs_"))
            curr_macd = df[macd_col].iloc[-1]
            curr_sig = df[signal_col].iloc[-1]
            prev_macd = df[macd_col].iloc[-2]
            prev_sig = df[signal_col].iloc[-2]
        except Exception:
            logger.exception("❌ Error en MACD signal")
            return "NEUTRAL", 0.0

        if prev_macd < prev_sig and curr_macd > curr_sig:
            return "BUY", MACD_CROSSOVER_CONFIDENCE
        if prev_macd > prev_sig and curr_macd < curr_sig:
            return "SELL", MACD_CROSSOVER_CONFIDENCE
        return "NEUTRAL", 0.0

    def get_bollinger_signal(self, df: pd.DataFrame) -> tuple[str, float]:
        if df is None or df.empty:
            return "NEUTRAL", 0.0
        try:
            latest = df.iloc[-1]
            close = latest["close"]
            bbl_col = next(
                (c for c in df.columns if c.startswith("BBL")), None,
            )
            bbu_col = next(
                (c for c in df.columns if c.startswith("BBU")), None,
            )
        except Exception:
            logger.exception("❌ Error en Bollinger signal")
            return "NEUTRAL", 0.0

        if bbl_col is not None and close < latest[bbl_col]:
            return "BUY", BOLLINGER_BREAK_CONFIDENCE
        if bbu_col is not None and close > latest[bbu_col]:
            return "SELL", BOLLINGER_BREAK_CONFIDENCE
        return "NEUTRAL", 0.0

    def get_combined_signal(
        self,
        df: pd.DataFrame,
        bollinger_signal: tuple[str, float] | None = None,
    ) -> tuple[str, float]:
        if df is None or df.empty:
            return "NEUTRAL", 0.0
        try:
            rsi = df["rsi"].iloc[-1]
        except Exception:
            logger.exception("❌ Error en combined signal")
            return "NEUTRAL", 0.0

        signals = []
        if rsi < RSI_OVERSOLD:
            signals.append("BUY")
        elif rsi > RSI_OVERBOUGHT:
            signals.append("SELL")

        if bollinger_signal is None:
            bollinger_signal = self.get_bollinger_signal(df)
        bol_sig, _ = bollinger_signal
        if bol_sig != "NEUTRAL":
            signals.append(bol_sig)

        if not signals:
            return "NEUTRAL", 0.0

        buy = signals.count("BUY")
        sell = signals.count("SELL")

        if buy > sell:
            return "BUY", COMBINED_SIGNAL_CONFIDENCE
        if sell > buy:
            return "SELL", COMBINED_SIGNAL_CONFIDENCE
        return "NEUTRAL", 0.0

    def get_indicators_summary(self, df: pd.DataFrame) -> dict:
        if df is None or df.empty:
            return {}
        try:
            return {"rsi": df["rsi"].iloc[-1]}
        except Exception:
            logger.exception("❌ Error en indicators summary")
            return {}

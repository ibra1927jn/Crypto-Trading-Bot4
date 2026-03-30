import logging

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    def __init__(self, config):
        self.config = config if config else {}
        self.rsi_period = self.config.get("RSI", {}).get("period", 14)
        self.macd_fast = self.config.get("MACD", {}).get("fast_period", 12)
        self.macd_slow = self.config.get("MACD", {}).get("slow_period", 26)
        self.macd_signal = self.config.get("MACD", {}).get("signal_period", 9)
        self.bollinger_period = self.config.get("BOLLINGER", {}).get("period", 20)
        self.bollinger_std = self.config.get("BOLLINGER", {}).get("std_dev", 2.0)

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
                df["close"], length=self.bollinger_period, std=self.bollinger_std
            )
            if bb is not None:
                df = df.join(bb)
        except Exception as e:
            logger.error("❌ Error calculando indicadores: %s", e)
        return df

    def get_macd_signal(self, df: pd.DataFrame) -> tuple[str, float]:
        if df is None or df.empty:
            return "NEUTRAL", 0.0
        try:
            macd_col = [c for c in df.columns if c.startswith("MACD_")][0]
            signal_col = [c for c in df.columns if c.startswith("MACDs_")][0]
            curr_macd, curr_sig = df[macd_col].iloc[-1], df[signal_col].iloc[-1]
            prev_macd, prev_sig = df[macd_col].iloc[-2], df[signal_col].iloc[-2]

            if prev_macd < prev_sig and curr_macd > curr_sig:
                return "BUY", 0.8
            elif prev_macd > prev_sig and curr_macd < curr_sig:
                return "SELL", 0.8
            return "NEUTRAL", 0.0
        except Exception as e:
            logger.error("❌ Error en MACD signal: %s", e)
            return "NEUTRAL", 0.0

    def get_bollinger_signal(self, df: pd.DataFrame) -> tuple[str, float]:
        if df is None or df.empty:
            return "NEUTRAL", 0.0
        try:
            latest = df.iloc[-1]
            close = latest["close"]
            bbl = [c for c in df.columns if c.startswith("BBL")]
            bbu = [c for c in df.columns if c.startswith("BBU")]

            if bbl and close < latest[bbl[0]]:
                return "BUY", 0.9
            if bbu and close > latest[bbu[0]]:
                return "SELL", 0.9
            return "NEUTRAL", 0.0
        except Exception as e:
            logger.error("❌ Error en Bollinger signal: %s", e)
            return "NEUTRAL", 0.0

    def get_combined_signal(self, df: pd.DataFrame) -> tuple[str, float]:
        if df is None or df.empty:
            return "NEUTRAL", 0.0
        try:
            signals = []
            rsi = df["rsi"].iloc[-1]
            if rsi < 30:
                signals.append("BUY")
            elif rsi > 70:
                signals.append("SELL")

            bol_sig, _ = self.get_bollinger_signal(df)
            if bol_sig != "NEUTRAL":
                signals.append(bol_sig)

            if not signals:
                return "NEUTRAL", 0.0

            buy = signals.count("BUY")
            sell = signals.count("SELL")

            if buy > sell:
                return "BUY", 0.7
            elif sell > buy:
                return "SELL", 0.7
            return "NEUTRAL", 0.0
        except Exception as e:
            logger.error("❌ Error en combined signal: %s", e)
            return "NEUTRAL", 0.0

    def get_indicators_summary(self, df: pd.DataFrame) -> dict:
        if df is None or df.empty:
            return {}
        try:
            return {"rsi": df["rsi"].iloc[-1]}
        except Exception as e:
            logger.error("❌ Error en indicators summary: %s", e)
            return {}

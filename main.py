#!/usr/bin/env python3
"""Punto de entrada del bot de trading: orquesta exchange, datos y estrategia."""
import asyncio
import contextlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import ccxt.async_support as ccxt
import colorlog
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

MIN_BARS_FOR_SIGNAL = 200

SYMBOLS = [
    s.strip()
    for s in os.getenv("TRADING_SYMBOLS", "BTC/USDT").split(",")
]
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_API_SECRET")

sys.path.insert(0, str(BASE_DIR / "src"))
from modules.ai_predictor import AI_Predictor  # noqa: E402
from modules.data_manager import DataManager  # noqa: E402
from modules.indicators import TechnicalIndicators  # noqa: E402
from strategies.strategy import HybridStrategy  # noqa: E402


def setup_logging() -> logging.Logger:
    """Configure and return the root logger with colored INFO-level output."""
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={"INFO": "green", "WARNING": "yellow", "ERROR": "red"},
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = setup_logging()
logger.info("=" * 50)
logger.info("RADAR IA ACTIVADO")
logger.info("=" * 50)


class CryptoRadar:
    """Scan configured symbols on a fixed interval and emit BUY/SELL/NEUTRAL signals."""

    def __init__(self) -> None:
        """Initialize empty manager registry and read timeframe from env."""
        self.managers = {}
        self.timeframe = os.getenv("TIMEFRAME", "1m")

    async def initialize(self) -> bool:
        """Connect to Binance futures testnet and build per-symbol managers."""
        self.exchange = ccxt.binance({
            "apiKey": API_KEY, "secret": SECRET_KEY, "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        # Parche URLs
        base = "https://testnet.binancefuture.com"
        self.exchange.urls["api"] = dict.fromkeys(
            ["fapiPublic", "fapiPrivate", "public", "private"],
            f"{base}/fapi/v1",
        )
        self.exchange.urls["api"].update({
            "sapi": f"{base}/sapi/v1",
            "dapiPublic": f"{base}/dapi/v1",
            "dapiPrivate": f"{base}/dapi/v1",
        })

        await self.exchange.load_markets()
        logger.info("✅ CONEXIÓN EXITOSA")

        self.indicators = TechnicalIndicators({})
        self.ai_predictor = AI_Predictor({})

        self.strategies = {}
        for sym in SYMBOLS:
            mgr = DataManager(
                self.exchange, sym, self.timeframe,
                historical_bars=300,
            )
            self.managers[sym] = mgr
            self.strategies[sym] = HybridStrategy(
                mgr, self.indicators, self.ai_predictor, {},
            )
        return True

    async def run(self) -> None:
        """Scan loop: call _scan() every 60s, backing off 5s on exceptions."""
        logger.info("🟢 RADAR GIRANDO (%s Pares)...", len(SYMBOLS))
        while True:
            try:
                await self._scan()
                logger.info("⏳ Esperando 60s...")
                await asyncio.sleep(60)
            # PERF203 overhead is negligible vs the 60s sleep body;
            # broad catch keeps the radar alive across transient errors.
            except Exception:  # noqa: BLE001, PERF203
                logger.exception("Error")
                await asyncio.sleep(5)

    async def _scan(self) -> None:
        logger.info(
            "\n📡 --- %s ---",
            datetime.now(tz=timezone.utc).strftime("%H:%M:%S"),
        )
        for symbol in SYMBOLS:
            try:
                mgr = self.managers[symbol]
                await mgr.update_data()
                df = mgr.get_latest_data()
                if df is None or len(df) < MIN_BARS_FOR_SIGNAL:
                    continue

                df = self.indicators.calculate_all(df)
                price = df["close"].iloc[-1]

                signal, _, _ = self.strategies[symbol].get_signal(df)

                if signal.value == "BUY":
                    icon = "🟢"
                elif signal.value == "SELL":
                    icon = "🔴"
                else:
                    icon = "⚪"
                logger.info(
                    "%s %-10s $%-10.2f | Señal: %s",
                    icon, symbol, price, signal.value,
                )
            except Exception:
                logger.exception("Error %s", symbol)


async def _main() -> None:
    radar = CryptoRadar()
    if await radar.initialize():
        await radar.run()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())

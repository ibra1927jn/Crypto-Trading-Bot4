"""
Crypto-Trading-Bot4 — Data Engine v3 (Sniper Rotativo)
======================================================
Vigila MÚLTIPLES monedas simultáneamente via combined WebSocket.
Calcula indicadores para cada moneda independientemente.
"""

import asyncio
import json
from typing import Optional, Callable, Dict
import pandas as pd
import pandas_ta as ta
import websockets

from config.settings import (
    SYMBOLS, TIMEFRAME, WARMUP_CANDLES, BINANCE_WS_BASE,
    ATR_PERIOD, ADX_PERIOD, BB_PERIOD, BB_STD
)
from utils.logger import setup_logger

logger = setup_logger("DATA")

TIMEFRAME_MAP = {
    '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m',
    '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d',
}


class DataEngine:
    """
    Motor de datos multi-moneda: vigila N monedas simultáneamente.
    Mantiene un DataFrame por moneda con indicadores institucionales.
    """

    def __init__(self):
        self.candles: Dict[str, pd.DataFrame] = {}  # {symbol: DataFrame}
        self.current_prices: Dict[str, float] = {}   # {symbol: price}
        self.ws_connected: bool = False
        self._ws = None
        self._on_candle_close: Optional[Callable] = None

    # ==========================================================
    # WARM-UP (descarga historial para TODAS las monedas)
    # ==========================================================

    async def warmup(self, exchange):
        """Descarga velas históricas para cada moneda."""
        logger.info(
            f"🔥 Warm-up: {len(SYMBOLS)} monedas × {WARMUP_CANDLES} velas ({TIMEFRAME})"
        )

        for symbol in SYMBOLS:
            try:
                ohlcv = await exchange.fetch_ohlcv(
                    symbol, TIMEFRAME, limit=WARMUP_CANDLES
                )

                df = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                df.set_index('timestamp', inplace=True)

                self.candles[symbol] = df
                self._calculate_indicators(symbol)
                self.current_prices[symbol] = float(df['close'].iloc[-1])

                last = df.iloc[-2]  # Última vela CERRADA
                logger.info(
                    f"  ✅ {symbol}: {len(df)} velas | "
                    f"${self.current_prices[symbol]:.6f} | "
                    f"RSI7: {self._safe(last, 'RSI_7'):.1f}"
                )
            except Exception as e:
                logger.error(f"  ❌ {symbol}: Error en warm-up: {e}")

        logger.info(f"✅ Warm-up completo: {len(self.candles)} monedas listas")

    # ==========================================================
    # WEBSOCKET MULTI-MONEDA (combined stream)
    # ==========================================================

    async def start_websocket(self):
        """WebSocket combined stream para todas las monedas."""
        tf = TIMEFRAME_MAP.get(TIMEFRAME, '5m')

        # Binance combined stream: stream?streams=xrpusdt@kline_5m/dogeusdt@kline_5m/...
        streams = []
        for symbol in SYMBOLS:
            sym_ws = symbol.replace('/', '').lower()
            streams.append(f"{sym_ws}@kline_{tf}")

        # Combined stream URL
        base = BINANCE_WS_BASE.replace('/ws', '')
        ws_url = f"{base}/stream?streams={'/'.join(streams)}"

        while True:
            try:
                logger.info(f"🔌 Conectando WebSocket multi-coin: {len(SYMBOLS)} monedas")

                async with websockets.connect(
                    ws_url,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    self._ws = ws
                    self.ws_connected = True
                    logger.info(
                        f"✅ WebSocket conectado — {', '.join(SYMBOLS)}"
                    )

                    async for message in ws:
                        await self._process_ws_message(message)

            except websockets.ConnectionClosed as e:
                self.ws_connected = False
                logger.warning(f"⚠️ WebSocket desconectado: {e}. Reconectando en 5s...")
                await asyncio.sleep(5)

            except Exception as e:
                self.ws_connected = False
                logger.error(f"❌ Error WS: {e}. Reconectando en 10s...")
                await asyncio.sleep(10)

    async def _process_ws_message(self, message: str):
        """Procesa mensaje del combined stream (tiene campo 'stream' extra)."""
        try:
            data = json.loads(message)

            # Combined stream wraps data in {stream: "...", data: {...}}
            if 'data' in data:
                stream_name = data.get('stream', '')
                data = data['data']
            
            kline = data.get('k', {})
            if not kline:
                return

            # Identificar el símbolo
            raw_symbol = kline.get('s', '').upper()  # e.g. "XRPUSDT"
            symbol = self._raw_to_symbol(raw_symbol)
            if not symbol or symbol not in self.candles:
                return

            ts = pd.Timestamp(kline['t'], unit='ms', tz='UTC')
            o, h, l, c, v = (
                float(kline['o']), float(kline['h']), float(kline['l']),
                float(kline['c']), float(kline['v'])
            )
            is_closed = kline['x']
            self.current_prices[symbol] = c

            df = self.candles[symbol]

            if is_closed:
                new_row = pd.DataFrame(
                    {'open': [o], 'high': [h], 'low': [l],
                     'close': [c], 'volume': [v]},
                    index=pd.DatetimeIndex([ts], name='timestamp')
                )

                if ts in df.index:
                    df.loc[ts, ['open', 'high', 'low', 'close', 'volume']] = [o, h, l, c, v]
                else:
                    self.candles[symbol] = pd.concat([df, new_row])

                # Buffer circular
                if len(self.candles[symbol]) > WARMUP_CANDLES + 20:
                    self.candles[symbol] = self.candles[symbol].iloc[-WARMUP_CANDLES:]

                self._calculate_indicators(symbol)

                last = self.candles[symbol].iloc[-1]
                logger.debug(
                    f"🕯️ {symbol} cerrada: C={c:.6f} | "
                    f"RSI7={self._safe(last, 'RSI_7'):.1f}"
                )

                if self._on_candle_close:
                    await self._on_candle_close()
            else:
                # Update current candle in-place
                if ts in df.index:
                    df.loc[ts, ['open', 'high', 'low', 'close', 'volume']] = [o, h, l, c, v]

        except Exception as e:
            logger.error(f"Error procesando mensaje WS: {e}")

    def _raw_to_symbol(self, raw: str) -> Optional[str]:
        """Convierte 'XRPUSDT' → 'XRP/USDT'."""
        for symbol in SYMBOLS:
            if symbol.replace('/', '') == raw:
                return symbol
        return None

    def set_on_candle_close(self, callback: Callable):
        self._on_candle_close = callback

    async def stop_websocket(self):
        if self._ws:
            await self._ws.close()
            self.ws_connected = False
            logger.info("WebSocket cerrado.")

    # ==========================================================
    # INDICADORES (por moneda)
    # ==========================================================

    def _calculate_indicators(self, symbol: str):
        """Calcula indicadores para una moneda específica."""
        df = self.candles.get(symbol)
        if df is None or len(df) < 200:
            return

        try:
            # EMA 200
            ema200 = ta.ema(df['close'], length=200)
            if ema200 is not None:
                df['EMA_200'] = ema200

            # EMAs cortas
            for length in [5, 9, 13, 21, 50]:
                ema = ta.ema(df['close'], length=length)
                if ema is not None:
                    df[f'EMA_{length}'] = ema

            # ADX + ATR
            adx_df = ta.adx(df['high'], df['low'], df['close'], length=ADX_PERIOD)
            if adx_df is not None:
                df['ADX_14'] = adx_df[f'ADX_{ADX_PERIOD}']

            atr = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
            if atr is not None:
                df['ATRr_14'] = atr

            # RSI 14 + RSI 7 (el gatillo principal del Sniper)
            rsi14 = ta.rsi(df['close'], length=14)
            if rsi14 is not None:
                df['RSI_14'] = rsi14
            rsi7 = ta.rsi(df['close'], length=7)
            if rsi7 is not None:
                df['RSI_7'] = rsi7

            # Volumen
            df['VOL_SMA_20'] = df['volume'].rolling(window=20).mean()
            vol_sma = df['VOL_SMA_20'].replace(0, 1e-10)
            df['VOL_RATIO'] = df['volume'] / vol_sma

            # Bollinger Bands
            bbands = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
            if bbands is not None:
                bb_cols = bbands.columns.tolist()
                bbl = [c for c in bb_cols if c.startswith('BBL_')]
                bbm = [c for c in bb_cols if c.startswith('BBM_')]
                bbu = [c for c in bb_cols if c.startswith('BBU_')]
                if bbl and bbm and bbu:
                    df['BB_LO'] = bbands[bbl[0]]
                    df['BB_MID'] = bbands[bbm[0]]
                    df['BB_HI'] = bbands[bbu[0]]

            # MACD
            macd_df = ta.macd(df['close'])
            if macd_df is not None:
                mc = [c for c in macd_df.columns if c.startswith('MACD_')]
                ms = [c for c in macd_df.columns if c.startswith('MACDs_')]
                if mc:
                    df['MACD'] = macd_df[mc[0]]
                if ms:
                    df['MACD_S'] = macd_df[ms[0]]

            # Stochastic
            stoch = ta.stoch(df['high'], df['low'], df['close'])
            if stoch is not None:
                sk = [c for c in stoch.columns if 'STOCHk' in c]
                if sk:
                    df['STOCH_K'] = stoch[sk[0]]

        except Exception as e:
            logger.error(f"Error calculando indicadores {symbol}: {e}")

    # ==========================================================
    # GETTERS
    # ==========================================================

    def _safe(self, row, col) -> float:
        val = row.get(col) if isinstance(row, dict) else row[col] if col in row.index else None
        return float(val) if val is not None and pd.notna(val) else 0.0

    def get_dataframe(self, symbol: str = None) -> Optional[pd.DataFrame]:
        """Retorna DataFrame de una moneda (o la primera si no se especifica)."""
        if symbol:
            return self.candles.get(symbol)
        # Compatibilidad: devuelve la primera
        if self.candles:
            return list(self.candles.values())[0]
        return None

    def get_all_dataframes(self) -> Dict[str, pd.DataFrame]:
        """Retorna todos los DataFrames."""
        return self.candles

    def get_market_snapshot(self, symbol: str = None) -> dict:
        """Retorna snapshot de UNA moneda."""
        if symbol is None:
            symbol = SYMBOLS[0] if SYMBOLS else None
        if symbol is None or symbol not in self.candles:
            return {'price': 0, 'ws_connected': self.ws_connected}

        df = self.candles[symbol]
        if len(df) < 2:
            return {'price': self.current_prices.get(symbol, 0), 'ws_connected': self.ws_connected}

        last = df.iloc[-2]  # Última vela CERRADA (anti-repainting)
        return {
            'symbol': symbol,
            'price': self.current_prices.get(symbol, 0),
            'last_close': self._safe(last, 'close'),
            'ema_200': self._safe(last, 'EMA_200'),
            'ema_9': self._safe(last, 'EMA_9'),
            'ema_21': self._safe(last, 'EMA_21'),
            'adx': self._safe(last, 'ADX_14'),
            'rsi': self._safe(last, 'RSI_14'),
            'rsi_7': self._safe(last, 'RSI_7'),
            'atr': self._safe(last, 'ATRr_14'),
            'volume': self._safe(last, 'volume'),
            'vol_sma': self._safe(last, 'VOL_SMA_20'),
            'vol_ratio': self._safe(last, 'VOL_RATIO'),
            'bb_lo': self._safe(last, 'BB_LO'),
            'bb_mid': self._safe(last, 'BB_MID'),
            'macd': self._safe(last, 'MACD'),
            'macd_s': self._safe(last, 'MACD_S'),
            'stoch_k': self._safe(last, 'STOCH_K'),
            'ws_connected': self.ws_connected,
            'candles_count': len(df),
        }

    def get_all_snapshots(self) -> Dict[str, dict]:
        """Retorna snapshot de TODAS las monedas (para el Sniper Rotativo)."""
        return {symbol: self.get_market_snapshot(symbol) for symbol in SYMBOLS}

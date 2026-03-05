"""
Crypto-Trading-Bot4 — Data Engine (Los Ojos)
=============================================
Lee el mercado en tiempo real y calcula indicadores institucionales.

Indicadores:
  - EMA 200: Filtro Macro (la marea general)
  - EMA 9/21: Gatillos de Momentum (crossover)
  - ADX 14: Fuerza de tendencia (filtro anti-rango)
  - ATR 14: Volatilidad real (para SL dinámico)
  - VOL SMA 20: Volumen institucional (filtro de ballenas)
"""

import asyncio
import json
from typing import Optional, Callable
import pandas as pd
import pandas_ta as ta
import websockets

from config.settings import (
    SYMBOL, TIMEFRAME, WARMUP_CANDLES, BINANCE_WS_BASE,
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
    Motor de datos: ojos del bot.
    Mantiene un DataFrame de velas OHLCV + indicadores institucionales.
    """

    def __init__(self):
        self.candles: Optional[pd.DataFrame] = None
        self.current_price: float = 0.0
        self.ws_connected: bool = False
        self._ws = None
        self._on_candle_close: Optional[Callable] = None

    # ==========================================================
    # WARM-UP
    # ==========================================================

    async def warmup(self, exchange):
        """
        Descarga las últimas N velas históricas via REST.
        Mínimo 250 para que la EMA 200 no devuelva NaN.
        """
        logger.info(
            f"🔥 Warm-up: Descargando últimas {WARMUP_CANDLES} velas "
            f"de {SYMBOL} ({TIMEFRAME})..."
        )

        ohlcv = await exchange.fetch_ohlcv(
            SYMBOL, TIMEFRAME, limit=WARMUP_CANDLES
        )

        self.candles = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        self.candles['timestamp'] = pd.to_datetime(
            self.candles['timestamp'], unit='ms', utc=True
        )
        self.candles.set_index('timestamp', inplace=True)

        self._calculate_indicators()
        self.current_price = float(self.candles['close'].iloc[-1])

        # Log con nuevos indicadores
        last = self.candles.iloc[-2]  # Última vela CERRADA
        logger.info(
            f"✅ Warm-up completo: {len(self.candles)} velas | "
            f"Precio: ${self.current_price:.2f} | "
            f"EMA200: {self._safe(last, 'EMA_200'):.2f} | "
            f"ADX: {self._safe(last, 'ADX_14'):.1f} | "
            f"RSI: {self._safe(last, 'RSI_14'):.1f} | "
            f"ATR: {self._safe(last, 'ATRr_14'):.2f}"
        )

    # ==========================================================
    # WEBSOCKET
    # ==========================================================

    async def start_websocket(self):
        """WebSocket con auto-reconnect y anti-zombie (ping_timeout)."""
        symbol_ws = SYMBOL.replace('/', '').lower()
        tf = TIMEFRAME_MAP.get(TIMEFRAME, '5m')
        ws_url = f"{BINANCE_WS_BASE}/{symbol_ws}@kline_{tf}"

        while True:
            try:
                logger.info(f"🔌 Conectando WebSocket: {ws_url}")

                async with websockets.connect(
                    ws_url,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    self._ws = ws
                    self.ws_connected = True
                    logger.info("✅ WebSocket conectado — recibiendo datos en vivo")

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
        """Procesa un mensaje del WebSocket de klines."""
        try:
            data = json.loads(message)
            kline = data.get('k', {})
            if not kline:
                return

            ts = pd.Timestamp(kline['t'], unit='ms', tz='UTC')
            o, h, l, c, v = (
                float(kline['o']), float(kline['h']), float(kline['l']),
                float(kline['c']), float(kline['v'])
            )
            is_closed = kline['x']
            self.current_price = c

            if is_closed:
                new_row = pd.DataFrame(
                    {'open': [o], 'high': [h], 'low': [l],
                     'close': [c], 'volume': [v]},
                    index=pd.DatetimeIndex([ts], name='timestamp')
                )

                if ts in self.candles.index:
                    self.candles.loc[ts, ['open', 'high', 'low', 'close', 'volume']] = [o, h, l, c, v]
                else:
                    self.candles = pd.concat([self.candles, new_row])

                # Buffer circular
                if len(self.candles) > WARMUP_CANDLES + 20:
                    self.candles = self.candles.iloc[-WARMUP_CANDLES:]

                self._calculate_indicators()

                last = self.candles.iloc[-1]
                logger.debug(
                    f"🕯️ Vela cerrada: C={c:.2f} | "
                    f"EMA9={self._safe(last, 'EMA_9'):.2f} | "
                    f"EMA21={self._safe(last, 'EMA_21'):.2f} | "
                    f"ADX={self._safe(last, 'ADX_14'):.1f}"
                )

                if self._on_candle_close:
                    await self._on_candle_close()
            else:
                if ts in self.candles.index:
                    self.candles.loc[ts, ['open', 'high', 'low', 'close', 'volume']] = [o, h, l, c, v]
                else:
                    new_row = pd.DataFrame(
                        {'open': [o], 'high': [h], 'low': [l],
                         'close': [c], 'volume': [v]},
                        index=pd.DatetimeIndex([ts], name='timestamp')
                    )
                    self.candles = pd.concat([self.candles, new_row])

        except Exception as e:
            logger.error(f"Error procesando mensaje WS: {e}")

    def set_on_candle_close(self, callback: Callable):
        self._on_candle_close = callback

    async def stop_websocket(self):
        if self._ws:
            await self._ws.close()
            self.ws_connected = False
            logger.info("WebSocket cerrado.")

    # ==========================================================
    # INDICADORES INSTITUCIONALES
    # ==========================================================

    def _calculate_indicators(self):
        """
        Calcula todos los indicadores institucionales vectorizados.
        pandas-ta usa Numba (JIT → C nativo) para velocidad extrema.
        """
        if self.candles is None or len(self.candles) < 200:
            return  # No hay historia suficiente para la EMA 200

        try:
            df = self.candles

            # 1. Filtro Macro (La Marea general)
            ema200 = ta.ema(df['close'], length=200)
            if ema200 is not None:
                df['EMA_200'] = ema200

            # 1.5. EMAs adicionales (v2: para AllIn RSI + MomBurst)
            ema5 = ta.ema(df['close'], length=5)
            ema13 = ta.ema(df['close'], length=13)
            ema50 = ta.ema(df['close'], length=50)
            if ema5 is not None:
                df['EMA_5'] = ema5
            if ema13 is not None:
                df['EMA_13'] = ema13
            if ema50 is not None:
                df['EMA_50'] = ema50

            # 2. Gatillos de Momentum (Crossover EMA 9/21)
            ema9 = ta.ema(df['close'], length=9)
            ema21 = ta.ema(df['close'], length=21)
            if ema9 is not None:
                df['EMA_9'] = ema9
            if ema21 is not None:
                df['EMA_21'] = ema21

            # 3. Fuerza de tendencia (ADX) + Volatilidad (ATR)
            adx_df = ta.adx(df['high'], df['low'], df['close'], length=ADX_PERIOD)
            if adx_df is not None:
                df['ADX_14'] = adx_df[f'ADX_{ADX_PERIOD}']
                df['DMP_14'] = adx_df[f'DMP_{ADX_PERIOD}']
                df['DMN_14'] = adx_df[f'DMN_{ADX_PERIOD}']

            atr = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
            if atr is not None:
                df['ATRr_14'] = atr

            # 4. RSI — EL NUEVO GATILLO (Buy the Dip)
            rsi = ta.rsi(df['close'], length=14)
            if rsi is not None:
                df['RSI_14'] = rsi

            # 5. Volumen Institucional (SMA 20 periodos)
            df['VOL_SMA_20'] = df['volume'].rolling(window=20).mean()

            # 6. Bollinger Bands (Estrategia Bollinger Bounce)
            bbands = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
            if bbands is not None:
                # Find columns dynamically (pandas_ta naming varies by version)
                bb_cols = bbands.columns.tolist()
                bbl = [c for c in bb_cols if c.startswith('BBL_')]
                bbm = [c for c in bb_cols if c.startswith('BBM_')]
                bbu = [c for c in bb_cols if c.startswith('BBU_')]
                if bbl and bbm and bbu:
                    df['BB_LO'] = bbands[bbl[0]]
                    df['BB_MID'] = bbands[bbm[0]]
                    df['BB_HI'] = bbands[bbu[0]]
                    # BB_PCT: 0.0 = banda inferior, 1.0 = banda superior
                    bb_range = df['BB_HI'] - df['BB_LO']
                    df['BB_PCT'] = (df['close'] - df['BB_LO']) / bb_range.replace(0, 1e-10)

        except Exception as e:
            logger.error(f"Error calculando indicadores vectorizados: {e}")

    # ==========================================================
    # GETTERS
    # ==========================================================

    def _safe(self, row, col) -> float:
        """Extrae valor numérico seguro de una fila del DataFrame."""
        val = row.get(col) if isinstance(row, dict) else row[col] if col in row.index else None
        return float(val) if val is not None and pd.notna(val) else 0.0

    def get_dataframe(self) -> Optional[pd.DataFrame]:
        """Retorna el DataFrame completo con indicadores."""
        return self.candles

    def get_market_snapshot(self) -> dict:
        """Retorna resumen del mercado para logging."""
        if self.candles is None or len(self.candles) < 2:
            return {'price': self.current_price, 'ws_connected': self.ws_connected}

        last = self.candles.iloc[-2]  # Última vela CERRADA
        return {
            'price': self.current_price,
            'last_close': self._safe(last, 'close'),
            'ema_200': self._safe(last, 'EMA_200'),
            'ema_9': self._safe(last, 'EMA_9'),
            'ema_21': self._safe(last, 'EMA_21'),
            'adx': self._safe(last, 'ADX_14'),
            'rsi': self._safe(last, 'RSI_14'),
            'atr': self._safe(last, 'ATRr_14'),
            'volume': self._safe(last, 'volume'),
            'vol_sma': self._safe(last, 'VOL_SMA_20'),
            'bb_pct': self._safe(last, 'BB_PCT'),
            'ws_connected': self.ws_connected,
            'candles_count': len(self.candles),
        }

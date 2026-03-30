import ccxt
import logging
import pandas as pd
import time
import os
from datetime import datetime

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ==========================================
# ⚙️ CONFIGURACIÓN "HIGH DEFINITION"
# ==========================================
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'DOGE/USDT']
TIMEFRAME = '1m'     # <--- CAMBIO CLAVE: Bajamos a 1 minuto (Máxima precisión)
YEARS = 4            # 4 años de 1m son 2 millones de velas (Suficiente para RAM)
OUTPUT_FOLDER = 'data'

# Crear carpeta
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Usamos el cliente de Futuros para tener acceso a datos avanzados
exchange = ccxt.binance({'options': {'defaultType': 'future'}})

logger.info("INICIANDO RECOLECCION HD (Alta Definicion)")
logger.info("Objetivo: %d años de datos minuto a minuto + Funding Rates", YEARS)
logger.info("=" * 70)

for symbol in SYMBOLS:
    logger.info("Procesando %s...", symbol)

    # -------------------------------------------
    # 1. DESCARGA DE PRECIOS (OHLCV 1m)
    # -------------------------------------------
    now = exchange.milliseconds()
    since = now - (YEARS * 365 * 24 * 60 * 60 * 1000)

    all_ohlcv = []
    logger.info("Descargando Velas de 1 minuto...")

    start_time = time.time()
    temp_since = since

    while temp_since < now:
        try:
            dt_str = datetime.fromtimestamp(temp_since/1000).strftime('%Y-%m-%d')
            logger.info("Fecha: %s | Velas: %s", dt_str, f"{len(all_ohlcv):,}")

            ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, temp_since, limit=1000)

            if len(ohlcv) == 0:
                break

            all_ohlcv += ohlcv
            temp_since = ohlcv[-1][0] + 60000  # Sumar 1 minuto
            time.sleep(0.1)  # Pequeña pausa para cuidar la API

        except Exception as e:
            logger.error("Error (Velas): %s", e)
            time.sleep(5)

    # -------------------------------------------
    # 2. DESCARGA DE FUNDING RATES (El Sentimiento)
    # -------------------------------------------
    logger.info("Descargando Funding Rates (Contexto de mercado)...")
    all_funding = []
    temp_since = since

    # El Funding Rate suele ser cada 8 horas, bajamos bloques grandes
    while temp_since < now:
        try:
            # Binance suele dar 1000 registros de funding
            funding = exchange.fetch_funding_rate_history(
                symbol, temp_since, limit=1000
            )

            if len(funding) == 0:
                break

            for f in funding:
                all_funding.append([f['timestamp'], f['fundingRate']])

            temp_since = funding[-1]['timestamp'] + 1
            time.sleep(0.1)

        except Exception as e:
            # Si falla (algunas monedas no tienen tanto historial de funding), seguimos
            logger.warning("Error obteniendo funding rate: %s", e)
            break

    # -------------------------------------------
    # 3. FUSIÓN INTELIGENTE
    # -------------------------------------------
    if len(all_ohlcv) > 0:
        # Crear DataFrame de Precios
        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df_price = pd.DataFrame(all_ohlcv, columns=cols)
        df_price['timestamp'] = pd.to_datetime(df_price['timestamp'], unit='ms')
        df_price.set_index('timestamp', inplace=True)

        # Crear DataFrame de Funding
        if len(all_funding) > 0:
            df_funding = pd.DataFrame(
                all_funding, columns=['timestamp', 'funding_rate']
            )
            df_funding['timestamp'] = pd.to_datetime(df_funding['timestamp'], unit='ms')
            df_funding.set_index('timestamp', inplace=True)

            # Re-muestrear Funding para que coincida con los minutos
            # (rellenar huecos: funding cambia cada 8h)
            df_funding = df_funding.resample('1min').ffill()

            # Unir todo
            df_final = df_price.join(df_funding)
            # Rellenar nulos iniciales
            df_final['funding_rate'] = df_final['funding_rate'].fillna(0)
        else:
            df_final = df_price
            df_final['funding_rate'] = 0.0

        # Guardar
        clean_name = symbol.replace('/', '_')
        filename = f"{OUTPUT_FOLDER}/{clean_name}_1m_HD.csv"
        df_final.reset_index().to_csv(filename, index=False)

        duration = time.time() - start_time
        logger.info("COMPLETADO: %s", symbol)
        logger.info("Archivo: %s", filename)
        logger.info(
            "Datos Totales: %s filas (Tiempo: %.1fs)",
            f"{len(df_final):,}", duration,
        )
    else:
        logger.warning("No se encontraron datos para %s", symbol)

logger.info("=" * 70)
logger.info("BASE DE DATOS HD COMPLETADA")
logger.info("Ahora tu IA tendra vision de Rayos X (1m + Funding)")

"""Módulo de Configuración del Bot de Trading
==========================================
Este módulo gestiona todas las configuraciones del bot, incluyendo:
- Credenciales de exchange
- Parámetros de trading
- Configuración de indicadores técnicos
- Configuración de modelos de IA
"""

import logging
import os
from typing import Any, ClassVar

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()


class Config:
    """Clase de configuración centralizada para el bot de trading"""

    # ===========================
    # CONFIGURACIÓN DEL EXCHANGE
    # ===========================
    EXCHANGE = "binance"
    API_KEY = os.getenv("BINANCE_API_KEY", "")
    API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    TESTNET = os.getenv("USE_TESTNET", "True").lower() == "true"

    # ===========================
    # CONFIGURACIÓN DE TRADING
    # ===========================
    SYMBOL = os.getenv("TRADING_SYMBOL", "BTC/USDT")
    TIMEFRAME = os.getenv("TIMEFRAME", "5m")  # 1m, 5m, 15m, 1h, 4h, 1d

    # Gestión de riesgo
    # Porcentaje del balance
    POSITION_SIZE = float(os.getenv("POSITION_SIZE", "0.01"))
    MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
    STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS", "2.0"))  # 2%
    TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT", "4.0"))  # 4%

    # ===========================
    # CONFIGURACIÓN DE INDICADORES
    # ===========================
    INDICATORS_CONFIG: ClassVar[dict[str, dict[str, Any]]] = {
        "RSI": {
            "period": 14,
            "overbought": 70,
            "oversold": 30,
        },
        "MACD": {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
        },
        "BOLLINGER": {
            "period": 20,
            "std_dev": 2,
        },
    }

    # ===========================
    # CONFIGURACIÓN DE VOLATILIDAD
    # ===========================
    # Umbral de volatilidad para cambiar de estrategia
    VOLATILITY_THRESHOLD = float(os.getenv("VOLATILITY_THRESHOLD", "2.0"))

    # Configuración para estrategia de Scalping (Alta Volatilidad)
    SCALPING_CONFIG: ClassVar[dict[str, Any]] = {
        "check_interval": 5,  # segundos
        "quick_profit_target": 0.5,  # 0.5%
        "quick_stop_loss": 0.3,  # 0.3%
    }

    # Configuración para estrategia de Swing (Baja Volatilidad)
    SWING_CONFIG: ClassVar[dict[str, Any]] = {
        "check_interval": 60,  # segundos
        "use_ai_predictor": True,
        "ai_confidence_threshold": 0.65,  # Confianza mínima del modelo
    }

    # ===========================
    # CONFIGURACIÓN DE IA/ML
    # ===========================
    AI_CONFIG: ClassVar[dict[str, Any]] = {
        # pytorch o tensorflow
        "model_type": os.getenv("AI_MODEL_TYPE", "pytorch"),
        "model_path": os.getenv(
            "AI_MODEL_PATH", "./models/trading_model.pth",
        ),
        "device": (
            "cuda"
            if os.getenv("USE_GPU", "True").lower() == "true"
            else "cpu"
        ),
        "input_features": 50,  # Número de características de entrada
        "sequence_length": 60,  # Ventana de datos históricos
        "batch_size": 32,
    }

    # ===========================
    # CONFIGURACIÓN DE DATOS
    # ===========================
    DATA_CONFIG: ClassVar[dict[str, Any]] = {
        "historical_bars": 500,  # Cantidad de velas históricas a descargar
        "update_interval": 60,  # Actualizar datos cada 60 segundos
        "cache_enabled": True,
    }

    # ===========================
    # CONFIGURACIÓN DE LOGGING
    # ===========================
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "./logs/trading_bot.log")

    @classmethod
    def get_exchange_config(cls) -> dict[str, Any]:
        """Retorna la configuración del exchange en formato dict"""
        config = {
            "apiKey": cls.API_KEY,
            "secret": cls.API_SECRET,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",  # spot, future, margin
            },
        }

        # Testnet Binance: URLs específicas de futures
        if cls.TESTNET and cls.EXCHANGE == "binance":
            config["urls"] = {
                "api": {
                    "public": "https://testnet.binancefuture.com/fapi/v1",
                    "private": "https://testnet.binancefuture.com/fapi/v1",
                },
            }

        return config

    @classmethod
    def validate_config(cls) -> bool:
        """Valida que la configuración sea correcta"""
        if not cls.API_KEY or not cls.API_SECRET:
            logger.warning(
                "API credentials not found! "
                "Set BINANCE_API_KEY and BINANCE_API_SECRET in .env file",
            )
            return False

        if cls.TESTNET:
            logger.info("Running in TESTNET mode")
        else:
            logger.warning("Running in PRODUCTION mode - Real money at risk!")

        return True

    @classmethod
    def print_config(cls) -> None:
        """Imprime la configuración actual (sin mostrar credenciales)"""
        logger.info("CRYPTO TRADING BOT - CONFIGURATION")
        logger.info("Exchange:          %s", cls.EXCHANGE)
        mode = "TESTNET" if cls.TESTNET else "PRODUCTION"
        logger.info("Mode:              %s", mode)
        logger.info("Symbol:            %s", cls.SYMBOL)
        logger.info("Timeframe:         %s", cls.TIMEFRAME)
        logger.info("Position Size:     %s%%", cls.POSITION_SIZE * 100)
        logger.info("Stop Loss:         %s%%", cls.STOP_LOSS_PERCENT)
        logger.info("Take Profit:       %s%%", cls.TAKE_PROFIT_PERCENT)
        logger.info("Volatility Threshold: %s", cls.VOLATILITY_THRESHOLD)
        logger.info("AI Device:         %s", cls.AI_CONFIG["device"])
        logger.info("AI Model Type:     %s", cls.AI_CONFIG["model_type"])


if __name__ == "__main__":
    # Test de configuración
    Config.print_config()
    Config.validate_config()

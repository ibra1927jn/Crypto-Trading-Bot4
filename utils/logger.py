"""
Crypto-Trading-Bot4 — Sistema de Logging
=========================================
Logger dual: consola (INFO+) + archivo (DEBUG+).
Cada motor tiene su propio nombre para rastrear quién dijo qué.

Uso:
    from utils.logger import setup_logger
    logger = setup_logger("EXEC")
    logger.info("Orden ejecutada exitosamente")
"""

import logging
import sys
import os
from config.settings import LOG_DIR


def setup_logger(name: str) -> logging.Logger:
    """
    Configura un logger dual (Consola + Archivo) para un motor específico.
    
    Args:
        name: Identificador del motor (EXEC, DATA, RISK, ALPHA, MAIN, DB)
    
    Returns:
        Logger configurado y listo para usar
    """
    # Asegurar que la carpeta logs existe
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Evitar duplicar handlers si se llama varias veces
    if logger.hasHandlers():
        return logger

    # Formato: [2026-02-27 23:05:00] [EXEC] INFO: Orden enviada
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(name)-5s] %(levelname)-8s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Consola — Solo INFO+ para no saturar la pantalla
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # 2. Archivo — Guarda TODO (DEBUG) para auditorías post-mortem
    log_file = os.path.join(LOG_DIR, "bot.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

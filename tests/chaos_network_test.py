"""
Crypto-Trading-Bot4 — Chaos Test: Simulación de Corte de Red
=============================================================
Este script simula un corte de WiFi/red bloqueando temporalmente
las conexiones a Binance via Windows Firewall.

Flujo:
  1. Arranca el bot normalmente
  2. Espera 30s a que se estabilice (WS conectado)
  3. BLOQUEA testnet.binance.vision via firewall (simula corte de WiFi)
  4. Observa los logs: backoff exponencial + errores de red
  5. Espera 30s con la red "cortada"
  6. RESTAURA la conexión (quita la regla del firewall)
  7. Observa: el bot debe reconectar automáticamente

REQUIERE ejecutar como Administrador (firewall rules).
"""

import asyncio
import subprocess
import sys
import os

# Añadir el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger

logger = setup_logger("CHAOS")

BINANCE_HOSTS = [
    "testnet.binance.vision",
    "stream.testnet.binance.vision",
]

FIREWALL_RULE_NAME = "CHAOS_TEST_BLOCK_BINANCE"


def block_network():
    """Bloquea conexiones a Binance via Windows Firewall."""
    logger.critical("🔥🔥🔥 CORTANDO RED A BINANCE 🔥🔥🔥")
    
    for host in BINANCE_HOSTS:
        # Resolver IP del host
        try:
            result = subprocess.run(
                ["nslookup", host],
                capture_output=True, text=True, timeout=5
            )
            # Extraer IPs del output
            lines = result.stdout.split('\n')
            ips = []
            for line in lines:
                line = line.strip()
                if line.startswith("Address:") or line.startswith("Addresses:"):
                    ip = line.split(":")[-1].strip()
                    if ip and not ip.startswith("192.168") and "." in ip:
                        ips.append(ip)
            
            for ip in ips:
                cmd = (
                    f'netsh advfirewall firewall add rule '
                    f'name="{FIREWALL_RULE_NAME}" '
                    f'dir=out action=block '
                    f'remoteip={ip} '
                    f'protocol=any'
                )
                subprocess.run(cmd, shell=True, capture_output=True)
                logger.warning(f"   ❌ Bloqueado: {host} ({ip})")
        
        except Exception as e:
            logger.error(f"Error bloqueando {host}: {e}")


def restore_network():
    """Restaura las conexiones eliminando las reglas del firewall."""
    logger.critical("✅✅✅ RESTAURANDO RED 🌐✅✅✅")
    
    cmd = (
        f'netsh advfirewall firewall delete rule '
        f'name="{FIREWALL_RULE_NAME}"'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if "Ok" in result.stdout or result.returncode == 0:
        logger.info("   ✅ Reglas de firewall eliminadas. Red restaurada.")
    else:
        logger.warning(f"   ⚠️ Resultado: {result.stdout} {result.stderr}")


async def run_chaos_test():
    """Ejecuta el test completo de corte de red."""
    from db.database import init_db
    from engines.execution_engine import ExecutionEngine
    from engines.data_engine import DataEngine
    from config.settings import SYMBOL

    logger.info("=" * 60)
    logger.info("🧪 CHAOS TEST: Simulación de Corte de Red")
    logger.info("=" * 60)
    
    # 1. INICIALIZAR
    logger.info("📦 Fase 1: Inicializando bot...")
    await init_db()
    
    exec_engine = ExecutionEngine()
    data_engine = DataEngine()
    
    await exec_engine.connect()
    wake_up = await exec_engine.wake_up_sequence()
    logger.info(f"   Balance: {wake_up['usdt_free']:.2f} USDT")
    
    await data_engine.warmup(exec_engine.exchange)
    
    # 2. CONECTAR WEBSOCKET
    logger.info("📡 Fase 2: Conectando WebSocket...")
    ws_task = asyncio.create_task(data_engine.start_websocket())
    
    # Esperar a que se estabilice
    logger.info("⏳ Esperando 15s para estabilización...")
    await asyncio.sleep(15)
    
    ws_status = "✅ CONECTADO" if data_engine.ws_connected else "❌ DESCONECTADO"
    logger.info(f"   WebSocket: {ws_status}")
    
    # 3. CORTAR RED
    logger.info("=" * 60)
    logger.info("🧪 Fase 3: CORTANDO RED (simula corte de WiFi)")
    logger.info("=" * 60)
    block_network()
    
    # 4. OBSERVAR DURANTE 30s (backoff + errores)
    logger.info("⏳ Observando comportamiento durante 30s con red cortada...")
    for i in range(6):
        await asyncio.sleep(5)
        ws_status = "✅ CONECTADO" if data_engine.ws_connected else "❌ DESCONECTADO"
        logger.info(f"   [{(i+1)*5}s] WebSocket: {ws_status} | Precio: ${data_engine.current_price:.2f}")
    
    # 5. RESTAURAR RED
    logger.info("=" * 60)
    logger.info("🧪 Fase 4: RESTAURANDO RED")
    logger.info("=" * 60)
    restore_network()
    
    # 6. ESPERAR RECONEXIÓN
    logger.info("⏳ Esperando reconexión automática (máx 30s)...")
    reconnected = False
    for i in range(12):
        await asyncio.sleep(5)
        if data_engine.ws_connected:
            logger.info(f"   ✅ ¡RECONECTADO en {(i+1)*5}s!")
            reconnected = True
            break
        else:
            logger.info(f"   [{(i+1)*5}s] Esperando reconexión...")
    
    # 7. RESULTADO
    logger.info("=" * 60)
    if reconnected:
        logger.info("🏆 CHAOS TEST: ✅ PASADO — El bot se recuperó del corte de red")
        
        # Verificar que los datos siguen fluyendo
        price_before = data_engine.current_price
        await asyncio.sleep(5)
        price_after = data_engine.current_price
        
        if price_after != price_before:
            logger.info(f"   📈 Datos fluyendo: ${price_before:.2f} → ${price_after:.2f}")
        else:
            logger.info(f"   📊 Precio estable: ${price_after:.2f}")
    else:
        logger.warning("🔴 CHAOS TEST: ⚠️ No reconectó en 60s (puede necesitar más tiempo)")
    
    logger.info("=" * 60)
    
    # Limpieza
    ws_task.cancel()
    try:
        await ws_task
    except asyncio.CancelledError:
        pass
    await exec_engine.disconnect()
    
    # Asegurar limpieza del firewall
    restore_network()
    logger.info("🧹 Limpieza completa. Chaos test finalizado.")


if __name__ == "__main__":
    try:
        asyncio.run(run_chaos_test())
    except KeyboardInterrupt:
        restore_network()
        logger.info("🛑 Test cancelado. Firewall limpiado.")
    except Exception as e:
        restore_network()
        logger.critical(f"💀 Error fatal: {e}", exc_info=True)

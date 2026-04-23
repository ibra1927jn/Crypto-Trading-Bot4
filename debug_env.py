import os

from dotenv import load_dotenv

# 1. Intentar cargar el archivo
print("🔍 Buscando archivo .env...")
se_cargo = load_dotenv()

if se_cargo:
    print("✅ ¡Archivo encontrado!")
else:
    print("❌ ERROR: No se encuentra el archivo .env")

# 2. Leer la clave (solo primeros 4 chars por seguridad)
api_key = os.getenv("BINANCE_API_KEY")

if api_key:
    print(f"🔑 Clave detectada: {api_key[:4]}... (El resto es secreto)")
    print("🚀 ¡TODO LISTO! Ejecuta main.py")
else:
    print(
        "⚠️  El archivo existe, pero "
        "'BINANCE_API_KEY' está vacía.",
    )
    print("👉 Abre el archivo .env y asegúrate de GUARDARLO (Ctrl + S)")

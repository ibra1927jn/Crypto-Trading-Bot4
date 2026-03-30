import ccxt
import pandas_ta as ta
import torch

print("\n" + "=" * 50)
print("🚀 DIAGNÓSTICO FINAL DEL SISTEMA")
print("=" * 50)

# 1. Verificación de GPU (RTX 5080)
print("\n🧠 MOTOR DE IA (PyTorch):")
if torch.cuda.is_available():
    print(f"   ✅ DETECTADO: {torch.cuda.get_device_name(0)}")
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"   ✅ VRAM: {vram_gb:.2f} GB")
    print("   -> ¡Tu Ferrari está listo para correr! 🏎️")
else:
    print("   ❌ ERROR: No se detecta la GPU. Se usará CPU (Lento).")

# 2. Verificación de Librerías
print("\n📚 LIBRERÍAS DE TRADING:")
if ta.version:
    print(f"   ✅ Pandas-TA (Matemáticas): INSTALADO ({ta.version})")
else:
    print("   ❌ Pandas-TA: ERROR")

if ccxt.__version__:
    print(f"   ✅ CCXT (Conexión Binance): INSTALADO ({ccxt.__version__})")
else:
    print("   ❌ CCXT: ERROR")

print("\n" + "=" * 50 + "\n")

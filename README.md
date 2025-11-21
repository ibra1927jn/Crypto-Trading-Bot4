# 🤖 Crypto Trading Bot con Machine Learning

Bot de trading de criptomonedas avanzado con arquitectura modular preparado para integrar modelos de Machine Learning locales. Optimizado para aprovechar GPUs potentes (RTX 5080) y ejecutarse de forma asíncrona.

## ✨ Características Principales

### 🏗️ Arquitectura Modular
- **Diseño escalable**: Módulos independientes y fácilmente extensibles
- **Separación de responsabilidades**: Datos, indicadores, IA y estrategias separadas
- **Código limpio**: Bien documentado y siguiendo mejores prácticas

### 📊 Gestión de Datos
- Conexión a **Binance** via CCXT
- Descarga automática de datos históricos
- Actualización en tiempo real
- Cálculo de volatilidad del mercado

### 📈 Indicadores Técnicos
Implementados con **pandas-ta**:
- **RSI** (Relative Strength Index)
- **MACD** (Moving Average Convergence Divergence)
- **Bandas de Bollinger**
- **EMAs** (Medias Móviles Exponenciales)
- **ATR** (Average True Range)

### 🧠 Módulo de IA
Preparado para modelos de **PyTorch** y **TensorFlow**:
- Soporte para GPU (CUDA)
- Clase `AI_Predictor` lista para integrar modelos
- Actualmente en modo PLACEHOLDER con predicciones aleatorias
- Infraestructura completa para cargar modelos reales

### 🎯 Estrategia Híbrida Adaptativa

El bot cambia automáticamente de estrategia según las condiciones del mercado:

| Condición | Estrategia | Características |
|-----------|------------|-----------------|
| **Alta Volatilidad** | **Scalping** | ⚡ Decisiones rápidas con indicadores técnicos |
| **Baja Volatilidad** | **Swing Trading** | 🎯 Decisiones informadas con predicciones de IA |

### ⚙️ Tecnologías Utilizadas

- **Python 3.8+**
- **asyncio**: Ejecución asíncrona de alta performance
- **CCXT**: Conexión con exchanges
- **pandas**: Manipulación de datos
- **pandas-ta**: Indicadores técnicos
- **PyTorch**: Framework de Deep Learning (opcional)
- **TensorFlow**: Framework de Deep Learning (opcional)
- **colorlog**: Logging con colores

## 📁 Estructura del Proyecto

```
Crypto-Trading-Bot4/
├── main.py                          # Punto de entrada del bot
├── requirements.txt                 # Dependencias del proyecto
├── .env.example                    # Plantilla de variables de entorno
├── README.md                       # Este archivo
│
├── src/
│   ├── config.py                   # Configuración centralizada
│   │
│   ├── modules/
│   │   ├── data_manager.py        # Gestión de datos del mercado
│   │   ├── indicators.py          # Indicadores técnicos
│   │   └── ai_predictor.py        # Predictor de IA (ML)
│   │
│   ├── strategies/
│   │   └── strategy.py            # Estrategias híbridas
│   │
│   └── utils/
│       └── (utilidades futuras)
│
├── models/                         # Modelos de ML entrenados
│   └── trading_model.pth          # (añadir tus modelos aquí)
│
├── logs/                          # Logs del bot
│   └── trading_bot.log
│
└── tests/                         # Tests unitarios
    └── (tests futuros)
```

## 🚀 Instalación

### 1. Clonar el Repositorio

```bash
git clone https://github.com/tuusuario/Crypto-Trading-Bot4.git
cd Crypto-Trading-Bot4
```

### 2. Crear Entorno Virtual

```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

### 3. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 4. Instalar PyTorch con Soporte CUDA (Para RTX 5080)

Si quieres aprovechar tu GPU para modelos de ML:

```bash
# PyTorch con CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

Verifica la instalación:
```bash
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

### 5. Configurar Variables de Entorno

Copia el archivo de ejemplo y edítalo con tus credenciales:

```bash
cp .env.example .env
nano .env  # O tu editor favorito
```

## ⚙️ Configuración

### Variables de Entorno (.env)

```env
# Exchange Configuration
BINANCE_API_KEY=tu_api_key_aqui
BINANCE_API_SECRET=tu_api_secret_aqui
USE_TESTNET=True

# Trading Configuration
TRADING_SYMBOL=BTC/USDT
TIMEFRAME=5m
POSITION_SIZE=0.01
MAX_POSITIONS=3
STOP_LOSS=2.0
TAKE_PROFIT=4.0

# Volatility & Strategy
VOLATILITY_THRESHOLD=2.0

# AI Configuration
AI_MODEL_TYPE=pytorch
AI_MODEL_PATH=./models/trading_model.pth
USE_GPU=True

# Logging
LOG_LEVEL=INFO
```

### Configuración Avanzada

Edita `src/config.py` para ajustes más específicos:
- Parámetros de indicadores técnicos
- Configuración de estrategias Scalping/Swing
- Configuración del modelo de IA

## 🎮 Uso

### Ejecución Básica

```bash
python main.py
```

### Modo Testnet (Recomendado para pruebas)

Asegúrate de tener `USE_TESTNET=True` en tu `.env`:

```bash
python main.py
```

### Modo Producción (¡Dinero real!)

⚠️ **ADVERTENCIA**: Esto operará con dinero real.

1. Cambia `USE_TESTNET=False` en `.env`
2. Verifica tu configuración de gestión de riesgo
3. Ejecuta el bot:

```bash
python main.py
```

### Detener el Bot

Presiona `Ctrl+C` para detener el bot de forma segura.

## 🧠 Integrar tu Modelo de IA

El bot está **100% preparado** para integrar tus modelos de ML. Aquí te explico cómo:

### 1. Entrenar tu Modelo

Entrena tu modelo de predicción de precios usando PyTorch o TensorFlow. Ejemplo de arquitectura:

**PyTorch (LSTM)**:
```python
import torch.nn as nn

class TradingLSTM(nn.Module):
    def __init__(self, input_size=50, hidden_size=128, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, 2)  # [predicción, confianza]

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        return self.fc(lstm_out[:, -1, :])
```

### 2. Guardar tu Modelo

```python
# PyTorch
torch.save(model.state_dict(), './models/trading_model.pth')

# TensorFlow
model.save('./models/trading_model')
```

### 3. Configurar el Bot

Edita `.env`:
```env
AI_MODEL_TYPE=pytorch  # o tensorflow
AI_MODEL_PATH=./models/trading_model.pth
USE_GPU=True
```

### 4. Modificar ai_predictor.py

Descomenta y adapta las funciones:
- `_load_pytorch_model()` o `_load_tensorflow_model()`
- `_pytorch_predict()` o `_tensorflow_predict()`

El bot automáticamente usará tu modelo en lugar de las predicciones aleatorias.

## 📊 Estrategias

### Scalping (Alta Volatilidad)

Activada cuando: `volatilidad > umbral (default: 2%)`

- ⚡ Chequeos frecuentes (cada 5 segundos)
- 📈 Decisiones basadas en indicadores técnicos
- 🎯 Objetivos de ganancia pequeños pero rápidos

### Swing (Baja Volatilidad)

Activada cuando: `volatilidad ≤ umbral`

- 🎯 Chequeos menos frecuentes (cada 60 segundos)
- 🧠 Combina indicadores con predicciones de IA
- 💎 Busca movimientos más grandes y seguros

## 🛡️ Gestión de Riesgo

El bot incluye múltiples capas de protección:

- **Stop Loss**: Cierre automático en pérdidas
- **Take Profit**: Cierre automático en ganancias
- **Límite de posiciones**: Máximo de posiciones abiertas
- **Tamaño de posición**: Porcentaje del balance por operación
- **Confianza mínima**: No opera sin suficiente confianza en la señal

## 📝 Logs

El bot genera logs detallados con colores:

- 🟢 **INFO**: Operaciones normales
- 🟡 **WARNING**: Advertencias
- 🔴 **ERROR**: Errores
- 🔵 **DEBUG**: Información detallada (activar con `LOG_LEVEL=DEBUG`)

Los logs se guardan en `logs/trading_bot.log`

## 🧪 Testing

```bash
# Instalar dependencias de testing
pip install pytest pytest-asyncio

# Ejecutar tests
pytest tests/
```

## 🔮 Roadmap

- [ ] Implementar más estrategias (DCA, Grid Trading)
- [ ] Panel web de monitoreo en tiempo real
- [ ] Backtesting automatizado
- [ ] Notificaciones (Telegram, Discord, Email)
- [ ] Multi-exchange support
- [ ] Base de datos para histórico de operaciones
- [ ] Paper trading mode completo
- [ ] Auto-entrenamiento del modelo de IA

## ⚠️ Disclaimer

**IMPORTANTE**:
- Este bot es solo para fines educativos y de investigación
- El trading de criptomonedas conlleva riesgos significativos
- Puedes perder todo tu capital
- No somos responsables de pérdidas financieras
- Siempre prueba en TESTNET antes de usar dinero real
- No inviertas más de lo que puedes permitirte perder

## 📄 Licencia

MIT License - Ver archivo LICENSE para más detalles

## 🤝 Contribuir

Las contribuciones son bienvenidas:

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📧 Contacto

Para preguntas, sugerencias o reportar bugs, abre un issue en GitHub.

---

⭐ Si te gusta este proyecto, dale una estrella en GitHub!

🚀 Happy Trading! (Pero con responsabilidad)

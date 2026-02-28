# Crypto-Trading-Bot4

> Bot de trading algorítmico para criptomonedas con arquitectura de 4 motores desacoplados.

## 🏗️ Arquitectura

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ Data Engine │ -> │Alpha Engine │ -> │ Risk Engine │ -> │  Execution  │
│  (Los Ojos) │    │ (El Cerebro)│    │ (El Escudo) │    │ (Los Puños) │
│  WebSocket  │    │   Señales   │    │  Kill Switch│    │  CCXT + OCO │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

## ⚡ Quick Start

```bash
python -m venv venv
.\venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env           # Rellenar con API keys de Binance Testnet
python main.py
```

## 📁 Estructura

```
├── config/settings.py     # Configuración centralizada
├── db/database.py         # SQLite async (WAL mode)
├── engines/
│   ├── data_engine.py     # WebSocket + indicadores
│   ├── alpha_engine.py    # Generador de señales
│   ├── risk_engine.py     # Position sizing + Kill Switch
│   └── execution_engine.py # Órdenes OCO + wake-up
├── utils/logger.py        # Logging dual (consola + archivo)
├── tests/                 # Tests automatizados
└── main.py                # Orquestador asyncio
```

## 🛡️ Principios de Diseño

- **Hard Stop Loss**: Los SL/TP viven en el exchange (OCO), no en Python
- **WAL Mode**: SQLite soporta escrituras concurrentes sin locks
- **Wake-up Sequence**: Al arrancar, reconcilia estado local vs exchange
- **Kill Switch**: Apagado automático si drawdown > 5% o 5+ errores API
- **Warm-up**: Carga 100 velas históricas antes de abrir WebSocket

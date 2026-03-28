"""
Crypto-Trading-Bot4 — API Server (Ojo de Dios)
===============================================
FastAPI ultraligero que expone el cerebro del bot en vivo.
Lee directamente de la RAM de los motores (microsegundos).
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.responses import Response, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime, timezone
import json
import os
import numpy as np

from config.settings import SYMBOLS

# --- Middleware de autenticacion por API key ---
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

# Rutas que no requieren autenticacion
_PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Valida X-API-Key header en todas las rutas excepto las publicas."""

    async def dispatch(self, request: Request, call_next):
        # Si no hay key configurada, dejar pasar todo (dev mode)
        if not DASHBOARD_API_KEY:
            return await call_next(request)

        # Rutas publicas no requieren auth
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        # Verificar header
        provided_key = request.headers.get("X-API-Key", "")
        if provided_key != DASHBOARD_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing API key"},
            )

        return await call_next(request)


class NumpySafeEncoder(json.JSONEncoder):
    """JSON encoder que convierte numpy types a Python nativo."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


app = FastAPI(title="Crypto-Trading-Bot4 Dashboard")
app.add_middleware(ApiKeyMiddleware)

# Referencia global a los motores (se inyecta desde main.py)
_bot = None


def set_bot_reference(bot):
    """Inyecta la referencia al bot para leer su estado."""
    global _bot
    _bot = bot


@app.get("/api/health")
async def health_check():
    """Endpoint publico: ping basico sin autenticacion."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
async def get_status():
    """Endpoint principal: devuelve el estado completo del bot."""
    if not _bot:
        return {"error": "Bot not initialized"}

    # Datos del Data Engine (RAM directa)
    market = _bot.data_engine.get_market_snapshot()
    df = _bot.data_engine.get_dataframe()

    # Estado de las 4 leyes
    laws = _get_laws_status(df)

    # Posiciones abiertas
    from db.database import get_open_positions, get_trade_history
    from config.settings import SYMBOL
    positions = await get_open_positions(SYMBOL)
    history = await get_trade_history(limit=10)

    # Equity total
    equity = await _calculate_equity()

    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "running": _bot.running,
        "market": market,
        "laws": laws,
        "risk": {
            "kill_switch": _bot.risk_engine.kill_switch_active,
            "kill_reason": _bot.risk_engine.kill_reason,
            "starting_balance": float(_bot.risk_engine.starting_balance),
            "current_equity": float(equity.get('total_equity', 0)),
            "usdt_free": float(equity.get('usdt_free', 0)),
            "btc_total": float(equity.get('btc_total', 0)),
            "btc_value_usdt": float(equity.get('btc_value', 0)),
            "drawdown_pct": float(equity.get('drawdown_pct', 0)),
        },
        "alpha": {
            "evaluations": _bot.alpha_engine.evaluations,
            "signals_emitted": _bot.alpha_engine.signals_emitted,
        },
        "execution": {
            "consecutive_errors": _bot.execution_engine.consecutive_errors,
        },
        "positions": positions if positions else [],
        "history": history if history else [],
    }

    # Use NumpySafeEncoder to handle numpy types from pandas
    return Response(
        content=json.dumps(data, cls=NumpySafeEncoder),
        media_type="application/json"
    )


def _get_laws_status(df):
    """Evalúa el estado de las 4 leyes sin disparar."""
    if df is None or len(df) < 200 or 'EMA_200' not in df.columns:
        return {"ready": False, "laws": []}

    import pandas as pd
    closed = df.iloc[-2]
    prev = df.iloc[-3]

    if pd.isna(closed.get('EMA_200')):
        return {"ready": False, "laws": []}

    macro = closed['close'] > closed['EMA_200']
    adx_val = closed.get('ADX_14', 0)
    if pd.isna(adx_val):
        adx_val = 0
    strong = adx_val > 20
    vol = closed['volume'] > closed.get('VOL_SMA_20', 0)
    
    rsi_prev = prev.get('RSI_14', 50)
    rsi_now = closed.get('RSI_14', 50)
    if pd.isna(rsi_prev):
        rsi_prev = 50
    if pd.isna(rsi_now):
        rsi_now = 50
    rsi_pullback = (rsi_prev < 35) and (rsi_now > rsi_prev)

    return {
        "ready": True,
        "all_green": macro and strong and vol and rsi_pullback,
        "laws": [
            {"name": "La Marea", "description": f"Precio > EMA200", "active": bool(macro),
             "detail": f"${closed['close']:.2f} {'>' if macro else '<'} ${closed['EMA_200']:.2f}"},
            {"name": "La Fuerza", "description": f"ADX > 20", "active": bool(strong),
             "detail": f"ADX = {adx_val:.1f}"},
            {"name": "Las Ballenas", "description": "Vol > SMA20", "active": bool(vol),
             "detail": f"Vol = {closed['volume']:.0f}"},
            {"name": "El Pullback", "description": "RSI < 35 + Rebote", "active": bool(rsi_pullback),
             "detail": f"RSI={rsi_now:.1f} (prev={rsi_prev:.1f})"},
        ]
    }


async def _calculate_equity():
    """Calcula Total Equity = USDT + BTC * precio spot."""
    if not _bot or not _bot.execution_engine.exchange:
        return {}

    try:
        balance = await _bot.execution_engine.get_balance()
        # Calcular valor total de todos los activos base monitoreados
        usdt_free = balance.get('USDT_free', 0)
        usdt_total = balance.get('USDT_total', 0)
        base_total = balance.get('base_total', 0)
        base_symbol = balance.get('base_symbol', '')
        # Obtener precio del activo base desde current_prices (dict multi-coin)
        from config.settings import SYMBOL
        price = _bot.data_engine.current_prices.get(SYMBOL, 0)
        base_value = base_total * price
        total_equity = usdt_total + base_value

        starting = _bot.risk_engine.starting_balance
        drawdown = (starting - total_equity) / starting if starting > 0 else 0

        return {
            'usdt_free': usdt_free,
            'usdt_total': usdt_total,
            'btc_total': base_total,
            'btc_value': base_value,
            'total_equity': total_equity,
            'drawdown_pct': max(0, drawdown),
        }
    except Exception:
        return {}


# Sirve los archivos estáticos del frontend
web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")


@app.get("/")
async def serve_dashboard():
    """Sirve el dashboard HTML."""
    index_path = os.path.join(web_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "Dashboard not found"}


@app.post("/api/backtest")
async def run_backtest(params: dict = None):
    """
    Ejecuta backtest integrado.
    POST body: {"coins": ["XRP","DOGE"], "days": 30, "sl": 3, "tp": 5, "rsi": 30, "sweep": false}
    """
    from engines.backtest_engine import BacktestEngine

    params = params or {}
    coins = params.get('coins', [c.split('/')[0] for c in SYMBOLS])
    coins = [f"{c}/USDT" if '/' not in c else c for c in coins]
    days = params.get('days', 30)
    capital = params.get('capital', 30.0)
    do_sweep = params.get('sweep', False)

    bt = BacktestEngine(initial_balance=capital)
    data = bt.fetch_data(coins, timeframe='1h', days=days)

    if not data:
        return {"error": "No data downloaded"}

    if do_sweep:
        results = bt.sweep(data)
        return Response(
            content=json.dumps([{
                'label': r['label'], 'pnl': r['pnl'], 'trades': r['trades'],
                'wr': r['wr'], 'max_dd': r['max_dd'], 'daily_pnl': r['daily_pnl'],
            } for r in results], cls=NumpySafeEncoder),
            media_type="application/json"
        )
    else:
        m = bt.run(data,
                   rsi_entry=params.get('rsi'),
                   sl_pct=params.get('sl'),
                   tp_pct=params.get('tp'),
                   verbose=False)
        # Remove non-serializable fields
        m.pop('equity_curve', None)
        m.pop('trades_list', None)
        return Response(
            content=json.dumps(m, cls=NumpySafeEncoder, default=str),
            media_type="application/json"
        )

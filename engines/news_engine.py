"""
Crypto-Trading-Bot4 — News Engine (Datos Externos)
====================================================
Integra datos externos al scoring del Alpha Engine:
  1. CryptoPanic API → Noticias cripto en tiempo real (gratis)
  2. Fear & Greed Index → Sentimiento general del mercado (gratis)

Score: 0-20 puntos adicionales al Alpha Engine.
"""

import asyncio
import aiohttp
import time
from datetime import datetime, timezone
from typing import Dict, Optional, List
from utils.logger import setup_logger

logger = setup_logger("NEWS")

# ═══════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
CRYPTOPANIC_URL = "https://cryptopanic.com/api/free/v1/posts/"

# Mapeo de símbolos del bot → símbolos de CryptoPanic
COIN_MAP = {
    'XRP/USDT': 'XRP',
    'DOGE/USDT': 'DOGE',
    'AVAX/USDT': 'AVAX',
    'SHIB/USDT': 'SHIB',
    'SOL/USDT': 'SOL',
    'BTC/USDT': 'BTC',
    'ETH/USDT': 'ETH',
    'ADA/USDT': 'ADA',
    'DOT/USDT': 'DOT',
    'LINK/USDT': 'LINK',
}

# Cache para no abusar de las APIs
_cache = {
    'fear_greed': {'value': None, 'label': None, 'ts': 0},
    'news': {},  # {symbol: {'score': 0, 'headlines': [], 'ts': 0}}
}

CACHE_TTL_FEAR = 300   # 5 minutos (el índice cambia 1x/día)
CACHE_TTL_NEWS = 60    # 1 minuto


class NewsEngine:
    """
    Motor de noticias y sentimiento.
    Añade 0-20 puntos al score del Alpha Engine.
    """

    def __init__(self, cryptopanic_token: str = None):
        self.cryptopanic_token = cryptopanic_token
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info(
            f"📰 News Engine inicializado | "
            f"CryptoPanic: {'✅' if cryptopanic_token else '❌ Sin token'} | "
            f"Fear&Greed: ✅"
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ═══════════════════════════════════════════════════════
    # FEAR & GREED INDEX
    # ═══════════════════════════════════════════════════════

    async def get_fear_greed(self) -> dict:
        """
        Obtiene el Fear & Greed Index actual.
        
        Returns:
            {'value': 25, 'label': 'Extreme Fear', 'score_boost': 10}
        """
        now = time.time()
        if (_cache['fear_greed']['value'] is not None and
                now - _cache['fear_greed']['ts'] < CACHE_TTL_FEAR):
            return _cache['fear_greed']

        try:
            session = await self._get_session()
            async with session.get(FEAR_GREED_URL) as resp:
                if resp.status != 200:
                    logger.warning(f"⚠️ Fear&Greed API: HTTP {resp.status}")
                    return _cache['fear_greed']

                data = await resp.json()
                fg_data = data.get('data', [{}])[0]
                value = int(fg_data.get('value', 50))
                label = fg_data.get('value_classification', 'Neutral')

                # Score boost: miedo extremo = oportunidad de compra
                if value <= 15:
                    score_boost = 15  # Extreme Fear → máxima oportunidad
                elif value <= 25:
                    score_boost = 10  # Fear
                elif value <= 35:
                    score_boost = 5   # Approaching Fear
                elif value <= 55:
                    score_boost = 0   # Neutral
                elif value <= 75:
                    score_boost = -5  # Greed → cuidado
                else:
                    score_boost = -10  # Extreme Greed → peligro de corrección

                result = {
                    'value': value,
                    'label': label,
                    'score_boost': score_boost,
                    'ts': now,
                }
                _cache['fear_greed'] = result
                logger.info(
                    f"😱 Fear&Greed: {value} ({label}) → "
                    f"Score boost: {score_boost:+d}"
                )
                return result

        except Exception as e:
            logger.warning(f"⚠️ Error Fear&Greed: {e}")
            return _cache['fear_greed']

    # ═══════════════════════════════════════════════════════
    # CRYPTOPANIC NEWS
    # ═══════════════════════════════════════════════════════

    async def get_news_score(self, symbol: str) -> dict:
        """
        Obtiene noticias recientes de una moneda y calcula un score.
        
        Returns:
            {'score_boost': 5, 'headlines': ['XRP wins...'], 'sentiment': 'bullish'}
        """
        coin = COIN_MAP.get(symbol, symbol.split('/')[0])
        now = time.time()

        # Cache check
        cached = _cache['news'].get(symbol)
        if cached and now - cached.get('ts', 0) < CACHE_TTL_NEWS:
            return cached

        if not self.cryptopanic_token:
            # Sin token → usar solo Fear&Greed, no news por moneda
            return {'score_boost': 0, 'headlines': [], 'sentiment': 'neutral', 'ts': now}

        try:
            session = await self._get_session()
            url = (
                f"{CRYPTOPANIC_URL}?auth_token={self.cryptopanic_token}"
                f"&currencies={coin}&filter=important&public=true"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"⚠️ CryptoPanic API: HTTP {resp.status}")
                    return {'score_boost': 0, 'headlines': [], 'sentiment': 'neutral', 'ts': now}

                data = await resp.json()
                posts = data.get('results', [])

                if not posts:
                    result = {'score_boost': 0, 'headlines': [], 'sentiment': 'neutral', 'ts': now}
                    _cache['news'][symbol] = result
                    return result

                # Analizar sentimiento de los posts
                bullish = 0
                bearish = 0
                headlines = []

                for post in posts[:10]:  # Últimos 10 posts
                    title = post.get('title', '')
                    headlines.append(title)

                    votes = post.get('votes', {})
                    positive = votes.get('positive', 0)
                    negative = votes.get('negative', 0)
                    important = votes.get('important', 0)

                    # Sentimiento basado en votos
                    if positive > negative:
                        bullish += 1
                    elif negative > positive:
                        bearish += 1

                    # Filtro por palabras clave
                    title_lower = title.lower()
                    bullish_words = ['bullish', 'surge', 'pump', 'rally', 'breakout',
                                     'adoption', 'partnership', 'launch', 'approval',
                                     'etf', 'institutional', 'win', 'victory']
                    bearish_words = ['bearish', 'crash', 'dump', 'hack', 'exploit',
                                     'lawsuit', 'ban', 'fine', 'fraud', 'fail',
                                     'bankruptcy', 'collapse']

                    if any(w in title_lower for w in bullish_words):
                        bullish += 1
                    if any(w in title_lower for w in bearish_words):
                        bearish += 1

                # Calcular score
                total = bullish + bearish
                if total == 0:
                    score_boost = 0
                    sentiment = 'neutral'
                elif bullish > bearish * 2:
                    score_boost = 10  # Muy bullish
                    sentiment = 'very_bullish'
                elif bullish > bearish:
                    score_boost = 5   # Bullish
                    sentiment = 'bullish'
                elif bearish > bullish * 2:
                    score_boost = -10  # Muy bearish
                    sentiment = 'very_bearish'
                elif bearish > bullish:
                    score_boost = -5   # Bearish
                    sentiment = 'bearish'
                else:
                    score_boost = 0
                    sentiment = 'neutral'

                result = {
                    'score_boost': score_boost,
                    'headlines': headlines[:3],
                    'sentiment': sentiment,
                    'bullish': bullish,
                    'bearish': bearish,
                    'ts': now,
                }
                _cache['news'][symbol] = result

                logger.info(
                    f"📰 {coin}: {sentiment} "
                    f"(B:{bullish}/R:{bearish}) → Score: {score_boost:+d}"
                )
                return result

        except Exception as e:
            logger.warning(f"⚠️ Error CryptoPanic {coin}: {e}")
            return {'score_boost': 0, 'headlines': [], 'sentiment': 'neutral', 'ts': now}

    # ═══════════════════════════════════════════════════════
    # SCORE COMBINADO (para el Alpha Engine)
    # ═══════════════════════════════════════════════════════

    async def get_external_score(self, symbol: str) -> dict:
        """
        Score combinado de todas las fuentes externas.
        
        Returns:
            {
                'total_boost': 15,  # Puntos extra para el Alpha Engine
                'fear_greed': {'value': 20, 'label': 'Extreme Fear', 'boost': 10},
                'news': {'sentiment': 'bullish', 'boost': 5, 'headlines': [...]},
            }
        """
        fg, news = await asyncio.gather(
            self.get_fear_greed(),
            self.get_news_score(symbol),
            return_exceptions=True
        )

        fg_boost = fg.get('score_boost', 0) if isinstance(fg, dict) else 0
        news_boost = news.get('score_boost', 0) if isinstance(news, dict) else 0

        total = max(-20, min(20, fg_boost + news_boost))  # Clamp -20 to +20

        return {
            'total_boost': total,
            'fear_greed': {
                'value': fg.get('value', 50) if isinstance(fg, dict) else 50,
                'label': fg.get('label', '?') if isinstance(fg, dict) else '?',
                'boost': fg_boost,
            },
            'news': {
                'sentiment': news.get('sentiment', 'neutral') if isinstance(news, dict) else 'neutral',
                'boost': news_boost,
                'headlines': news.get('headlines', []) if isinstance(news, dict) else [],
            },
        }

    async def get_all_scores(self, symbols: List[str]) -> Dict[str, dict]:
        """Score externo para todas las monedas."""
        results = {}
        for symbol in symbols:
            results[symbol] = await self.get_external_score(symbol)
            await asyncio.sleep(0.2)  # Rate limiting
        return results

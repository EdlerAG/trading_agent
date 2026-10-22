import re
import html
import time
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
import orjson

from app.core.config import settings
from app.core.http_client import http_pool
from app.domain.interfaces import IService


class NewsAiService(IService):
    """
    Асинхронний парсер криптоновин RSS + оцінка структурованого сентименту через Google Gemini API.
    Повертає:
    - macro_sentiment: загальний напрямок ринку [-1.0 .. +1.0]
    - geo_shock_prob: ймовірність системного шоку [0.0 .. 1.0] (злам бірж, регуляторний удар, геополітика)
    - coin_bias: специфічний сентимент по кожній монеті кошика {"BTC": float, "ETH": float, ...}
    - is_geo_shock: True, якщо geo_shock_prob > 0.75 (активує режим захисту R5: Geo-Macro Shock)
    """

    __slots__ = ("_score", "_geo_shock_prob", "_coin_bias", "_headlines", "_updated_ts", "_ttl_sec")

    RSS_SOURCES = (
        "https://news.google.com/rss/search?q=bitcoin+crypto+market+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://cointelegraph.com/rss/tag/bitcoin",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    )

    def __init__(self) -> None:
        self._score: float = 0.0
        self._geo_shock_prob: float = 0.0
        self._coin_bias: Dict[str, float] = {}
        self._headlines: List[str] = []
        self._updated_ts: float = 0.0
        self._ttl_sec: float = 900.0

    @property
    def name(self) -> str:
        return "NewsAiService"

    @property
    def macro_sentiment(self) -> float:
        return self._score

    @property
    def geo_shock_prob(self) -> float:
        return self._geo_shock_prob

    @property
    def is_geo_shock(self) -> bool:
        return self._geo_shock_prob > 0.75

    @property
    def coin_bias(self) -> Dict[str, float]:
        return dict(self._coin_bias)

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        self._headlines.clear()
        self._coin_bias.clear()

    async def fetch_headlines(self, force_refresh: bool = False) -> List[str]:
        now = time.time()
        if not force_refresh and self._headlines and (now - self._updated_ts < self._ttl_sec):
            return self._headlines

        collected: List[str] = []
        client = http_pool.get()

        for url in self.RSS_SOURCES:
            try:
                resp = await client.get(url, timeout=8.0)
                if resp.status_code != 200 or not resp.content:
                    continue
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:8]:
                    t_el = item.find("title")
                    if t_el is not None and t_el.text:
                        clean = html.unescape(t_el.text).strip()
                        clean = re.sub(r"\s+-\s+[A-Za-z0-9\s\.]+$", "", clean)
                        if len(clean) > 20 and clean not in collected:
                            collected.append(clean)
                if len(collected) >= 8:
                    break
            except Exception:
                continue

        if collected:
            self._headlines = collected[:10]
        return self._headlines

    async def fetch_market_intelligence(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Запитує Gemini API для структурованої оцінки макро-сентименту, гео-шоку та сентименту по монетах.
        """
        if not settings.ENABLE_NEWS_SENTIMENT or not settings.GEMINI_API_KEY:
            return {
                "macro_sentiment": 0.0,
                "geo_shock_prob": 0.0,
                "coin_bias": {},
                "is_geo_shock": False,
            }

        now = time.time()
        if not force_refresh and (now - self._updated_ts < self._ttl_sec):
            return {
                "macro_sentiment": self._score,
                "geo_shock_prob": self._geo_shock_prob,
                "coin_bias": dict(self._coin_bias),
                "is_geo_shock": self.is_geo_shock,
            }

        headlines = await self.fetch_headlines(force_refresh=True)
        if not headlines:
            return {
                "macro_sentiment": self._score,
                "geo_shock_prob": self._geo_shock_prob,
                "coin_bias": dict(self._coin_bias),
                "is_geo_shock": self.is_geo_shock,
            }

        formatted = "\n".join(f"- {h}" for h in headlines)
        active_syms = getattr(settings, "ACTIVE_SYMBOLS", getattr(settings, "DEFAULT_SYMBOLS", ("BTCUSDT", "ETHUSDT", "SOLUSDT")))
        active_coins = [s.replace("USDT", "") for s in active_syms]
        symbols_str = ", ".join(active_coins)

        prompt = (
            "You are an institutional crypto quantitative hedge fund strategist and risk officer.\n"
            "Analyze the short-term market impact of these latest crypto news headlines:\n\n"
            f"{formatted}\n\n"
            "Evaluate strictly:\n"
            "1. 'macro_sentiment': overall market direction from -1.0 (extreme panic/bearish) to +1.0 (extreme euphoria/bullish).\n"
            "2. 'geo_shock_prob': probability from 0.0 to 1.0 of an acute systemic shock (e.g. major exchange collapse/hack, sudden regulatory ban/indictment, war/geopolitical escalation, stablecoin depeg, or catastrophic flash crash).\n"
            f"3. 'coin_bias': specific directional bias for monitored assets ({symbols_str}) between -1.0 and +1.0 based on asset-specific catalysts (0.0 if neutral or unaffected).\n\n"
            "Return strictly a JSON object with this exact structure:\n"
            "{\n"
            '  "macro_sentiment": <float -1.0 to 1.0>,\n'
            '  "geo_shock_prob": <float 0.0 to 1.0>,\n'
            '  "coin_bias": {"BTC": <float>, "ETH": <float>, "SOL": <float>}\n'
            "}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "maxOutputTokens": 300,
            },
        }

        client = http_pool.get()
        model_candidates = list(dict.fromkeys([
            settings.GEMINI_MODEL,
            "gemini-3.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]))

        for model_name in model_candidates:
            if not model_name:
                continue
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
            try:
                resp = await client.post(url, json=payload, timeout=9.0)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
                parsed = orjson.loads(clean_json)

                macro_sent = max(-1.0, min(1.0, float(parsed.get("macro_sentiment", parsed.get("sentiment", 0.0)))))
                geo_prob = max(0.0, min(1.0, float(parsed.get("geo_shock_prob", 0.0))))
                raw_bias = parsed.get("coin_bias", {})
                bias_map = {}
                if isinstance(raw_bias, dict):
                    for k, v in raw_bias.items():
                        try:
                            coin_clean = str(k).upper().replace("USDT", "")
                            bias_map[coin_clean] = max(-1.0, min(1.0, float(v)))
                        except (ValueError, TypeError):
                            continue

                self._score = round(macro_sent, 2)
                self._geo_shock_prob = round(geo_prob, 2)
                self._coin_bias = bias_map
                self._updated_ts = now
                return {
                    "macro_sentiment": self._score,
                    "geo_shock_prob": self._geo_shock_prob,
                    "coin_bias": dict(self._coin_bias),
                    "is_geo_shock": self.is_geo_shock,
                }
            except Exception:
                continue

        return {
            "macro_sentiment": self._score,
            "geo_shock_prob": self._geo_shock_prob,
            "coin_bias": dict(self._coin_bias),
            "is_geo_shock": self.is_geo_shock,
        }

    async def get_sentiment_score(self, force_refresh: bool = False) -> float:
        intel = await self.fetch_market_intelligence(force_refresh=force_refresh)
        return float(intel.get("macro_sentiment", self._score))

    def get_cached_info(self) -> Dict[str, Any]:
        return {
            "sentiment": self._score,
            "macro_sentiment": self._score,
            "geo_shock_prob": self._geo_shock_prob,
            "is_geo_shock": self.is_geo_shock,
            "coin_bias": dict(self._coin_bias),
            "headlines": self._headlines[:5],
            "updated_at": self._updated_ts,
        }

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
    """Асинхронний парсер криптоновин RSS + оцінка сентименту через Google Gemini API."""

    __slots__ = ("_score", "_headlines", "_updated_ts", "_ttl_sec")

    RSS_SOURCES = (
        "https://news.google.com/rss/search?q=bitcoin+crypto+market+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://cointelegraph.com/rss/tag/bitcoin",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    )

    def __init__(self) -> None:
        self._score: float = 0.0
        self._headlines: List[str] = []
        self._updated_ts: float = 0.0
        self._ttl_sec: float = 900.0

    @property
    def name(self) -> str:
        return "NewsAiService"

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        self._headlines.clear()

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

    async def get_sentiment_score(self, force_refresh: bool = False) -> float:
        if not settings.ENABLE_NEWS_SENTIMENT or not settings.GEMINI_API_KEY:
            return 0.0

        now = time.time()
        if not force_refresh and (now - self._updated_ts < self._ttl_sec):
            return self._score

        headlines = await self.fetch_headlines(force_refresh=True)
        if not headlines:
            return self._score

        formatted = "\n".join(f"- {h}" for h in headlines)
        prompt = (
            "You are an institutional crypto hedge fund analyst.\n"
            "Evaluate the short-term impact of these crypto headlines on Bitcoin and major altcoins:\n\n"
            f"{formatted}\n\n"
            "Return strictly a JSON object: {\"sentiment\": <float between -1.0 and 1.0>}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "maxOutputTokens": 50,
            },
        }

        client = http_pool.get()
        for model_name in (settings.GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-2.5-flash"):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
            try:
                resp = await client.post(url, json=payload, timeout=9.0)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
                parsed = orjson.loads(clean_json)
                val = max(-1.0, min(1.0, float(parsed.get("sentiment", 0.0))))
                self._score = round(val, 2)
                self._updated_ts = now
                return self._score
            except Exception:
                continue

        return self._score

    def get_cached_info(self) -> Dict[str, Any]:
        return {
            "sentiment": self._score,
            "headlines": self._headlines[:5],
            "updated_at": self._updated_ts,
        }
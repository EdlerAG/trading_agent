import asyncio
import email.utils
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import orjson

from app.core.config import settings
from app.core.http_client import http_pool
from app.domain.interfaces import IService


class NewsAiService(IService):
    """
    Надлегкий конкурентний парсер криптоновин (RSS 2.0 + Atom) із двоконтурним аналізом:
      1) Основний контур: структурована оцінка через Google Gemini JSON API.
      2) Автономний резервний контур (Lexical Quant Scorer): працює з 0 мс затримки навіть без
         GEMINI_API_KEY або при лімітах API, виявляючи гострі системні шоки (depeg, біржовий злам,
         зупинка виведення коштів) та макро-сентимент за підтвердженням кількох джерел.
    """

    __slots__ = (
        "_score",
        "_geo_shock_prob",
        "_coin_bias",
        "_headlines",
        "_sources_ok",
        "_engine_mode",
        "_updated_ts",
        "_ttl_sec",
    )

    RSS_SOURCES: Tuple[Tuple[str, str], ...] = (
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Cointelegraph", "https://cointelegraph.com/rss"),
        ("Decrypt", "https://decrypt.co/feed"),
        ("CryptoSlate", "https://cryptoslate.com/feed/"),
        ("GoogleNews", "https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+binance+crypto+when:1d&hl=en-US&gl=US&ceid=US:en"),
    )

    MAX_FEED_BYTES: int = 262_144       # 256 KB ліміт на 1 стрічку (захист 1GB VPS RAM)
    MAX_AGE_SECONDS: float = 36 * 3600  # відсікаємо новини старіші за 36 годин

    _BULLISH_TERMS: Tuple[Tuple[str, float], ...] = (
        ("etf inflow", 0.35), ("record inflow", 0.40), ("sec approves", 0.45),
        ("approval", 0.25), ("institutional adoption", 0.30), ("rate cut", 0.30),
        ("all-time high", 0.30), ("breakout", 0.20), ("treasury buys", 0.28),
        ("accumulate", 0.20), ("surge", 0.18), ("rally", 0.18), ("bullish", 0.20),
        ("upgrade", 0.15), ("partnership", 0.12),
    )

    _BEARISH_TERMS: Tuple[Tuple[str, float], ...] = (
        ("etf outflow", -0.32), ("sec sues", -0.38), ("lawsuit", -0.25),
        ("crackdown", -0.30), ("ban", -0.28), ("liquidation", -0.22),
        ("plunge", -0.24), ("crash", -0.32), ("sell-off", -0.24), ("selloff", -0.24),
        ("bearish", -0.20), ("rate hike", -0.28), ("tariff", -0.20),
        ("delist", -0.25), ("outage", -0.22),
    )

    _SYSTEMIC_SHOCK_TERMS: Tuple[Tuple[str, float], ...] = (
        ("exchange hack", 0.55), ("binance hack", 0.65), ("withdrawals halted", 0.60),
        ("halts withdrawals", 0.60), ("usdt depeg", 0.65), ("usdc depeg", 0.60),
        ("stablecoin depeg", 0.58), ("insolven", 0.55), ("bankrupt", 0.52),
        ("doj indictment", 0.50), ("nuclear", 0.55), ("martial law", 0.50),
        ("major exploit", 0.45), ("bridge drained", 0.42), ("flash crash", 0.42),
    )

    def __init__(self) -> None:
        self._score: float = 0.0
        self._geo_shock_prob: float = 0.0
        self._coin_bias: Dict[str, float] = {}
        self._headlines: List[str] = []
        self._sources_ok: int = 0
        self._engine_mode: str = "idle"
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

    @staticmethod
    def _parse_pub_ts(raw_date: Optional[str]) -> Optional[float]:
        if not raw_date:
            return None
        txt = raw_date.strip()
        try:
            dt = email.utils.parsedate_to_datetime(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
        try:
            dt_iso = datetime.fromisoformat(txt.replace("Z", "+00:00"))
            if dt_iso.tzinfo is None:
                dt_iso = dt_iso.replace(tzinfo=timezone.utc)
            return dt_iso.timestamp()
        except Exception:
            return None

    @staticmethod
    def _fingerprint(title: str) -> str:
        words = re.findall(r"[a-z0-9]+", title.lower())
        return " ".join(words[:7])

    @classmethod
    def _extract_feed_titles(cls, xml_bytes: bytes, now_ts: float, max_items: int = 8) -> List[str]:
        out: List[str] = []
        raw_slice = xml_bytes[: cls.MAX_FEED_BYTES]
        if b"<!DOCTYPE" in raw_slice.upper() or b"<!ENTITY" in raw_slice.upper():
            return out
        try:
            root = ET.fromstring(raw_slice)
        except Exception:
            return out

        # Підтримка RSS 2.0 (<item>) та Atom (<entry>)
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry") + root.findall(".//entry")

        for item in items[:max_items]:
            t_el = item.find("title")
            if t_el is None:
                t_el = item.find("{http://www.w3.org/2005/Atom}title")
            if t_el is None or not t_el.text:
                continue

            d_el = (
                item.find("pubDate")
                or item.find("updated")
                or item.find("{http://www.w3.org/2005/Atom}updated")
                or item.find("{http://www.w3.org/2005/Atom}published")
            )
            if d_el is not None and d_el.text:
                pub_ts = cls._parse_pub_ts(d_el.text)
                if pub_ts is not None and (now_ts - pub_ts) > cls.MAX_AGE_SECONDS:
                    continue

            clean = html.unescape(t_el.text).strip()
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = re.sub(r"\s+-\s+[A-Za-z0-9\s\.]+$", "", clean).strip()
            if 18 <= len(clean) <= 240:
                out.append(clean)
        return out

    async def fetch_headlines(self, force_refresh: bool = False) -> List[str]:
        now = time.time()
        if not force_refresh and self._headlines and (now - self._updated_ts < self._ttl_sec):
            return list(self._headlines)

        client = http_pool.get()
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; QuantCoreResearch/2.1; +https://quantcore.local)",
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        }

        async def _pull_one(src_name: str, url: str) -> Tuple[str, List[str]]:
            try:
                resp = await client.get(url, timeout=6.5, headers=headers)
                if resp.status_code != 200 or not resp.content:
                    return src_name, []
                return src_name, self._extract_feed_titles(resp.content, now)
            except Exception:
                return src_name, []

        results = await asyncio.gather(*[_pull_one(nm, u) for nm, u in self.RSS_SOURCES], return_exceptions=True)

        deduped: List[str] = []
        seen_fp: set[str] = set()
        ok_cnt = 0
        for res in results:
            if isinstance(res, Exception) or not isinstance(res, tuple):
                continue
            _src, titles = res
            if titles:
                ok_cnt += 1
            for t in titles:
                fp = self._fingerprint(t)
                if not fp or fp in seen_fp:
                    continue
                seen_fp.add(fp)
                deduped.append(t)
                if len(deduped) >= 14:
                    break
            if len(deduped) >= 14:
                break

        self._sources_ok = ok_cnt
        if deduped:
            self._headlines = deduped[:12]
        return list(self._headlines)

    @classmethod
    def score_headlines_lexically(cls, headlines: List[str], active_coins: List[str]) -> Dict[str, Any]:
        """Детермінований резервний скорер без зовнішніх LLM-викликів."""
        if not headlines:
            return {"macro_sentiment": 0.0, "geo_shock_prob": 0.0, "coin_bias": {}, "is_geo_shock": False}

        sent_vals: List[float] = []
        shock_hits = 0
        shock_sum = 0.0
        coin_scores: Dict[str, List[float]] = {}
        coin_upper = {c.upper(): c.upper() for c in active_coins if c}

        for h in headlines:
            low = h.lower()
            s = 0.0
            for phrase, w in cls._BULLISH_TERMS:
                if phrase in low:
                    s += w
            for phrase, w in cls._BEARISH_TERMS:
                if phrase in low:
                    s += w
            h_shock = 0.0
            for phrase, sw in cls._SYSTEMIC_SHOCK_TERMS:
                if phrase in low:
                    h_shock = max(h_shock, sw)
            if h_shock > 0.0:
                shock_hits += 1
                shock_sum += h_shock
                s -= 0.35

            s_clamped = max(-1.0, min(1.0, s))
            if abs(s_clamped) > 1e-6:
                sent_vals.append(s_clamped)

            tokens = set(re.findall(r"[A-Z0-9]{2,10}", h.upper()))
            for tk in tokens:
                if tk in coin_upper and abs(s_clamped) > 0.05:
                    coin_scores.setdefault(tk, []).append(s_clamped)
            if ("bitcoin" in low or "btc" in low) and "BTC" in coin_upper and abs(s_clamped) > 0.05:
                coin_scores.setdefault("BTC", []).append(s_clamped)
            if ("ethereum" in low or "ether" in low) and "ETH" in coin_upper and abs(s_clamped) > 0.05:
                coin_scores.setdefault("ETH", []).append(s_clamped)
            if "solana" in low and "SOL" in coin_upper and abs(s_clamped) > 0.05:
                coin_scores.setdefault("SOL", []).append(s_clamped)

        macro = round(max(-1.0, min(1.0, sum(sent_vals) / max(2, len(sent_vals)))), 2) if sent_vals else 0.0
        # Вимагаємо >= 2 незалежних заголовки для переходу порогу R5 Geo-Shock (>0.75) у лексичному режимі
        if shock_hits >= 2:
            geo_prob = round(min(0.95, 0.40 + shock_sum * 0.65), 2)
        elif shock_hits == 1:
            geo_prob = round(min(0.65, shock_sum), 2)
        else:
            geo_prob = 0.0

        bias_out = {
            c: round(max(-1.0, min(1.0, sum(vs) / len(vs))), 2)
            for c, vs in coin_scores.items()
            if vs
        }
        return {
            "macro_sentiment": macro,
            "geo_shock_prob": geo_prob,
            "coin_bias": bias_out,
            "is_geo_shock": geo_prob > 0.75,
        }

    async def fetch_market_intelligence(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Оцінює макро-сентимент, гео-шок та сентимент по монетах (Gemini JSON API + Lexical Fallback).
        """
        if not settings.ENABLE_NEWS_SENTIMENT:
            self._engine_mode = "disabled"
            return {
                "macro_sentiment": 0.0,
                "geo_shock_prob": 0.0,
                "coin_bias": {},
                "is_geo_shock": False,
            }

        now = time.time()
        if not force_refresh and self._updated_ts > 0 and (now - self._updated_ts < self._ttl_sec):
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

        active_syms = getattr(settings, "DEFAULT_SYMBOLS", ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        active_coins = [s.replace("USDT", "").replace("1000", "") for s in active_syms[:16]]

        if not settings.GEMINI_API_KEY:
            lex = self.score_headlines_lexically(headlines, active_coins)
            self._score = float(lex["macro_sentiment"])
            self._geo_shock_prob = float(lex["geo_shock_prob"])
            self._coin_bias = dict(lex["coin_bias"])
            self._engine_mode = "lexical_fallback"
            self._updated_ts = now
            return {
                "macro_sentiment": self._score,
                "geo_shock_prob": self._geo_shock_prob,
                "coin_bias": dict(self._coin_bias),
                "is_geo_shock": self.is_geo_shock,
            }

        formatted = "\n".join(f"- {h}" for h in headlines[:10])
        symbols_str = ", ".join(active_coins)
        prompt = (
            "You are an institutional crypto quantitative hedge fund strategist and risk officer.\n"
            "Analyze the short-term market impact of these latest crypto news headlines:\n\n"
            f"{formatted}\n\n"
            "Evaluate strictly:\n"
            "1. 'macro_sentiment': overall market direction from -1.0 (extreme panic/bearish) to +1.0 (extreme euphoria/bullish).\n"
            "2. 'geo_shock_prob': probability from 0.0 to 1.0 of an acute systemic shock ( ONLY >0.75 for confirmed major exchange hack/insolvency, stablecoin depeg, sudden withdrawal halt, or acute war escalation).\n"
            f"3. 'coin_bias': specific directional bias for affected assets among ({symbols_str}) between -1.0 and +1.0 (omit unaffected coins).\n\n"
            "Return strictly a JSON object:\n"
            "{\n"
            '  "macro_sentiment": <float -1.0 to 1.0>,\n'
            '  "geo_shock_prob": <float 0.0 to 1.0>,\n'
            '  "coin_bias": {"BTC": <float>, "ETH": <float>}\n'
            "}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "maxOutputTokens": 320,
            },
        }

        client = http_pool.get()
        model_candidates = list(dict.fromkeys([
            settings.GEMINI_MODEL,
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]))

        for model_name in model_candidates:
            if not model_name:
                continue
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"x-goog-api-key": settings.GEMINI_API_KEY},
                    timeout=8.5,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
                parsed = orjson.loads(clean_json)

                macro_sent = max(-1.0, min(1.0, float(parsed.get("macro_sentiment", parsed.get("sentiment", 0.0)))))
                geo_prob = max(0.0, min(1.0, float(parsed.get("geo_shock_prob", 0.0))))
                raw_bias = parsed.get("coin_bias", {})
                bias_map: Dict[str, float] = {}
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
                self._engine_mode = f"gemini:{model_name}"
                self._updated_ts = now
                return {
                    "macro_sentiment": self._score,
                    "geo_shock_prob": self._geo_shock_prob,
                    "coin_bias": dict(self._coin_bias),
                    "is_geo_shock": self.is_geo_shock,
                }
            except Exception:
                continue

        # Якщо всі моделі Gemini недоступні (429/timeout) -> миттєвий Lexical Fallback
        lex_fb = self.score_headlines_lexically(headlines, active_coins)
        self._score = float(lex_fb["macro_sentiment"])
        self._geo_shock_prob = float(lex_fb["geo_shock_prob"])
        self._coin_bias = dict(lex_fb["coin_bias"])
        self._engine_mode = "lexical_fallback"
        self._updated_ts = now
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
            "headlines": self._headlines[:8],
            "sources_ok": self._sources_ok,
            "engine_mode": self._engine_mode,
            "updated_at": self._updated_ts,
        }

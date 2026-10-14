import re
import json
import html
import time
import xml.etree.ElementTree as ET
import requests
import numpy as np
import config

_HTTP_SESSION = requests.Session()
_HTTP_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8"
})

_NEWS_CACHE = {
    "score": 0.0,
    "headlines": [],
    "updated_ts": 0.0
}
NEWS_CACHE_TTL_SEC = 3600  # Кешуємо новини на 60 хвилин (опитування 1 раз на 4 свічки)


def fetch_latest_crypto_headlines(force_refresh: bool = False) -> list:
    now = time.time()
    if not force_refresh and _NEWS_CACHE["headlines"] and (now - _NEWS_CACHE["updated_ts"] < NEWS_CACHE_TTL_SEC):
        return _NEWS_CACHE["headlines"]

    sources = [
        "https://news.google.com/rss/search?q=bitcoin+crypto+market+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://cointelegraph.com/rss/tag/bitcoin",
        "https://www.coindesk.com/arc/outboundfeeds/rss/"
    ]

    collected_headlines = []
    timeout_sec = getattr(config, "NEWS_REQUEST_TIMEOUT", 10)

    for url in sources:
        try:
            resp = _HTTP_SESSION.get(url, timeout=(3.5, timeout_sec))
            if resp.status_code != 200 or not resp.content:
                continue

            root = ET.fromstring(resp.content)
            items = root.findall(".//item")

            for item in items[:8]:
                title_elem = item.find("title")
                if title_elem is not None and title_elem.text:
                    clean_title = html.unescape(title_elem.text).strip()
                    clean_title = re.sub(r"\s+-\s+[A-Za-z0-9\s\.]+$", "", clean_title)

                    if len(clean_title) > 20 and clean_title not in collected_headlines:
                        collected_headlines.append(clean_title)

            if len(collected_headlines) >= 8:
                break

        except Exception:
            continue

    return collected_headlines[:10]


def get_news_sentiment(force_refresh: bool = False) -> float:
    """
    Аналізує новинний фон через Gemini API з інтелектуальним кешуванням на 60 хвилин.
    """
    if not getattr(config, "ENABLE_NEWS_SENTIMENT", True):
        return 0.0

    now = time.time()
    if not force_refresh and (now - _NEWS_CACHE["updated_ts"] < NEWS_CACHE_TTL_SEC):
        return _NEWS_CACHE["score"]

    api_key = getattr(config, "GEMINI_API_KEY", None)
    if not api_key:
        return 0.0

    headlines = fetch_latest_crypto_headlines(force_refresh=True)
    if not headlines:
        return _NEWS_CACHE["score"]

    formatted_news = "\n".join([f"- {h}" for h in headlines])

    prompt = (
        "You are an institutional crypto financial analyst.\n"
        "Evaluate the short-term market impact of these recent Bitcoin/crypto headlines on BTC price:\n\n"
        f"{formatted_news}\n\n"
        "Assess whether the net sentiment is bearish, neutral, or bullish.\n"
        "Return strictly a valid JSON object with this exact key: {\"sentiment\": <float between -1.0 and 1.0>}\n"
        "-1.0 is extreme panic/bearish, 0.0 is strictly neutral, 1.0 is extreme greed/bullish."
    )

    model_name = getattr(config, "GEMINI_MODEL", "gemini-3.5-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "maxOutputTokens": 60
        }
    }

    timeout_sec = getattr(config, "NEWS_REQUEST_TIMEOUT", 10)

    try:
        resp = _HTTP_SESSION.post(url, json=payload, timeout=(3.5, timeout_sec))
        if resp.status_code != 200:
            return _NEWS_CACHE["score"]

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return _NEWS_CACHE["score"]

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return _NEWS_CACHE["score"]

        raw_output = parts[0].get("text", "").strip()
        clean_json_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_output)

        clamped = 0.0
        try:
            parsed = json.loads(clean_json_str)
            clamped = float(np.clip(float(parsed.get("sentiment", 0.0)), -1.0, 1.0))
        except Exception:
            match = re.search(r'"sentiment"\s*:\s*([-+]?(?:\d*\.\d+|\d+))', clean_json_str)
            if match:
                clamped = float(np.clip(float(match.group(1)), -1.0, 1.0))

        score_rounded = round(clamped, 2)
        _NEWS_CACHE["score"] = score_rounded
        _NEWS_CACHE["headlines"] = headlines
        _NEWS_CACHE["updated_ts"] = now

        config.logger.info(f"📰 Gemini Sentiment оновлено: {score_rounded:+.2f} (Кеш на 60 хв)")
        return score_rounded

    except Exception as e:
        config.logger.warning(f"Збій Gemini API: {e}")
        return _NEWS_CACHE["score"]
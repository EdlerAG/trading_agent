from typing import Optional
import httpx


class SharedHttpClient:
    """Singleton-пул HTTP-з'єднань із мінімальним споживанням оперативної пам'яті."""

    __slots__ = ("_client",)

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    def get(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_connections=8,
                max_keepalive_connections=3,
                keepalive_expiry=45.0,
            )
            headers = {
                "User-Agent": "QuantCore-Sovereign-Engine/23.0",
                "Accept": "application/json, application/xml, text/xml;q=0.9, */*;q=0.8",
            }
            self._client = httpx.AsyncClient(limits=limits, headers=headers, timeout=12.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


http_pool = SharedHttpClient()
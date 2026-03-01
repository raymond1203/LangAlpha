"""REST client for ginlix-data aggregates API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GinlixDataClient:
    """Low-level httpx client for ``GET /api/v1/data/aggregates``."""

    def __init__(self, base_url: str, service_token: str = ""):
        self.base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if service_token:
            headers["X-Service-Token"] = service_token
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )

    def _user_headers(self, user_id: str | None) -> dict[str, str]:
        """Build per-request headers with the caller's user ID."""
        if user_id:
            return {"X-User-Id": user_id}
        return {}

    async def get_aggregates(
        self,
        market: str,
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 5000,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV bars for a single symbol.

        ``GET /api/v1/data/aggregates/{market}/{symbol}``
        """
        params: dict[str, Any] = {
            "timespan": timespan,
            "multiplier": multiplier,
            "limit": limit,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        resp = await self.http.get(
            f"/api/v1/data/aggregates/{market}/{symbol}",
            params=params,
            headers=self._user_headers(user_id),
        )
        resp.raise_for_status()
        body = resp.json()
        return body.get("results", [])

    async def get_batch_aggregates(
        self,
        market: str,
        symbols: list[str],
        timespan: str = "day",
        multiplier: int = 1,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 5000,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch OHLCV bars for multiple symbols.

        ``GET /api/v1/data/aggregates/{market}?symbols=AAPL,TSLA``

        Returns ``{SYMBOL: {ticker, status, results: [...]}, ...}``.
        Failed symbols have ``{error: "..."}`` instead.
        """
        params: dict[str, Any] = {
            "symbols": ",".join(symbols),
            "timespan": timespan,
            "multiplier": multiplier,
            "limit": limit,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        resp = await self.http.get(
            f"/api/v1/data/aggregates/{market}",
            params=params,
            headers=self._user_headers(user_id),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self.http.aclose()

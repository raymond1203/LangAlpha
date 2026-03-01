"""ginlix-data REST client package.

Provides :class:`GinlixDataClient` for fetching aggregates from the
ginlix-data market data proxy service.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from .client import GinlixDataClient

__all__ = ["GinlixDataClient", "get_ginlix_data_client", "close_ginlix_data_client"]

_client: Optional[GinlixDataClient] = None
_lock = asyncio.Lock()


async def get_ginlix_data_client() -> GinlixDataClient:
    """Get or create a singleton :class:`GinlixDataClient`."""
    global _client
    async with _lock:
        if _client is None:
            from src.config.settings import GINLIX_DATA_URL

            service_token = __import__("os").getenv("INTERNAL_SERVICE_TOKEN", "")
            _client = GinlixDataClient(base_url=GINLIX_DATA_URL, service_token=service_token)
        return _client


async def close_ginlix_data_client() -> None:
    """Close the singleton client (call on shutdown)."""
    global _client
    async with _lock:
        if _client is not None:
            await _client.close()
            _client = None

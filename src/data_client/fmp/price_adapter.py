"""FMP implementation of PriceDataProvider.

Thin wrapper around :class:`FMPClient` that conforms to the
:class:`~src.data_client.base.PriceDataProvider` protocol.
"""

from __future__ import annotations

from typing import Any

from .fmp_client import FMPClient


class FMPPriceProvider:
    """Price data provider backed by Financial Modeling Prep."""

    async def get_intraday(
        self,
        symbol: str,
        interval: str,
        from_date: str | None = None,
        to_date: str | None = None,
        is_index: bool = False,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        api_symbol = f"^{symbol}" if is_index and not symbol.startswith("^") else symbol
        async with FMPClient() as client:
            data = await client.get_intraday_chart(
                symbol=api_symbol,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
            )
        return data or []

    async def get_daily(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        async with FMPClient() as client:
            data = await client.get_stock_price(
                symbol=symbol,
                from_date=from_date,
                to_date=to_date,
            )
        return data or []

    async def close(self) -> None:
        pass  # FMPClient manages its own lifecycle per-request

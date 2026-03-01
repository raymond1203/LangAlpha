"""
WebSocket proxy for ginlix-data real-time market aggregates.

Authenticates the frontend WebSocket via Supabase JWT, then opens a
backend WebSocket to ginlix-data using the internal service token.
Messages are forwarded bidirectionally until either side disconnects.

The entire router is only registered when ``GINLIX_DATA_ENABLED`` is
true (i.e. ``GINLIX_DATA_WS_URL`` is set) — see ``setup.py``.
"""

import asyncio
import logging
import os

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.config.settings import GINLIX_DATA_WS_URL
from src.server.auth.ws_auth import authenticate_websocket

logger = logging.getLogger(__name__)

router = APIRouter()

_INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
_ALLOWED_MARKETS = {"stock", "index", "crypto", "forex"}


@router.get("/ws/v1/market-data/status")
async def market_data_ws_status():
    """Lightweight probe — returns 200 when the WS proxy feature is enabled.
    Used by the frontend preflight check to avoid noisy WS handshake failures."""
    return {"enabled": True}


@router.websocket("/ws/v1/market-data/aggregates/{market}")
async def ws_market_data_proxy(websocket: WebSocket, market: str, interval: str = "minute"):
    """Proxy frontend WS to ginlix-data aggregate stream."""

    if market not in _ALLOWED_MARKETS:
        await websocket.close(code=1008, reason=f"Invalid market: {market}")
        return

    # Authenticate before accepting
    try:
        user_id = await authenticate_websocket(websocket)
    except Exception:
        return  # ws_auth already closed the socket

    await websocket.accept()
    logger.info("WS proxy opened: user=%s market=%s interval=%s", user_id, market, interval)

    # Build backend URL
    backend_url = f"{GINLIX_DATA_WS_URL}/ws/v1/data/aggregates/{market}?interval={interval}"
    backend_headers = {"X-User-Id": user_id}
    if _INTERNAL_SERVICE_TOKEN:
        backend_headers["X-Service-Token"] = _INTERNAL_SERVICE_TOKEN

    try:
        async with websockets.connect(
            backend_url,
            additional_headers=backend_headers,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as backend_ws:

            async def client_to_backend():
                """Forward messages from the frontend client to ginlix-data."""
                try:
                    while True:
                        msg = await websocket.receive_text()
                        await backend_ws.send(msg)
                except WebSocketDisconnect:
                    pass  # Client disconnected
                except Exception as exc:
                    logger.debug("client_to_backend closed: %s", exc)

            async def backend_to_client():
                """Forward messages from ginlix-data to the frontend client."""
                try:
                    async for msg in backend_ws:
                        await websocket.send_text(msg)
                except websockets.exceptions.ConnectionClosed:
                    pass  # Backend disconnected
                except Exception as exc:
                    logger.debug("backend_to_client closed: %s", exc)

            # Run both directions concurrently; when either finishes, cancel the other
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_backend()),
                    asyncio.create_task(backend_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except (websockets.exceptions.WebSocketException, OSError) as exc:
        logger.warning("Backend WS connection failed: %s", exc)
    finally:
        # Ensure client socket is closed
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("WS proxy closed: user=%s market=%s", user_id, market)

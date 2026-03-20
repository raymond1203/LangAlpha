"""
PriceMonitorService — Monitors stock prices via SharedWSConnectionManager
and triggers price-based automations when conditions are met.

Uses Redis SET NX locks for multi-instance deduplication.
Falls back to REST snapshot polling when WS is disconnected.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from src.server.models.automation import (
    PriceConditionType,
    PriceTriggerConfig,
    RetriggerMode,
)
from src.server.services.shared_ws_manager import SharedWSConnectionManager

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL = 60  # seconds — reload automations from DB
_POLL_INTERVAL = 30  # seconds — REST fallback polling
_REFERENCE_REFRESH_INTERVAL = 300  # seconds — refresh reference prices
_ONE_SHOT_DEDUP_TTL = 60  # seconds — short dedup for one-shot (DB status is the real guard)
_MIN_TRADING_DAY_TTL = 300  # 5 min floor for trading-day TTL

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MINUTE = 30


def _now_utc() -> datetime:
    """Return current UTC time. Extracted for testability."""
    return datetime.now(timezone.utc)


def _seconds_until_next_market_open() -> int:
    """Compute seconds from now until next US market open (9:30 AM ET, skip weekends).

    Returns at least _MIN_TRADING_DAY_TTL to avoid degenerate cases.
    Does not account for market holidays.
    """
    now_et = _now_utc().astimezone(_ET)

    # Start from tomorrow
    next_day = (now_et + timedelta(days=1)).replace(
        hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0
    )

    # Skip weekends: Saturday=5, Sunday=6
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)

    delta = (next_day - now_et).total_seconds()
    return max(int(delta), _MIN_TRADING_DAY_TTL)


class ConditionEvaluator:
    """Evaluates price conditions against current prices."""

    def __init__(self):
        # symbol → {previous_close, day_open}
        self._reference_prices: Dict[str, Dict[str, float]] = {}

    def set_reference(self, symbol: str, previous_close: float, day_open: float) -> None:
        self._reference_prices[symbol] = {
            "previous_close": previous_close,
            "day_open": day_open,
        }

    def evaluate(
        self,
        condition_type: str,
        value: float,
        reference: str,
        current_price: float,
        symbol: str,
    ) -> bool:
        """Evaluate a single condition. Returns True if condition is met."""
        if condition_type == PriceConditionType.PRICE_ABOVE:
            return current_price > value
        elif condition_type == PriceConditionType.PRICE_BELOW:
            return current_price < value
        elif condition_type in (
            PriceConditionType.PCT_CHANGE_ABOVE,
            PriceConditionType.PCT_CHANGE_BELOW,
        ):
            ref_prices = self._reference_prices.get(symbol)
            if not ref_prices:
                return False
            ref_price = ref_prices.get(reference, 0)
            if ref_price <= 0:
                return False
            pct_change = ((current_price - ref_price) / ref_price) * 100
            if condition_type == PriceConditionType.PCT_CHANGE_ABOVE:
                return pct_change > value
            else:
                return pct_change < -value
        return False

    async def refresh_references(self, symbols: List[str]) -> None:
        """Fetch reference prices (previous_close, day_open) via REST snapshots."""
        if not symbols:
            return
        try:
            from src.data_client import get_market_data_provider

            provider = await get_market_data_provider()
            snapshots = await provider.get_snapshots(symbols)
            for snap in snapshots:
                sym = snap.get("symbol", "").upper()
                if sym:
                    self.set_reference(
                        sym,
                        previous_close=snap.get("previous_close", 0),
                        day_open=snap.get("open", 0),
                    )
        except Exception:
            logger.warning("Failed to refresh reference prices", exc_info=True)


class PriceMonitorService:
    """Monitors stock prices and triggers price-based automations."""

    _instance: Optional["PriceMonitorService"] = None

    @classmethod
    def get_instance(cls) -> "PriceMonitorService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._shared_ws: Optional[SharedWSConnectionManager] = None
        self._consumer_handle = None
        self._evaluator = ConditionEvaluator()

        # symbol → [automation dicts]
        self._symbol_automations: Dict[str, List[Dict[str, Any]]] = {}
        self._monitored_symbols: set[str] = set()

        # In-memory dedup fallback when Redis is unavailable
        # automation_id → expiry timestamp (monotonic)
        self._local_locks: Dict[str, float] = {}
        self._redis_warned = False

        # Background tasks
        self._refresh_task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._ref_refresh_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the price monitor."""
        self._shared_ws = SharedWSConnectionManager.get_instance()
        self._shutdown_event.clear()

        # Initial load of price automations
        await self._load_automations()

        # Register as consumer
        self._consumer_handle = self._shared_ws.register_consumer(
            "price_monitor", self._on_message
        )

        # Subscribe to all monitored symbols
        if self._monitored_symbols:
            await self._consumer_handle.subscribe(list(self._monitored_symbols))

        # Start background loops
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(), name="price_monitor_refresh"
        )
        self._poll_task = asyncio.create_task(
            self._poll_fallback_loop(), name="price_monitor_poll"
        )
        self._ref_refresh_task = asyncio.create_task(
            self._reference_refresh_loop(), name="price_monitor_ref_refresh"
        )

        logger.info(
            "[PriceMonitor] Started — monitoring %d symbols from %d automations",
            len(self._monitored_symbols),
            sum(len(v) for v in self._symbol_automations.values()),
        )

    async def stop(self) -> None:
        """Stop the price monitor."""
        logger.info("[PriceMonitor] Stopping...")
        self._shutdown_event.set()

        for task in (self._refresh_task, self._poll_task, self._ref_refresh_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._consumer_handle:
            await self._consumer_handle.close()
            self._consumer_handle = None

        logger.info("[PriceMonitor] Stopped")

    # ─── Message Handling ────────────────────────────────────────────

    async def _on_message(self, raw_msg: str, bar: Optional[dict]) -> None:
        """Callback from SharedWSConnectionManager on each price tick."""
        if not bar:
            return

        symbol = bar["symbol"]
        current_price = bar["close"]

        automations = self._symbol_automations.get(symbol, [])
        for automation in automations:
            try:
                await self._evaluate_and_trigger(automation, current_price)
            except Exception:
                logger.error(
                    "[PriceMonitor] Error evaluating automation %s",
                    automation.get("automation_id"),
                    exc_info=True,
                )

    async def _evaluate_and_trigger(
        self, automation: Dict[str, Any], current_price: float
    ) -> None:
        """Evaluate conditions for an automation and trigger if all are met."""
        trigger_config = automation.get("trigger_config", {})
        try:
            config = PriceTriggerConfig(**trigger_config)
        except Exception:
            return

        symbol = config.symbol.upper()

        # All conditions must be met (AND logic)
        for condition in config.conditions:
            if not self._evaluator.evaluate(
                condition.type, condition.value, condition.reference,
                current_price, symbol,
            ):
                return  # At least one condition not met

        # All conditions met — try to trigger
        await self._try_trigger(automation, config, current_price)

    async def _try_trigger(
        self,
        automation: Dict[str, Any],
        config: PriceTriggerConfig,
        current_price: float,
    ) -> None:
        """Attempt to trigger an automation with Redis dedup lock."""
        automation_id = str(automation["automation_id"])
        lock_key = f"price_trigger:{automation_id}:lock"

        # Determine lock TTL based on retrigger mode
        retrigger = config.retrigger
        if retrigger.mode == RetriggerMode.ONE_SHOT:
            lock_ttl = _ONE_SHOT_DEDUP_TTL
        else:  # RECURRING
            if retrigger.cooldown_seconds is not None:
                lock_ttl = retrigger.cooldown_seconds
            else:
                lock_ttl = max(_seconds_until_next_market_open(), _MIN_TRADING_DAY_TTL)

        # Try to acquire dedup lock — Redis preferred, in-memory fallback
        acquired = await self._acquire_lock(automation_id, lock_key, lock_ttl, current_price)
        if not acquired:
            return

        logger.info(
            "[PriceMonitor] Triggering automation %s — %s price=%.2f",
            automation_id, config.symbol, current_price,
        )

        try:
            from src.server.database import automation as auto_db
            from src.server.services.automation_executor import AutomationExecutor
            from src.server.services.automation_scheduler import AutomationScheduler

            scheduler = AutomationScheduler.get_instance()
            executor = AutomationExecutor.get_instance()

            # Create execution record
            execution_id = await auto_db.create_execution(
                automation_id=automation_id,
                scheduled_at=datetime.now(timezone.utc),
                server_id=scheduler.server_id,
            )

            # Dispatch execution
            asyncio.create_task(
                executor.execute(automation, execution_id),
                name=f"price_exec_{automation_id[:8]}",
            )
        except Exception:
            logger.error(
                "[PriceMonitor] Failed to dispatch execution for %s",
                automation_id, exc_info=True,
            )

    # ─── Dedup Locking ────────────────────────────────────────────────

    async def _acquire_lock(
        self, automation_id: str, lock_key: str, lock_ttl: int, current_price: float
    ) -> bool:
        """Acquire a dedup lock via Redis, falling back to in-memory."""
        # Try Redis first
        try:
            from src.utils.cache.redis_cache import get_cache_client

            cache = get_cache_client()
            if cache.enabled and cache.client:
                lock_value = f"{current_price}:{datetime.now(timezone.utc).isoformat()}"
                acquired = await cache.client.set(lock_key, lock_value, nx=True, ex=lock_ttl)
                return bool(acquired)
        except Exception:
            pass

        # In-memory fallback (single-instance dedup only)
        if not self._redis_warned:
            self._redis_warned = True
            logger.warning("[PriceMonitor] Redis unavailable — using in-memory dedup locks")

        now = time.monotonic()
        # Clean expired entries
        self._local_locks = {k: v for k, v in self._local_locks.items() if v > now}

        if automation_id in self._local_locks:
            return False  # still locked

        self._local_locks[automation_id] = now + lock_ttl
        return True

    # ─── Background Loops ────────────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Periodically reload price automations from DB and update subscriptions."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=_REFRESH_INTERVAL
                )
                return  # shutdown
            except asyncio.TimeoutError:
                pass

            try:
                await self._load_automations()
            except Exception:
                logger.error("[PriceMonitor] Refresh failed", exc_info=True)

    async def _load_automations(self) -> None:
        """Load active price automations and update symbol subscriptions."""
        from src.server.database import automation as auto_db

        automations = await auto_db.get_active_price_automations()

        new_symbol_map: Dict[str, List[Dict[str, Any]]] = {}
        new_symbols: set[str] = set()

        for auto in automations:
            trigger_config = auto.get("trigger_config", {})
            try:
                config = PriceTriggerConfig(**trigger_config)
            except Exception:
                logger.warning(
                    "[PriceMonitor] Invalid trigger_config for automation %s",
                    auto.get("automation_id"),
                )
                continue

            symbol = config.symbol.upper()
            new_symbols.add(symbol)
            new_symbol_map.setdefault(symbol, []).append(auto)

        # Diff subscriptions
        added = new_symbols - self._monitored_symbols
        removed = self._monitored_symbols - new_symbols

        if self._consumer_handle:
            if removed:
                await self._consumer_handle.unsubscribe(list(removed))
            if added:
                await self._consumer_handle.subscribe(list(added))
                # Fetch reference prices for new symbols
                await self._evaluator.refresh_references(list(added))

        self._symbol_automations = new_symbol_map
        self._monitored_symbols = new_symbols

        if added or removed:
            logger.info(
                "[PriceMonitor] Subscriptions updated: +%d -%d (total %d symbols, %d automations)",
                len(added), len(removed), len(new_symbols),
                sum(len(v) for v in new_symbol_map.values()),
            )

    async def _poll_fallback_loop(self) -> None:
        """REST polling fallback when WS is disconnected."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=_POLL_INTERVAL
                )
                return
            except asyncio.TimeoutError:
                pass

            # Only poll if WS is disconnected
            if self._shared_ws and self._shared_ws.is_connected:
                continue

            if not self._monitored_symbols:
                continue

            try:
                await self._poll_snapshots()
            except Exception:
                logger.error("[PriceMonitor] REST poll failed", exc_info=True)

    async def _poll_snapshots(self) -> None:
        """Fetch current prices via REST and evaluate conditions."""
        from src.data_client import get_market_data_provider

        provider = await get_market_data_provider()
        symbols = list(self._monitored_symbols)

        try:
            snapshots = await provider.get_snapshots(symbols)
        except Exception:
            logger.debug("[PriceMonitor] Batch snapshot fetch failed")
            return

        for snapshot in snapshots:
            symbol = snapshot.get("symbol", "").upper()
            if not symbol:
                continue

            current_price = snapshot.get("price", 0)
            if current_price <= 0:
                continue

            # Update reference prices
            if snapshot.get("previous_close"):
                self._evaluator.set_reference(
                    symbol,
                    previous_close=snapshot["previous_close"],
                    day_open=snapshot.get("open", 0),
                )

            # Evaluate automations for this symbol
            for automation in self._symbol_automations.get(symbol, []):
                try:
                    await self._evaluate_and_trigger(automation, current_price)
                except Exception:
                    logger.error(
                        "[PriceMonitor] Poll eval error for %s",
                        automation.get("automation_id"),
                        exc_info=True,
                    )

    async def _reference_refresh_loop(self) -> None:
        """Periodically refresh reference prices for all monitored symbols."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=_REFERENCE_REFRESH_INTERVAL
                )
                return
            except asyncio.TimeoutError:
                pass

            if self._monitored_symbols:
                try:
                    await self._evaluator.refresh_references(
                        list(self._monitored_symbols)
                    )
                except Exception:
                    logger.debug("[PriceMonitor] Reference refresh failed", exc_info=True)

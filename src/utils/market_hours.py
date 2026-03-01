"""US equity market hours and phase detection.

Provides phase classification (pre/open/post/closed) and timing helpers
used by the OHLCV cache to gate background refreshes and set TTL policies.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, date
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Session boundaries (Eastern Time)
_PRE_OPEN = time(4, 0)       # Pre-market opens
_MARKET_OPEN = time(9, 30)   # Regular session opens
_MARKET_CLOSE = time(16, 0)  # Regular session closes
_POST_CLOSE = time(20, 0)    # Post-market closes

# US market holidays for 2025-2027 (NYSE/NASDAQ observed closures).
# Update annually or replace with an API call.
_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # MLK Day
    date(2025, 2, 17),   # Presidents' Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
    # 2027
    date(2027, 1, 1),    # New Year's Day
    date(2027, 1, 18),   # MLK Day
    date(2027, 2, 15),   # Presidents' Day
    date(2027, 3, 26),   # Good Friday
    date(2027, 5, 31),   # Memorial Day
    date(2027, 6, 18),   # Juneteenth (observed)
    date(2027, 7, 5),    # Independence Day (observed)
    date(2027, 9, 6),    # Labor Day
    date(2027, 11, 25),  # Thanksgiving
    date(2027, 12, 24),  # Christmas (observed)
}

MarketPhase = str  # "pre" | "open" | "post" | "closed"

_holiday_staleness_warned = False


def _is_trading_day(d: date) -> bool:
    """Return True if *d* is a weekday and not a US market holiday."""
    global _holiday_staleness_warned
    if not _holiday_staleness_warned:
        _holiday_staleness_warned = True
        max_year = max(h.year for h in _HOLIDAYS)
        if date.today().year > max_year:
            logger.warning(
                "market_hours._HOLIDAYS only covers through %d. "
                "Update the holiday set or integrate exchange_calendars.",
                max_year,
            )
    return d.weekday() < 5 and d not in _HOLIDAYS


def current_market_phase(now: datetime | None = None) -> MarketPhase:
    """Classify the current moment into a market phase.

    Args:
        now: Optional override for testability. Must be tz-aware or None.

    Returns:
        One of ``"pre"``, ``"open"``, ``"post"``, or ``"closed"``.
    """
    if now is None:
        now = datetime.now(ET)
    else:
        now = now.astimezone(ET)

    if not _is_trading_day(now.date()):
        return "closed"

    t = now.time()
    if t < _PRE_OPEN:
        return "closed"
    if t < _MARKET_OPEN:
        return "pre"
    if t < _MARKET_CLOSE:
        return "open"
    if t < _POST_CLOSE:
        return "post"
    return "closed"


def is_market_active(now: datetime | None = None) -> bool:
    """Return True during pre-market, regular, or post-market sessions."""
    return current_market_phase(now) != "closed"


def is_market_closed(now: datetime | None = None) -> bool:
    """Return True when the market is fully closed (no session active)."""
    return current_market_phase(now) == "closed"


def seconds_until_next_open(now: datetime | None = None) -> int:
    """Seconds until the next pre-market open (04:00 ET on a trading day).

    Returns 0 if a session is currently active.
    """
    if now is None:
        now = datetime.now(ET)
    else:
        now = now.astimezone(ET)

    if is_market_active(now):
        return 0

    # Walk forward day by day to find the next trading day
    candidate = now.date()
    t = now.time()

    # If we're before 04:00 on a trading day, the next open is today at 04:00
    if _is_trading_day(candidate) and t < _PRE_OPEN:
        next_open = datetime.combine(candidate, _PRE_OPEN, tzinfo=ET)
        return max(0, int((next_open - now).total_seconds()))

    # Otherwise advance to the next trading day
    from datetime import timedelta
    candidate += timedelta(days=1)
    # Safety limit: max 10 days (handles long holiday runs)
    for _ in range(10):
        if _is_trading_day(candidate):
            next_open = datetime.combine(candidate, _PRE_OPEN, tzinfo=ET)
            return max(0, int((next_open - now).total_seconds()))
        candidate += timedelta(days=1)

    # Fallback: shouldn't happen but return 12 hours as safe default
    return 43200

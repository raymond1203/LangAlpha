"""InsightService — Schedule-based US market news gathering via Tavily Research API.

Schedule (all times Eastern / America/New_York):
  - 4:00 AM  pre_market    — Overnight + pre-market news (8 PM yesterday → 4 AM)
  - 10–20    market_update  — Hourly news summaries (weekdays only)
  - 8:30 PM  post_market   — End-of-day recap

Weekends: pre_market (4 AM) and post_market (8:30 PM) only — no hourly updates.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.config.settings import get_config
from src.server.database import market_insight as insight_db

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Staleness windows: skip a job if a matching insight already exists within this window
STALENESS_WINDOWS = {
    "pre_market": timedelta(hours=4),
    "market_update": timedelta(minutes=30),
    "post_market": timedelta(hours=4),
}

INSIGHT_OUTPUT_SCHEMA = {
    "properties": {
        "headline": {
            "type": "string",
            "description": (
                "Concise headline capturing the dominant market theme "
                "(max 120 chars)"
            ),
        },
        "summary": {
            "type": "string",
            "description": "2-3 sentence overview of the most important developments",
        },
        "news_items": {
            "type": "array",
            "description": "Curated list of significant news stories",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short factual headline for this news item",
                    },
                    "body": {
                        "type": "string",
                        "description": "2-4 sentence factual summary of what happened",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL of the primary source article for this news item",
                    },
                },
            },
        },
        "topics": {
            "type": "array",
            "description": "3-5 key topic tags with trend direction",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Topic name (1-2 words)",
                    },
                    "trend": {
                        "type": "string",
                        "description": (
                            "up (stock/sector rose), "
                            "down (stock/sector fell), "
                            "or neutral"
                        ),
                    },
                },
            },
        },
    },
    "required": ["headline", "summary", "news_items", "topics"],
}


_TAIL = (
    "Only include genuinely noteworthy stories. "
    "Report facts, not predictions or recommendations. US market focus."
)


def _build_instruction(insight_type: str, now_et: datetime) -> str:
    """Build the Tavily research instruction for the given job type."""
    time_str = now_et.strftime("%A, %B %-d, %Y %-I:%M %p ET")
    today_date = now_et.strftime("%A, %B %-d, %Y")

    if insight_type == "pre_market":
        yesterday = now_et - timedelta(days=1)
        yesterday_date = yesterday.strftime("%A, %B %-d, %Y")
        return (
            f"Current time: {time_str}\n\n"
            f"Curate the most significant US financial market news "
            f"from last night ({yesterday_date} ~8 PM ET) through this morning. "
            f"For each story, provide a short headline and a 2-4 sentence "
            f"factual summary of what happened. {_TAIL}"
        )

    if insight_type == "market_update":
        window_end = now_et.strftime("%-I:%M %p")
        window_start = (now_et - timedelta(hours=1)).strftime("%-I:%M %p")
        return (
            f"Current time: {time_str}\n\n"
            f"Curate the most significant US financial market news from the "
            f"past hour ({window_start} – {window_end} ET). "
            f"For each story, provide a short headline and a 2-4 sentence "
            f"factual summary of what happened. {_TAIL}"
        )

    # post_market
    return (
        f"Current time: {time_str}\n\n"
        f"Curate the most significant US financial market news from today "
        f"({today_date}) for an end-of-day recap. "
        f"For each story, provide a short headline and a 2-4 sentence "
        f"factual summary of what happened. {_TAIL}"
    )


class InsightService:
    """Singleton background service that gathers market news on a schedule."""

    _instance: Optional["InsightService"] = None

    @classmethod
    def get_instance(cls) -> "InsightService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        # Defaults (overridden by config in start())
        self._enabled = True
        self._model = "mini"
        self._tz = ET
        # Schedule times (overridden by config)
        self._pre_market = datetime.strptime("04:00", "%H:%M").time()
        self._post_market = datetime.strptime("20:30", "%H:%M").time()
        self._update_start = datetime.strptime("10:00", "%H:%M").time()
        self._update_end = datetime.strptime("20:00", "%H:%M").time()
        self._update_interval_min = 60

    async def start(self) -> None:
        """Load config and start the schedule loop."""
        config = get_config("market_insight") or {}
        self._enabled = config.get("enabled", True)
        self._model = config.get("model", "mini")

        tz_name = config.get("timezone", "America/New_York")
        self._tz = ZoneInfo(tz_name)

        schedule = config.get("schedule", {})
        if schedule:
            self._pre_market = datetime.strptime(
                schedule.get("pre_market", "04:00"), "%H:%M"
            ).time()
            self._post_market = datetime.strptime(
                schedule.get("post_market", "20:30"), "%H:%M"
            ).time()
            self._update_start = datetime.strptime(
                schedule.get("market_update_start", "10:00"), "%H:%M"
            ).time()
            self._update_end = datetime.strptime(
                schedule.get("market_update_end", "20:00"), "%H:%M"
            ).time()
            self._update_interval_min = schedule.get(
                "market_update_interval", 60
            )

        if not self._enabled:
            logger.info("[MARKET_INSIGHT] Disabled by config")
            return

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            logger.warning(
                "[MARKET_INSIGHT] TAVILY_API_KEY not set — service disabled"
            )
            return

        self._shutdown_event.clear()
        self._task = asyncio.create_task(
            self._schedule_loop(), name="market_insight_loop"
        )

        # Log next job for visibility
        now_et = datetime.now(self._tz)
        next_job = self._next_job(now_et)
        if next_job:
            run_at, job_type = next_job
            logger.info(
                f"[MARKET_INSIGHT] Service started (model={self._model}), "
                f"next job: {job_type} at {run_at.strftime('%H:%M')} ET"
            )
        else:
            logger.info(
                f"[MARKET_INSIGHT] Service started (model={self._model}), "
                f"no more jobs today"
            )

    async def shutdown(self) -> None:
        """Gracefully stop the schedule loop."""
        logger.info("[MARKET_INSIGHT] Shutting down...")
        self._shutdown_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[MARKET_INSIGHT] Shutdown complete")

    # ------------------------------------------------------------------
    # Schedule computation
    # ------------------------------------------------------------------

    def _todays_schedule(self, now_et: datetime) -> list[tuple[datetime, str]]:
        """Compute all scheduled jobs for today (full day), sorted by time."""
        date = now_et.date()
        is_weekday = date.weekday() < 5  # Mon=0 .. Fri=4
        jobs: list[tuple[datetime, str]] = []

        # pre_market — every day
        jobs.append((
            datetime.combine(date, self._pre_market, tzinfo=self._tz),
            "pre_market",
        ))

        # market_update — weekdays only
        if is_weekday:
            t = datetime.combine(date, self._update_start, tzinfo=self._tz)
            end = datetime.combine(date, self._update_end, tzinfo=self._tz)
            while t <= end:
                jobs.append((t, "market_update"))
                t += timedelta(minutes=self._update_interval_min)

        # post_market — every day
        jobs.append((
            datetime.combine(date, self._post_market, tzinfo=self._tz),
            "post_market",
        ))

        jobs.sort(key=lambda x: x[0])
        return jobs

    def _remaining_jobs(
        self, now_et: datetime
    ) -> list[tuple[datetime, str]]:
        """Return today's jobs that are still in the future (>= now)."""
        return [
            (t, jtype) for t, jtype in self._todays_schedule(now_et) if t >= now_et
        ]

    def _next_job(
        self, now_et: datetime
    ) -> Optional[tuple[datetime, str]]:
        """Return the next job to run (today or tomorrow)."""
        remaining = self._remaining_jobs(now_et)
        if remaining:
            return remaining[0]

        # No more jobs today — return first job tomorrow
        tomorrow = now_et.date() + timedelta(days=1)
        tomorrow_start = datetime.combine(
            tomorrow, datetime.min.time(), tzinfo=self._tz
        )
        tomorrow_jobs = self._todays_schedule(tomorrow_start)
        return tomorrow_jobs[0] if tomorrow_jobs else None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _schedule_loop(self) -> None:
        """Main loop: sleep until next scheduled job, execute, repeat."""
        while not self._shutdown_event.is_set():
            now_et = datetime.now(self._tz)
            next_job = self._next_job(now_et)

            if not next_job:
                # Should never happen with a valid schedule, but guard
                logger.warning(
                    "[MARKET_INSIGHT] No scheduled jobs found, retrying in 1h"
                )
                if await self._sleep_until_or_shutdown(
                    datetime.now(self._tz) + timedelta(hours=1)
                ):
                    return
                continue

            run_at, job_type = next_job
            wait_seconds = (run_at - datetime.now(self._tz)).total_seconds()

            if wait_seconds > 0:
                logger.info(
                    f"[MARKET_INSIGHT] Next: {job_type} at "
                    f"{run_at.strftime('%H:%M')} ET "
                    f"(in {wait_seconds:.0f}s)"
                )
                if await self._sleep_until_or_shutdown(run_at):
                    return  # Shutdown requested

            # Check deduplication — skip if a recent insight of this type exists
            now_et = datetime.now(self._tz)
            if await self._is_duplicate(job_type):
                logger.info(
                    f"[MARKET_INSIGHT] Skipping {job_type} — "
                    f"recent insight already exists"
                )
                continue

            # Execute the job
            try:
                await self._generate_insight(job_type, now_et)
            except Exception as e:
                logger.error(
                    f"[MARKET_INSIGHT] {job_type} generation failed: {e}",
                    exc_info=True,
                )

    async def _sleep_until_or_shutdown(self, target: datetime) -> bool:
        """Sleep until target time. Returns True if shutdown was requested."""
        now = datetime.now(self._tz)
        wait = max((target - now).total_seconds(), 0)
        if wait <= 0:
            return False
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=wait)
            return True  # Shutdown requested
        except asyncio.TimeoutError:
            return False  # Timer elapsed normally

    async def _is_duplicate(self, job_type: str) -> bool:
        """Check if a completed insight of this type exists within the staleness window."""
        from datetime import timezone

        latest_at = await insight_db.get_latest_completed_at(type=job_type)
        if not latest_at:
            return False

        age = datetime.now(timezone.utc) - latest_at
        window = STALENESS_WINDOWS.get(job_type, timedelta(minutes=30))
        return age < window

    # ------------------------------------------------------------------
    # Insight generation
    # ------------------------------------------------------------------

    async def _generate_insight(
        self, job_type: str, now_et: datetime
    ) -> None:
        """Generate a single market insight via Tavily Research API."""
        from tavily import AsyncTavilyClient

        from src.tools.search_services.tavily.stream_parser import (
            parse_research_stream,
        )

        instruction = _build_instruction(job_type, now_et)

        logger.info(
            f"[MARKET_INSIGHT] Starting {job_type} "
            f"(model={self._model})"
        )
        start_time = time.monotonic()

        # Create DB row
        row = await insight_db.create_market_insight(
            model=self._model,
            type=job_type,
            metadata={
                "instruction": instruction,
                "schema_version": 2,
            },
        )
        insight_id = row["market_insight_id"]

        try:
            client = AsyncTavilyClient(
                api_key=os.environ["TAVILY_API_KEY"]
            )
            stream = await client.research(
                input=instruction,
                model=self._model,
                output_schema=INSIGHT_OUTPUT_SCHEMA,
                stream=True,
            )

            content_raw, sources, resolved_model = (
                await parse_research_stream(stream)
            )

            parsed = json.loads(content_raw)
            if not parsed.get("headline") or not parsed.get("news_items"):
                raise ValueError(
                    f"Incomplete Tavily output: "
                    f"headline={bool(parsed.get('headline'))}, "
                    f"news_items={len(parsed.get('news_items', []))}"
                )
            headline = parsed.get("headline", "")
            summary = parsed.get("summary", "")
            news_items = parsed.get("news_items", [])
            topics = parsed.get("topics", [])

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            await insight_db.complete_market_insight(
                market_insight_id=insight_id,
                headline=headline,
                summary=summary,
                content=news_items,
                topics=topics,
                sources=sources,
                generation_time_ms=elapsed_ms,
            )

            logger.info(
                f"[MARKET_INSIGHT] {job_type} completed: "
                f"id={insight_id}, model={resolved_model or self._model}, "
                f"time={elapsed_ms}ms"
            )

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                f"[MARKET_INSIGHT] {job_type} failed for {insight_id}: {e}",
                exc_info=True,
            )
            await insight_db.fail_market_insight(insight_id, str(e))

"""Database operations for market insights."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row
from psycopg.types.json import Json

from src.server.database.conversation import get_db_connection

logger = logging.getLogger(__name__)

CARD_COLUMNS = (
    "market_insight_id::text, type, headline, summary, topics, model, created_at, completed_at"
)
ALL_COLUMNS = (
    "market_insight_id::text, user_id, type, status, headline, summary, content, "
    "topics, sources, model, error_message, generation_time_ms, metadata, "
    "created_at, completed_at"
)


async def create_market_insight(
    model: str,
    type: str = "daily_brief",
    user_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Insert a new insight row with status='generating'."""
    insight_id = str(uuid4())
    now = datetime.now(timezone.utc)
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO market_insights
                    (market_insight_id, user_id, type, status, model, metadata, created_at)
                VALUES (%s, %s, %s, 'generating', %s, %s, %s)
                RETURNING market_insight_id, created_at
                """,
                (insight_id, user_id, type, model, Json(metadata), now),
            )
            row = await cur.fetchone()
            return dict(row)


async def complete_market_insight(
    market_insight_id: str,
    headline: str,
    summary: str,
    content: list,
    topics: list,
    sources: list,
    generation_time_ms: int,
) -> None:
    """Mark an insight as completed with generated content."""
    now = datetime.now(timezone.utc)
    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE market_insights
                SET status = 'completed',
                    headline = %s,
                    summary = %s,
                    content = %s,
                    topics = %s,
                    sources = %s,
                    generation_time_ms = %s,
                    completed_at = %s
                WHERE market_insight_id = %s
                """,
                (
                    headline,
                    summary,
                    Json(content),
                    Json(topics),
                    Json(sources),
                    generation_time_ms,
                    now,
                    market_insight_id,
                ),
            )


async def fail_market_insight(market_insight_id: str, error_message: str) -> None:
    """Mark an insight as failed."""
    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE market_insights
                SET status = 'failed', error_message = %s
                WHERE market_insight_id = %s
                """,
                (error_message, market_insight_id),
            )


async def get_market_insight(market_insight_id: str) -> Optional[dict]:
    """Get a single insight by ID (all columns)."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT {ALL_COLUMNS}
                FROM market_insights
                WHERE market_insight_id = %s
                """,
                (market_insight_id,),
            )
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_todays_market_insights(
    user_id: Optional[str] = None,
) -> list[dict]:
    """Get all completed insights for today (America/New_York).

    Returns card columns only, ordered newest first.
    If no insights exist for today, falls back to the most recent insight
    from yesterday so there is never a gap between post-market close and
    the next day's first insight.
    """
    et = ZoneInfo("America/New_York")
    today = datetime.now(et).date()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=et).astimezone(
        timezone.utc
    )
    day_end = datetime.combine(
        today + timedelta(days=1), datetime.min.time(), tzinfo=et
    ).astimezone(timezone.utc)

    user_cond = "user_id IS NULL" if user_id is None else "user_id = %s"

    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            conditions = [
                "status = 'completed'",
                "created_at >= %s",
                "created_at < %s",
                user_cond,
            ]
            params: list = [day_start, day_end]
            if user_id is not None:
                params.append(user_id)

            where = " AND ".join(conditions)
            await cur.execute(
                f"""
                SELECT {CARD_COLUMNS}
                FROM market_insights
                WHERE {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            rows = await cur.fetchall()

            if rows:
                return [dict(r) for r in rows]

            # No insights today yet — fall back to yesterday's most recent
            yesterday_start = datetime.combine(
                today - timedelta(days=1), datetime.min.time(), tzinfo=et
            ).astimezone(timezone.utc)

            fallback_conditions = [
                "status = 'completed'",
                "created_at >= %s",
                "created_at < %s",
                user_cond,
            ]
            fallback_params: list = [yesterday_start, day_start]
            if user_id is not None:
                fallback_params.append(user_id)

            fallback_where = " AND ".join(fallback_conditions)
            await cur.execute(
                f"""
                SELECT {CARD_COLUMNS}
                FROM market_insights
                WHERE {fallback_where}
                ORDER BY created_at DESC
                LIMIT 1
                """,
                fallback_params,
            )
            fallback_row = await cur.fetchone()
            return [dict(fallback_row)] if fallback_row else []


async def get_latest_completed_at(
    type: Optional[str] = None, user_id: Optional[str] = None
) -> Optional[datetime]:
    """Get the completed_at timestamp of the most recent completed insight.

    If type is None, returns the most recent completed insight of any type.
    """
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            conditions = ["status = 'completed'"]
            params: list = []

            if type is not None:
                conditions.append("type = %s")
                params.append(type)

            if user_id is None:
                conditions.append("user_id IS NULL")
            else:
                conditions.append("user_id = %s")
                params.append(user_id)

            where = " AND ".join(conditions)
            await cur.execute(
                f"""
                SELECT completed_at
                FROM market_insights
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT 1
                """,
                params,
            )
            row = await cur.fetchone()
            return row["completed_at"] if row else None

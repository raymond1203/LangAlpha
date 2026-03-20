"""Unit tests for PriceMonitorService — price monitoring and automation triggering."""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.server.models.automation import PriceConditionType, PriceTriggerConfig, RetriggerMode
from src.server.services.price_monitor import PriceMonitorService, _seconds_until_next_market_open
from src.server.services.shared_ws_manager import SharedWSConnectionManager

ET = ZoneInfo("America/New_York")


def _make_automation(
    symbol="AAPL",
    condition_type="price_below",
    value=150.0,
    reference="previous_close",
    retrigger_mode="one_shot",
    cooldown_seconds=None,
    **overrides,
):
    """Factory for automation dicts with price trigger_config."""
    auto_id = overrides.pop("automation_id", str(uuid.uuid4()))
    retrigger = {"mode": retrigger_mode}
    if cooldown_seconds is not None:
        retrigger["cooldown_seconds"] = cooldown_seconds
    return {
        "automation_id": auto_id,
        "user_id": "test-user",
        "name": f"Test {symbol} alert",
        "trigger_type": "price",
        "trigger_config": {
            "symbol": symbol,
            "conditions": [
                {"type": condition_type, "value": value, "reference": reference}
            ],
            "retrigger": retrigger,
        },
        "status": "active",
        "agent_mode": "flash",
        "instruction": "Analyze the price movement",
        "workspace_id": None,
        "cron_expression": None,
        "timezone": "UTC",
        "next_run_at": None,
        "last_run_at": None,
        "thread_strategy": "new",
        "conversation_thread_id": None,
        "max_failures": 3,
        "failure_count": 0,
        "delivery_config": {},
        "metadata": {},
        **overrides,
    }


class TestOnMessage:
    """Test _on_message dispatches to _evaluate_and_trigger correctly."""

    def setup_method(self):
        PriceMonitorService._instance = None
        SharedWSConnectionManager._instance = None

    @pytest.mark.asyncio
    async def test_evaluates_matching_symbol(self):
        svc = PriceMonitorService()
        auto = _make_automation(symbol="AAPL", condition_type="price_below", value=150.0)
        svc._symbol_automations = {"AAPL": [auto]}

        with patch.object(svc, "_evaluate_and_trigger", new_callable=AsyncMock) as mock_eval:
            bar = {"symbol": "AAPL", "close": 149.0, "open": 150.0, "high": 150.5, "low": 148.5, "volume": 1000, "time": 1710000000000}
            await svc._on_message('{"ev":"AM"}', bar)
            mock_eval.assert_called_once_with(auto, 149.0)

    @pytest.mark.asyncio
    async def test_skips_unmonitored_symbol(self):
        svc = PriceMonitorService()
        svc._symbol_automations = {"AAPL": [_make_automation()]}

        with patch.object(svc, "_evaluate_and_trigger", new_callable=AsyncMock) as mock_eval:
            bar = {"symbol": "TSLA", "close": 200.0, "open": 201.0, "high": 202.0, "low": 199.0, "volume": 500, "time": 1710000000000}
            await svc._on_message('{"ev":"AM"}', bar)
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_none_bar(self):
        svc = PriceMonitorService()
        svc._symbol_automations = {"AAPL": [_make_automation()]}

        with patch.object(svc, "_evaluate_and_trigger", new_callable=AsyncMock) as mock_eval:
            await svc._on_message('{"type":"keepalive"}', None)
            mock_eval.assert_not_called()


class TestEvaluateAndTrigger:
    """Test _evaluate_and_trigger calls _try_trigger only when conditions are met."""

    def setup_method(self):
        PriceMonitorService._instance = None

    @pytest.mark.asyncio
    async def test_triggers_when_condition_met(self):
        svc = PriceMonitorService()
        auto = _make_automation(condition_type="price_below", value=150.0)

        with patch.object(svc, "_try_trigger", new_callable=AsyncMock) as mock_trigger:
            await svc._evaluate_and_trigger(auto, 149.0)
            mock_trigger.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_trigger_when_condition_not_met(self):
        svc = PriceMonitorService()
        auto = _make_automation(condition_type="price_below", value=150.0)

        with patch.object(svc, "_try_trigger", new_callable=AsyncMock) as mock_trigger:
            await svc._evaluate_and_trigger(auto, 155.0)
            mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_invalid_trigger_config(self):
        svc = PriceMonitorService()
        auto = _make_automation()
        auto["trigger_config"] = {"invalid": True}  # missing required fields

        with patch.object(svc, "_try_trigger", new_callable=AsyncMock) as mock_trigger:
            await svc._evaluate_and_trigger(auto, 149.0)
            mock_trigger.assert_not_called()


class TestTryTrigger:
    """Test _try_trigger acquires Redis lock and dispatches execution."""

    def setup_method(self):
        PriceMonitorService._instance = None

    @pytest.mark.asyncio
    async def test_acquires_lock_and_creates_execution(self):
        svc = PriceMonitorService()
        auto = _make_automation(retrigger_mode="one_shot")

        from src.server.models.automation import PriceTriggerConfig
        config = PriceTriggerConfig(**auto["trigger_config"])

        mock_redis_client = AsyncMock()
        mock_redis_client.set = AsyncMock(return_value=True)  # lock acquired

        mock_cache = MagicMock()
        mock_cache.enabled = True
        mock_cache.client = mock_redis_client

        mock_scheduler = MagicMock()
        mock_scheduler.server_id = "test-server"

        mock_executor = AsyncMock()

        with (
            patch("src.utils.cache.redis_cache.get_cache_client", return_value=mock_cache),
            patch("src.server.database.automation.create_execution", new_callable=AsyncMock, return_value="exec-123") as mock_create_exec,
            patch("src.server.services.automation_scheduler.AutomationScheduler.get_instance", return_value=mock_scheduler),
            patch("src.server.services.automation_executor.AutomationExecutor.get_instance", return_value=mock_executor),
        ):
            await svc._try_trigger(auto, config, 149.0)

            # Lock was acquired with NX
            mock_redis_client.set.assert_called_once()
            call_kwargs = mock_redis_client.set.call_args
            assert call_kwargs.kwargs["nx"] is True

            # Execution was created
            mock_create_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_lock_not_acquired(self):
        svc = PriceMonitorService()
        auto = _make_automation(retrigger_mode="recurring")

        from src.server.models.automation import PriceTriggerConfig
        config = PriceTriggerConfig(**auto["trigger_config"])

        mock_redis_client = AsyncMock()
        mock_redis_client.set = AsyncMock(return_value=False)  # lock NOT acquired

        mock_cache = MagicMock()
        mock_cache.enabled = True
        mock_cache.client = mock_redis_client

        with patch("src.utils.cache.redis_cache.get_cache_client", return_value=mock_cache):
            await svc._try_trigger(auto, config, 149.0)
            # If lock wasn't acquired, we should have returned early
            # (no exception means success)

    @pytest.mark.asyncio
    async def test_falls_back_to_in_memory_lock_when_redis_unavailable(self):
        svc = PriceMonitorService()
        auto = _make_automation()

        from src.server.models.automation import PriceTriggerConfig
        config = PriceTriggerConfig(**auto["trigger_config"])

        mock_cache = MagicMock()
        mock_cache.enabled = False
        mock_cache.client = None

        with (
            patch("src.utils.cache.redis_cache.get_cache_client", return_value=mock_cache),
            patch("src.server.database.automation.create_execution", new_callable=AsyncMock, return_value="exec-1"),
            patch("src.server.services.automation_scheduler.AutomationScheduler.get_instance", return_value=MagicMock(server_id="s1")),
            patch("src.server.services.automation_executor.AutomationExecutor.get_instance", return_value=AsyncMock()),
        ):
            await svc._try_trigger(auto, config, 149.0)
            assert auto["automation_id"] in svc._local_locks


class TestLoadAutomations:
    """Test _load_automations loads from DB and updates subscriptions."""

    def setup_method(self):
        PriceMonitorService._instance = None
        SharedWSConnectionManager._instance = None

    @pytest.mark.asyncio
    async def test_loads_and_subscribes(self):
        svc = PriceMonitorService()
        mock_handle = AsyncMock()
        svc._consumer_handle = mock_handle

        autos = [
            _make_automation(symbol="AAPL"),
            _make_automation(symbol="TSLA"),
        ]

        mock_auto_db = MagicMock()
        mock_auto_db.get_active_price_automations = AsyncMock(return_value=autos)

        with patch("src.server.database.automation.get_active_price_automations", mock_auto_db.get_active_price_automations):
            with patch.object(svc._evaluator, "refresh_references", new_callable=AsyncMock):
                await svc._load_automations()

        assert "AAPL" in svc._monitored_symbols
        assert "TSLA" in svc._monitored_symbols
        assert len(svc._symbol_automations["AAPL"]) == 1
        assert len(svc._symbol_automations["TSLA"]) == 1
        mock_handle.subscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_removes_stale_subscriptions(self):
        svc = PriceMonitorService()
        mock_handle = AsyncMock()
        svc._consumer_handle = mock_handle
        svc._monitored_symbols = {"AAPL", "TSLA"}
        svc._symbol_automations = {"AAPL": [_make_automation(symbol="AAPL")], "TSLA": [_make_automation(symbol="TSLA")]}

        autos = [_make_automation(symbol="AAPL")]

        with patch("src.server.database.automation.get_active_price_automations", AsyncMock(return_value=autos)):
            with patch.object(svc._evaluator, "refresh_references", new_callable=AsyncMock):
                await svc._load_automations()

        assert "AAPL" in svc._monitored_symbols
        assert "TSLA" not in svc._monitored_symbols
        mock_handle.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_invalid_trigger_config(self):
        svc = PriceMonitorService()
        mock_handle = AsyncMock()
        svc._consumer_handle = mock_handle

        auto = _make_automation(symbol="AAPL")
        auto["trigger_config"] = {"bad": "config"}

        with patch("src.server.database.automation.get_active_price_automations", AsyncMock(return_value=[auto])):
            with patch.object(svc._evaluator, "refresh_references", new_callable=AsyncMock):
                await svc._load_automations()

        assert len(svc._monitored_symbols) == 0


class TestSecondsUntilNextMarketOpen:
    """Test _seconds_until_next_market_open returns correct TTL."""

    def test_monday_2pm_et_returns_next_morning(self):
        now = datetime(2026, 3, 16, 14, 0, tzinfo=ET)
        with patch("src.server.services.price_monitor._now_utc", return_value=now.astimezone(timezone.utc)):
            result = _seconds_until_next_market_open()
        assert result == 70200

    def test_friday_3pm_et_returns_monday_morning(self):
        now = datetime(2026, 3, 20, 15, 0, tzinfo=ET)
        with patch("src.server.services.price_monitor._now_utc", return_value=now.astimezone(timezone.utc)):
            result = _seconds_until_next_market_open()
        assert result == 239400

    def test_saturday_returns_monday_morning(self):
        now = datetime(2026, 3, 21, 10, 0, tzinfo=ET)
        with patch("src.server.services.price_monitor._now_utc", return_value=now.astimezone(timezone.utc)):
            result = _seconds_until_next_market_open()
        assert result == 171000

    def test_tuesday_10am_et_returns_next_morning(self):
        now = datetime(2026, 3, 17, 10, 0, tzinfo=ET)
        with patch("src.server.services.price_monitor._now_utc", return_value=now.astimezone(timezone.utc)):
            result = _seconds_until_next_market_open()
        assert result == 84600

    def test_just_before_open_returns_next_day(self):
        now = datetime(2026, 3, 17, 9, 29, 50, tzinfo=ET)
        with patch("src.server.services.price_monitor._now_utc", return_value=now.astimezone(timezone.utc)):
            result = _seconds_until_next_market_open()
        assert result == 86410


class TestTryTriggerLockTTL:
    """Test that lock TTL matches the new retrigger strategy."""

    def setup_method(self):
        PriceMonitorService._instance = None

    @pytest.mark.asyncio
    async def test_one_shot_uses_short_dedup_ttl(self):
        """one_shot: 60s dedup lock only — DB completion is the real guard."""
        svc = PriceMonitorService()
        auto = _make_automation(retrigger_mode="one_shot")
        config = PriceTriggerConfig(**auto["trigger_config"])

        mock_redis_client = AsyncMock()
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_cache = MagicMock(enabled=True, client=mock_redis_client)

        with (
            patch("src.utils.cache.redis_cache.get_cache_client", return_value=mock_cache),
            patch("src.server.database.automation.create_execution", new_callable=AsyncMock, return_value="exec-1"),
            patch("src.server.services.automation_scheduler.AutomationScheduler.get_instance", return_value=MagicMock(server_id="s1")),
            patch("src.server.services.automation_executor.AutomationExecutor.get_instance", return_value=AsyncMock()),
        ):
            await svc._try_trigger(auto, config, 149.0)
            call_kwargs = mock_redis_client.set.call_args
            assert call_kwargs.kwargs["ex"] == 60

    @pytest.mark.asyncio
    async def test_recurring_no_cooldown_uses_trading_day(self):
        """recurring with no cooldown_seconds: lock until next market open."""
        svc = PriceMonitorService()
        auto = _make_automation(retrigger_mode="recurring")
        config = PriceTriggerConfig(**auto["trigger_config"])

        mock_redis_client = AsyncMock()
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_cache = MagicMock(enabled=True, client=mock_redis_client)

        with (
            patch("src.utils.cache.redis_cache.get_cache_client", return_value=mock_cache),
            patch("src.server.services.price_monitor._seconds_until_next_market_open", return_value=70200),
            patch("src.server.database.automation.create_execution", new_callable=AsyncMock, return_value="exec-1"),
            patch("src.server.services.automation_scheduler.AutomationScheduler.get_instance", return_value=MagicMock(server_id="s1")),
            patch("src.server.services.automation_executor.AutomationExecutor.get_instance", return_value=AsyncMock()),
        ):
            await svc._try_trigger(auto, config, 149.0)
            call_kwargs = mock_redis_client.set.call_args
            assert call_kwargs.kwargs["ex"] == 70200

    @pytest.mark.asyncio
    async def test_recurring_with_explicit_cooldown(self):
        """recurring with explicit cooldown_seconds: use that value."""
        svc = PriceMonitorService()
        auto = _make_automation(retrigger_mode="recurring", cooldown_seconds=14400)
        config = PriceTriggerConfig(**auto["trigger_config"])

        mock_redis_client = AsyncMock()
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_cache = MagicMock(enabled=True, client=mock_redis_client)

        with (
            patch("src.utils.cache.redis_cache.get_cache_client", return_value=mock_cache),
            patch("src.server.database.automation.create_execution", new_callable=AsyncMock, return_value="exec-1"),
            patch("src.server.services.automation_scheduler.AutomationScheduler.get_instance", return_value=MagicMock(server_id="s1")),
            patch("src.server.services.automation_executor.AutomationExecutor.get_instance", return_value=AsyncMock()),
        ):
            await svc._try_trigger(auto, config, 149.0)
            call_kwargs = mock_redis_client.set.call_args
            assert call_kwargs.kwargs["ex"] == 14400
